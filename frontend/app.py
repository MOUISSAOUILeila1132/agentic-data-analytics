import itertools
import json
import time
from datetime import date

import httpx
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

import styles

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Agentic AI Data Analytics", page_icon="📊", layout="wide")
styles.inject()

# Gros datasets : l'import (envoi + conversion en Parquet) et le 1er calcul du profil / dashboard
# peuvent durer plusieurs dizaines de secondes.
UPLOAD_TIMEOUT = httpx.Timeout(1800.0, connect=10.0)
HEAVY_TIMEOUT = 300
DASHBOARD_TIMEOUT = 180

PAGES = ["Aperçu", "Profil qualité", "Dashboard", "Requête SQL", "Agent IA"]

SQL_EXAMPLES = {
    "Aperçu (10 lignes)": "SELECT * FROM data LIMIT 10",
    "Nombre de lignes": "SELECT COUNT(*) AS nb_lignes FROM data",
    "Colonnes du dataset": "DESCRIBE SELECT * FROM data",
    "Lignes distinctes": "SELECT COUNT(*) AS total, COUNT(DISTINCT *) AS distinctes FROM (SELECT * FROM data)",
}

AGENT_SUGGESTIONS = [
    "Combien de lignes contient ce dataset ?",
    "Quelles colonnes ont le plus de valeurs manquantes ?",
    "Donne-moi un résumé statistique des colonnes numériques.",
    "Quelles sont les 10 valeurs les plus fréquentes de la première colonne texte ?",
]


# ---------------------------------------------------------------- Utilitaires
def fmt_int(n) -> str:
    """15000000 -> '15 000 000' (espace insécable fine)."""
    return f"{int(n):,}".replace(",", " ")


def show_df(df: pd.DataFrame, **kwargs) -> None:
    """st.dataframe pleine largeur, compatible anciennes et nouvelles versions de Streamlit."""
    try:
        st.dataframe(df, width="stretch", **kwargs)
    except (TypeError, st.errors.StreamlitAPIException):
        st.dataframe(df, use_container_width=True, **kwargs)


def show_chart(fig, **kwargs) -> None:
    try:
        st.plotly_chart(fig, width="stretch", **kwargs)
    except (TypeError, st.errors.StreamlitAPIException):
        st.plotly_chart(fig, use_container_width=True, **kwargs)


def style_fig(fig, height: int | None = None):
    """Habille un graphique Plotly dans le style de l'interface (fond transparent, grille discrète, accent indigo)."""
    fig.update_layout(
        template="plotly_white",
        colorway=styles.PALETTE,
        margin=dict(l=8, r=8, t=8, b=8),
        font=dict(family="Inter, sans-serif", size=12, color="#44444E"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="white", font_size=12),
        title=None,
        **({"height": height} if height else {}),
    )
    fig.update_xaxes(gridcolor="#EFEDE8", linecolor="#DAD8D2", zerolinecolor="#DAD8D2")
    fig.update_yaxes(gridcolor="#EFEDE8", linecolor="#DAD8D2", zerolinecolor="#DAD8D2")

    # plotly express fige la couleur par défaut (#636efa) dans chaque trace : on la remplace par l'accent.
    def recolor(trace):
        marker = getattr(trace, "marker", None)
        if marker is not None and getattr(marker, "color", None) == "#636efa":
            marker.color = styles.ACCENT
        line = getattr(trace, "line", None)
        if line is not None and getattr(line, "color", None) == "#636efa":
            line.color = styles.ACCENT

    fig.for_each_trace(recolor)
    return fig


def segmented(label: str, options: list, default, key: str):
    """Sélecteur en segments (repli sur st.radio horizontal pour les anciennes versions de Streamlit)."""
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
        return default if value is None else value
    return st.radio(label, options, index=options.index(default), key=key, horizontal=True, label_visibility="collapsed")


_card_ids = itertools.count()


def card():
    """Conteneur « carte » (bordure + fond blanc). La clé permet de le styler via CSS dans les versions récentes de Streamlit."""
    try:
        return st.container(border=True, key=f"card_{next(_card_ids)}")
    except TypeError:  # anciennes versions : pas de paramètre key
        return st.container(border=True)



def pill_popover(label: str):
    """Pastille qui ouvre un panneau de filtre (repli sur expander)."""
    if hasattr(st, "popover"):
        return st.popover(label)
    return st.expander(label)


def api(method: str, path: str, timeout: int = 60, **kwargs):
    """Appelle l'API. Retourne (données, message_erreur)."""
    try:
        r = httpx.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except httpx.HTTPError:
        st.error("API injoignable. Lance le backend : `uvicorn app.main:app --reload` (dossier backend).")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        return None, detail
    return (r.json() if r.content else {}), None


@st.cache_data(ttl=600, show_spinner=False)
def fetch_dashboard(dataset_id: str, filters_json: str) -> dict:
    """Appelle l'API dashboard (résultat mis en cache par dataset + filtres)."""
    try:
        r = httpx.post(
            f"{API_URL}/datasets/{dataset_id}/dashboard",
            content=filters_json,
            headers={"Content-Type": "application/json"},
            timeout=DASHBOARD_TIMEOUT,
        )
    except httpx.HTTPError:
        raise RuntimeError("API injoignable. Lance le backend : `uvicorn app.main:app --reload` (dossier backend).")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(str(detail))  # une exception n'est pas mise en cache
    return r.json()


def show_agent_details(msg: dict) -> None:
    """Affiche le SQL exécuté et le tableau de résultat d'une réponse de l'agent."""
    with st.expander("SQL et résultat"):
        st.code(msg["sql"], language="sql")
        if msg.get("rows"):
            show_df(pd.DataFrame(msg["rows"], columns=msg["columns"]), hide_index=True)
        caption = f"{msg.get('row_count', 0)} ligne(s) · {msg.get('attempts', 1)} tentative(s)"
        if msg.get("truncated"):
            caption += " · résultat tronqué"
        st.caption(caption)


def type_stream(text: str):
    """Effet « machine à écrire » pour les réponses de l'agent."""
    for word in text.split(" "):
        yield word + " "
        time.sleep(0.012)


# Conserve l'état des filtres / de l'éditeur SQL quand on change de page
# (Streamlit supprime l'état d'un widget qui n'est pas affiché pendant un run).
for _k in list(st.session_state.keys()):
    if isinstance(_k, str) and _k.startswith(("dash_cat_", "dash_date_", "sql_text_")):
        st.session_state[_k] = st.session_state[_k]


# ---------------------------------------------------------------- Barre latérale
datasets, err = api("GET", "/datasets")
if err:
    st.sidebar.error(err)
    st.stop()

with st.sidebar:
    styles.brand()

    dataset_id, d = None, None
    if datasets:
        ids = [x["id"] for x in datasets]
        meta = {x["id"]: x for x in datasets}
        labels = {x["id"]: x["filename"] for x in datasets}
        default_index = ids.index(st.session_state["active_id"]) if st.session_state.get("active_id") in ids else 0

        styles.side_label("Dataset actif")
        dataset_id = st.selectbox("Dataset", ids, index=default_index, format_func=labels.get, label_visibility="collapsed")
        st.session_state["active_id"] = dataset_id
        d = meta[dataset_id]
        styles.side_meta(f"{fmt_int(d['rows'])} lignes · {d['columns']} colonnes")

        styles.side_label("Navigation")
        page = st.radio("Navigation", PAGES, key="page", label_visibility="collapsed")
    else:
        page = None

    styles.side_label("Données")
    with st.expander("Importer un fichier", expanded=not datasets):
        uploaded = st.file_uploader("Fichier", type=["csv", "xlsx", "parquet"], label_visibility="collapsed")
        if uploaded and st.button("Importer", type="primary", use_container_width=True):
            uploaded.seek(0)
            with st.spinner("Import en cours… la conversion d'un gros fichier peut prendre un moment."):
                # on passe l'objet fichier (envoi par blocs) et non uploaded.getvalue() (copie complète en mémoire)
                data, err = api(
                    "POST",
                    "/datasets",
                    timeout=UPLOAD_TIMEOUT,
                    files={"file": (uploaded.name, uploaded, uploaded.type or "application/octet-stream")},
                )
            if err:
                st.error(err)
            else:
                st.session_state["active_id"] = data["id"]
                st.toast(f"« {data['filename']} » importé ({fmt_int(data['rows'])} lignes)")
                st.rerun()

    if datasets:
        with st.expander("Zone sensible"):
            confirm = st.checkbox("Je confirme la suppression", key=f"confirm_del_{dataset_id}")
            if st.button("Supprimer ce dataset", disabled=not confirm, use_container_width=True):
                _, err = api("DELETE", f"/datasets/{dataset_id}")
                if err:
                    st.error(err)
                else:
                    st.session_state.pop("active_id", None)
                    st.session_state.pop(f"result_{dataset_id}", None)
                    st.session_state.pop(f"agent_chat_{dataset_id}", None)
                    st.rerun()

if not datasets:
    styles.page_header(
        "Bienvenue",
        "Explore, nettoie et interroge tes données en langage naturel.",
        "Nouveau",
        ["CSV", "Excel", "Parquet"],
    )
    with card():
        styles.empty_state(
            "Commence par importer un fichier",
            "Utilise le panneau de gauche : ton dataset sera analysé automatiquement.",
            icon='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4F46E5" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/></svg>',
        )
    st.stop()

file_ext = d["filename"].rsplit(".", 1)[-1].upper() if "." in d["filename"] else "Données"
PILLS = [file_ext, f"{fmt_int(d['rows'])} lignes", f"{d['columns']} colonnes"]


# ================================================================ Aperçu
def page_preview() -> None:
    styles.page_header(
        "Aperçu des données",
        "Parcours les premières lignes, filtre les colonnes et exporte ce que tu vois.",
        d["filename"],
        PILLS,
    )
    with card():
        c_search, c_cols, c_rows = st.columns([2.2, 2, 3])
        with c_rows:
            n_rows = segmented("Lignes chargées", [25, 50, 100, 250, 500], 50, key="preview_rows")

        data, err = api("GET", f"/datasets/{dataset_id}/preview", params={"rows": n_rows})
        if err:
            st.error(err)
            return
        df_prev = pd.DataFrame(data["rows"], columns=data["columns"])

        with c_search:
            search = st.text_input("Rechercher", placeholder="Rechercher dans l'aperçu", label_visibility="collapsed")
        with c_cols:
            chosen = st.multiselect("Colonnes", list(df_prev.columns), placeholder="Toutes les colonnes", label_visibility="collapsed")

        view = df_prev[chosen] if chosen else df_prev
        if search:
            mask = view.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            view = view[mask]

        show_df(view, hide_index=True, height=440)
        b1, b2 = st.columns([4, 1.3])
        b1.caption(f"{len(view)} ligne(s) affichée(s) sur {len(df_prev)} chargées · {len(view.columns)} colonne(s)")
        b2.download_button("Exporter en CSV", view.to_csv(index=False).encode("utf-8"), "apercu.csv", "text/csv", use_container_width=True)


# ================================================================ Profil qualité
def page_profile() -> None:
    styles.page_header(
        "Profil qualité",
        "Un diagnostic rapide : valeurs manquantes, doublons et valeurs potentiellement aberrantes.",
        d["filename"],
        PILLS,
    )
    with st.spinner("Calcul du profil qualité (mis en cache ensuite)…"):
        prof, err = api("GET", f"/datasets/{dataset_id}/profile", timeout=HEAVY_TIMEOUT)
    if err:
        st.error(err)
        return

    cols_info = prof["columns"]
    total_rows = max(int(prof["rows"]), 1)
    avg_missing = sum((c.get("missing_pct") or 0) for c in cols_info) / max(len(cols_info), 1)
    dup_pct = prof["duplicate_rows"] / total_rows * 100
    score = max(0, round(100 - avg_missing * 2 - dup_pct * 2 - len(prof["warnings"]) * 3))

    left, right = st.columns([1.15, 2])
    with left:
        with card():
            styles.score_card(score)
    with right:
        t1, t2, t3 = st.columns(3)
        with t1:
            styles.tile("Lignes", fmt_int(prof["rows"]))
        with t2:
            styles.tile("Colonnes", prof["columns_count"])
        with t3:
            styles.tile("Doublons", fmt_int(prof["duplicate_rows"]), f"{dup_pct:.2f} % des lignes".replace(".", ","))

    warnings = prof["warnings"]
    with card():
        styles.card_title("Avertissements", count=len(warnings))
        if not warnings:
            st.success("Aucun problème de qualité détecté.")
        else:
            styles.warning_rows(warnings[:3])
            if len(warnings) > 3:
                with st.expander(f"Voir les {len(warnings) - 3} autres avertissements"):
                    styles.warning_rows(warnings[3:])

    cols_df = pd.DataFrame(
        [
            {
                "Colonne": c["name"],
                "Type": c["kind"],
                "dtype": c["dtype"],
                "% manquants": c["missing_pct"],
                "Valeurs uniques": c["unique"],
                "Aberrantes (IQR)": c.get("outliers_iqr"),
            }
            for c in cols_info
        ]
    )

    with card():
        styles.card_title("Détail par colonne")
        f1, f2, f3 = st.columns([2, 3, 1.6])
        kinds = ["Tous"] + sorted(cols_df["Type"].dropna().unique().tolist())
        with f1:
            name_q = st.text_input("Nom", placeholder="Filtrer par nom", label_visibility="collapsed")
        with f2:
            sel_kind = segmented("Type", kinds, "Tous", key="profile_kind")
        with f3:
            only_issues = st.toggle("Problèmes seulement")

        view = cols_df
        if sel_kind != "Tous":
            view = view[view["Type"] == sel_kind]
        if name_q:
            view = view[view["Colonne"].str.contains(name_q, case=False, na=False)]
        if only_issues:
            view = view[(view["% manquants"].fillna(0) > 0) | (view["Aberrantes (IQR)"].fillna(0) > 0)]

        show_df(
            view,
            hide_index=True,
            column_config={
                "% manquants": st.column_config.ProgressColumn("% manquants", min_value=0, max_value=100, format="%.1f %%"),
                "Valeurs uniques": st.column_config.NumberColumn(format="%d"),
                "Aberrantes (IQR)": st.column_config.NumberColumn(format="%d"),
            },
        )
        st.caption(f"{len(view)} colonne(s) affichée(s) sur {len(cols_df)}")

    v1, v2 = st.columns(2)
    with v1:
        with card():
            styles.card_title("Répartition des types")
            counts = cols_df["Type"].value_counts().reset_index()
            counts.columns = ["Type", "Colonnes"]
            fig = px.pie(counts, names="Type", values="Colonnes", hole=0.62)
            fig.update_traces(textinfo="percent", marker=dict(line=dict(color="#fff", width=2)))
            show_chart(style_fig(fig, height=280))
    with v2:
        with card():
            styles.card_title("Colonnes les plus incomplètes")
            top = cols_df[cols_df["% manquants"].fillna(0) > 0].nlargest(8, "% manquants")
            if top.empty:
                st.info("Aucune valeur manquante.")
            else:
                scale = float(top["% manquants"].max())
                styles.hbars(
                    [(r["Colonne"], float(r["% manquants"]), f"{r['% manquants']:.1f} %".replace(".", ",")) for _, r in top.iterrows()],
                    scale,
                )
                st.markdown('<p class="note">Barres affichées relativement à la colonne la plus incomplète.</p>', unsafe_allow_html=True)


# ================================================================ Dashboard
def page_dashboard() -> None:
    styles.page_header(
        "Dashboard",
        "Vue d'ensemble générée automatiquement à partir des colonnes du dataset.",
        d["filename"],
        PILLS,
    )
    cat_prefix = f"dash_cat_{dataset_id}__"
    date_prefix = f"dash_date_{dataset_id}__"

    # Filtres choisis (l'état des widgets est déjà dans session_state au début du rerun)
    cat_filters, date_filters = {}, {}
    for key, val in list(st.session_state.items()):
        if not isinstance(key, str):
            continue
        if key.startswith(cat_prefix) and val:
            cat_filters[key[len(cat_prefix):]] = list(val)
        elif key.startswith(date_prefix) and isinstance(val, (tuple, list)) and len(val) == 2:
            date_filters[key[len(date_prefix):]] = [x.isoformat() for x in val]

    def reset_filters():
        for k in [k for k in st.session_state if isinstance(k, str) and k.startswith((cat_prefix, date_prefix))]:
            del st.session_state[k]

    try:
        with st.spinner("Calcul du dashboard…"):
            dash = fetch_dashboard(dataset_id, json.dumps({"categorical": cat_filters, "dates": date_filters}, sort_keys=True))
    except RuntimeError as e:
        st.error(str(e))
        return

    opts = dash["filter_options"]
    items = [("cat", c, v) for c, v in opts["categorical"].items()] + [("date", c, r) for c, r in opts["temporal"].items()]
    if items:
        with card():
            active = len(cat_filters) + len(date_filters)
            st.caption("Filtres" + (f" · {active} actif(s)" if active else ""))
            for start in range(0, len(items), 6):
                chunk = items[start:start + 6]
                cols = st.columns(6)
                for col_ui, (kind, name, spec) in zip(cols, chunk):
                    with col_ui:
                        if kind == "cat":
                            n = len(st.session_state.get(f"{cat_prefix}{name}") or [])
                            with pill_popover(f"{name} · {n}" if n else name):
                                st.multiselect(name, spec, key=f"{cat_prefix}{name}", placeholder="Tout")
                        else:
                            lo, hi = date.fromisoformat(spec["min"]), date.fromisoformat(spec["max"])
                            with pill_popover(name if name not in date_filters else f"{name} · filtré"):
                                st.date_input(name, (lo, hi), min_value=lo, max_value=hi, key=f"{date_prefix}{name}")
            if active:
                st.button("Réinitialiser les filtres", on_click=reset_filters)

    styles.kpi_strip([(k["label"], k["value"]) for k in dash["kpis"]])

    for w in dash["warnings"]:
        st.warning(w)

    widgets = dash["widgets"]
    for i in range(0, len(widgets), 2):
        for gcol, w in zip(st.columns(2), widgets[i:i + 2]):
            with gcol, card():
                fig = pio.from_json(w["figure_json"])
                title = ""
                if fig.layout.title is not None and fig.layout.title.text:
                    title = fig.layout.title.text
                if title:
                    styles.card_title(title)
                show_chart(style_fig(fig, height=320), key=f"dash_{dataset_id}_{w['id']}")
                with st.expander("SQL et données"):
                    st.code(w["sql"], language="sql")
                    show_df(pd.DataFrame(w["rows"], columns=w["columns"]), hide_index=True)
                    st.caption(f"{w['row_count']} ligne(s)")


# ================================================================ Requête SQL
def page_sql() -> None:
    styles.page_header(
        "Requête SQL",
        "Le dataset est accessible sous le nom de table « data ». Seules les requêtes SELECT sont autorisées.",
        d["filename"],
        PILLS,
    )
    sql_key = f"sql_text_{dataset_id}"
    result_key = f"result_{dataset_id}"
    hist_key = f"sql_hist_{dataset_id}"
    st.session_state.setdefault(sql_key, "SELECT * FROM data LIMIT 10")
    history_sql = st.session_state.setdefault(hist_key, [])

    def set_sql(value: str):
        st.session_state[sql_key] = value

    with card():
        st.caption("Exemples")
        ex_cols = st.columns(len(SQL_EXAMPLES))
        for col_ui, (name, q) in zip(ex_cols, SQL_EXAMPLES.items()):
            with col_ui:
                st.button(name, key=f"ex_{dataset_id}_{name}", on_click=set_sql, args=(q,), use_container_width=True)

        st.text_area("Requête SQL", key=sql_key, height=150, label_visibility="collapsed")
        r1, r2 = st.columns([1, 4])
        with r1:
            run = st.button("Exécuter", type="primary", use_container_width=True)
        with r2:
            if history_sql:
                with st.expander("Historique"):
                    for idx, q in enumerate(reversed(history_sql)):
                        st.button(
                            q[:70] + ("…" if len(q) > 70 else ""),
                            key=f"hist_{dataset_id}_{idx}",
                            on_click=set_sql,
                            args=(q,),
                            use_container_width=True,
                        )

    if run:
        query = st.session_state[sql_key]
        with st.spinner("Exécution…"):
            res, err = api("POST", f"/datasets/{dataset_id}/query", json={"sql": query})
        if err:
            st.session_state.pop(result_key, None)
            st.error(err)
        else:
            st.session_state[result_key] = res
            if query not in history_sql:
                history_sql.append(query)
                del history_sql[:-8]
            st.toast("Requête exécutée")

    res = st.session_state.get(result_key)
    if not res:
        return

    df = pd.DataFrame(res["rows"], columns=res["columns"])
    with card():
        styles.card_title("Résultat")
        m1, m2, m3 = st.columns(3)
        with m1:
            styles.tile("Lignes", fmt_int(res["row_count"]))
        with m2:
            styles.tile("Colonnes", len(df.columns))
        with m3:
            styles.tile("Temps", f"{res['elapsed_ms']} ms")
        st.write("")
        if res["truncated"]:
            st.warning("Résultat tronqué : la limite de lignes a été atteinte.")
        show_df(df, hide_index=True, height=340)
        st.download_button("Exporter en CSV", df.to_csv(index=False).encode("utf-8"), "resultat.csv", "text/csv")

    if len(df) > 0 and len(df.columns) >= 1:
        with card():
            styles.card_title("Visualiser ce résultat")
            kind = segmented("Type", ["Barres", "Courbe", "Nuage de points", "Histogramme"], "Barres", key="sql_chart_kind")
            cols = list(df.columns)
            a, b, c = st.columns(3)
            x = a.selectbox("Axe X", cols, index=0)
            if kind == "Histogramme":
                fig = px.histogram(df, x=x)
            else:
                y = b.selectbox("Axe Y", cols, index=min(1, len(cols) - 1))
                color = c.selectbox("Couleur (optionnel)", ["—"] + cols)
                plot = {"Barres": px.bar, "Courbe": px.line, "Nuage de points": px.scatter}[kind]
                fig = plot(df, x=x, y=y, color=None if color == "—" else color)
            show_chart(style_fig(fig, height=360))


# ================================================================ Agent IA
def page_agent() -> None:
    top_l, top_r = st.columns([4, 1.3])
    with top_l:
        styles.page_header(
            "Agent IA",
            "Pose une question en français ou en anglais : l'agent écrit une requête SELECT, l'exécute, puis t'explique le résultat.",
            d["filename"],
        )

    chat_key = f"agent_chat_{dataset_id}"
    pending_key = f"agent_pending_{dataset_id}"
    messages = st.session_state.setdefault(chat_key, [])

    def ask_suggestion(q: str):
        st.session_state[pending_key] = q

    def reset_chat():
        st.session_state[chat_key] = []

    with top_r:
        if messages:
            st.button("Nouvelle conversation", on_click=reset_chat, use_container_width=True)

    if not messages:
        with card():
            styles.empty_state("Que veux-tu savoir sur tes données ?", "Choisis une idée ci-dessous ou écris ta propre question.")
            sc = st.columns(2)
            for i, s in enumerate(AGENT_SUGGESTIONS):
                sc[i % 2].button(s, key=f"sugg_{dataset_id}_{i}", on_click=ask_suggestion, args=(s,), use_container_width=True)

    for m in messages:
        with st.chat_message(m["role"]):
            if m.get("badge"):
                st.markdown(styles.badge(*m["badge"]), unsafe_allow_html=True)
            st.markdown(m["content"])
            if m.get("sql"):
                show_agent_details(m)

    question = st.chat_input("Ex. : Quel est le montant total des ventes par région ?", key=f"agent_input_{dataset_id}")
    question = question or st.session_state.pop(pending_key, None)
    if not question:
        return

    # Contexte de conversation : les 3 dernières questions avec leur SQL
    history = [
        {"question": m["question"], "sql": m.get("sql")}
        for m in messages
        if m["role"] == "assistant" and m.get("question")
    ][-3:]

    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("L'agent analyse tes données…"):
            out, err = api(
                "POST",
                "/agent/ask",
                timeout=180,  # l'appel au LLM peut être long
                json={"dataset_id": dataset_id, "question": question, "history": history},
            )
        if err:
            msg = {"role": "assistant", "content": f"⚠️ {err}", "badge": ("Erreur", "err")}
        else:
            badge_map = {
                "clarification": ("Précision nécessaire", "info"),
                "impossible": ("Impossible", "warn"),
                "error": ("Erreur", "err"),
            }
            msg = {
                "role": "assistant",
                "question": question,
                "content": out["answer"],
                "badge": badge_map.get(out.get("status", "ok"), ("Réponse", "ok")),
                "sql": out.get("sql"),
                "columns": out.get("columns", []),
                "rows": out.get("rows", []),
                "row_count": out.get("row_count", 0),
                "truncated": out.get("truncated", False),
                "attempts": out.get("attempts", 1),
            }
        st.markdown(styles.badge(*msg["badge"]), unsafe_allow_html=True)
        st.write_stream(type_stream(msg["content"]))
        if msg.get("sql"):
            show_agent_details(msg)
    messages.append(msg)


# ---------------------------------------------------------------- Routage
{
    "Aperçu": page_preview,
    "Profil qualité": page_profile,
    "Dashboard": page_dashboard,
    "Requête SQL": page_sql,
    "Agent IA": page_agent,
}[page]()
