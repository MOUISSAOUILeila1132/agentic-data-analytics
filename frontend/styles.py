"""Habillage visuel « v2 » : CSS global + petits composants HTML."""
import html

import streamlit as st

ACCENT = "#4F46E5"
PALETTE = ["#4F46E5", "#0D9488", "#D97706", "#DB2777", "#0284C7", "#7C3AED", "#65A30D", "#64748B"]

# Icônes (style Lucide) utilisées par la navigation latérale : une par page, dans l'ordre.
NAV_ICONS = [
    "<rect width='18' height='18' x='3' y='3' rx='2'/><path d='M3 9h18M3 15h18M12 3v18'/>",
    "<path d='M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2'/>",
    "<rect width='7' height='9' x='3' y='3' rx='1'/><rect width='7' height='5' x='14' y='3' rx='1'/>"
    "<rect width='7' height='9' x='14' y='12' rx='1'/><rect width='7' height='5' x='3' y='16' rx='1'/>",
    "<path d='m4 17 6-6-6-6M12 19h8'/>",
    "<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/>",
]


def _icon_uri(inner: str) -> str:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
        "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" + inner + "</svg>"
    )
    return 'url("data:image/svg+xml,' + svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23") + '")'


def _nav_icons_css() -> str:
    rules = []
    for i, inner in enumerate(NAV_ICONS, start=1):
        uri = _icon_uri(inner)
        body = (
            "{content:'';flex:none;width:18px;height:18px;background-color:currentColor;"
            "-webkit-mask:" + uri + " center/contain no-repeat;mask:" + uri + " center/contain no-repeat;}"
        )
        # anciennes versions de Streamlit : les <label> sont enfants directs du radiogroup
        rules.append('section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(' + str(i) + ")::before" + body)
        # versions récentes : chaque <label> est dans un <div> wrapper
        rules.append(
            'section[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div:nth-of-type(' + str(i) + ") > label::before" + body
        )
    return "\n".join(rules)


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root { --ink:#1A1A1F; --muted:#6B6B76; --line:#E8E6E1; --bg:#F6F6F3; --accent:#4F46E5; --accent-soft:#EEF0FF; }

html, body, .stApp, [class*="css"], button, input, textarea, select { font-family:'Inter', system-ui, -apple-system, sans-serif; }
.stApp { background: var(--bg); color: var(--ink); }
.block-container { padding: 2.2rem 2.6rem 3rem; max-width: 1180px; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stAppDeployButton"], .stAppDeployButton { display:none !important; visibility:hidden; }
h1, h2, h3 { letter-spacing: -0.02em; color: var(--ink); }

/* ---------- En-tête de page ---------- */
.crumb { font-size:13px; color:var(--muted); }
.page-title { margin:6px 0 0 !important; padding:0 !important; font-size:26px !important; line-height:1.2 !important; font-weight:600 !important; letter-spacing:-0.02em; }
.page-sub { margin:6px 0 0; font-size:14px; color:var(--muted); max-width:720px; }
.page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:20px; }
.pills { display:flex; gap:8px; flex-wrap:wrap; }
.pill { display:inline-flex; align-items:center; height:28px; padding:0 10px; border-radius:999px; background:#fff;
        border:1px solid var(--line); font-size:12px; font-weight:500; color:#44444E; }

/* ---------- Cartes ---------- */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) { }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-card_"] {
    background:#fff; border-color:var(--line) !important; border-radius:14px !important; box-shadow:0 1px 2px rgba(20,20,30,.04);
}
[class*="st-key-card_"] { padding:16px 18px !important; }
.tile { background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 20px; height:100%;
        box-shadow:0 1px 2px rgba(20,20,30,.04); box-sizing:border-box; }
.tile-label { font-size:12px; font-weight:500; color:var(--muted); }
.tile-value { margin-top:6px; font-size:28px; font-weight:600; letter-spacing:-0.02em; font-variant-numeric:tabular-nums; line-height:1.15; }
.tile-hint { margin-top:2px; font-size:12px; color:var(--muted); }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:1px; background:var(--line);
        border:1px solid var(--line); border-radius:14px; overflow:hidden; box-shadow:0 1px 2px rgba(20,20,30,.04); margin:4px 0 16px; }
.kpi { background:#fff; padding:18px 20px; min-width:0; }
.kpi-label { font-size:12px; font-weight:500; color:var(--muted); }
.kpi-value { margin-top:6px; font-size:24px; font-weight:600; letter-spacing:-0.02em; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }

.card-title { margin:0 !important; padding:0 !important; font-size:15px !important; line-height:1.3 !important; font-weight:600 !important; color:var(--ink); }
.card-sub { margin:2px 0 0; font-size:12px; color:var(--muted); }
.title-row { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
.count { display:inline-flex; align-items:center; justify-content:center; min-width:24px; height:22px; padding:0 8px; box-sizing:border-box;
         border-radius:999px; background:#FEF6DC; color:#8A5A00; font-size:12px; font-weight:600; }

/* ---------- Score ---------- */
.score { display:flex; align-items:center; gap:24px; flex-wrap:wrap; }
.ring { position:relative; width:132px; height:132px; flex:none; }
.ring-num { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.ring-num b { font-size:34px; line-height:1; font-weight:600; letter-spacing:-0.02em; }
.ring-num span { margin-top:2px; font-size:12px; color:var(--muted); }
.status { display:inline-flex; align-items:center; height:24px; padding:0 10px; border-radius:999px; font-size:12px; font-weight:600; }
.status-ok { background:#E8F6EC; color:#14693A; } .status-warn { background:#FEF6DC; color:#8A5A00; } .status-err { background:#FDE8E6; color:#9B1C12; }
.score-text { margin:6px 0 0; font-size:13px; line-height:1.5; color:var(--muted); max-width:240px; }

/* ---------- Avertissements ---------- */
.warn-row { display:flex; align-items:center; gap:14px; padding:12px 4px; border-bottom:1px solid #F0EEE9; }
.warn-row:last-child { border-bottom:0; }
.warn-ico { flex:none; width:32px; height:32px; border-radius:9px; background:#FEF6DC; display:flex; align-items:center; justify-content:center; }
.warn-txt { flex:1; min-width:0; font-size:14px; line-height:1.5; }

/* ---------- Barres horizontales ---------- */
.hbar { margin-top:16px; }
.hbar-top { display:flex; justify-content:space-between; font-size:14px; }
.hbar-track { margin-top:8px; height:10px; border-radius:999px; background:#EFEDE8; overflow:hidden; }
.hbar-fill { height:100%; border-radius:999px; background:var(--accent); }
.note { margin:16px 0 0; font-size:12px; color:var(--muted); }

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--line); }
section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top:1.2rem; }
.brand { display:flex; align-items:center; gap:10px; padding:0 4px; margin-bottom:14px; }
.brand-logo { width:32px; height:32px; border-radius:9px; background:var(--accent); display:flex; align-items:center; justify-content:center; }
.brand-name { font-size:15px; font-weight:600; letter-spacing:-0.01em; line-height:1.2; }
.brand-sub { font-size:12px; color:var(--muted); }
.side-label { font-size:11px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); margin:14px 4px 6px; }
.side-meta { font-size:12px; color:var(--muted); margin:-8px 4px 6px; }

section[data-testid="stSidebar"] div[role="radiogroup"], section[data-testid="stSidebar"] [data-testid="stRadioGroup"] { gap:2px; flex-direction:column; }
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] { align-items:stretch; width:100%; }
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div { width:100%; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label, section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {
    display:flex; align-items:center; gap:10px; width:100%; box-sizing:border-box; margin:0; padding:10px 12px;
    border-radius:9px; cursor:pointer; color:#44444E; transition:background .12s ease;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover, section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover { background:#F4F3EF; }
/* masque le rond du bouton radio (les deux structures DOM) */
section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child,
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child:not([data-testid="stMarkdownContainer"]) { display:none; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label p, section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p { font-size:14px; font-weight:500; margin:0; color:inherit; }
section[data-testid="stSidebar"] label:has(input:checked) { background:var(--accent-soft); color:#3730A3; }
section[data-testid="stSidebar"] label:has(input:checked) p { font-weight:600; }
__NAV_ICONS__

/* ---------- Champs & boutons ---------- */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border-radius:9px !important; border:1px solid #DAD8D2 !important; background:#fff !important; }
[data-baseweb="textarea"] { background:#FBFBF9 !important; }
[data-testid="stTextInputRootElement"], [data-testid="stMultiSelect"] [data-baseweb="select"] > div, [data-testid="stSelectbox"] [data-baseweb="select"] > div { border:1px solid #DAD8D2 !important; border-radius:9px !important; background:#fff !important; }
.stTextInput input, .stTextArea textarea { font-size:14px; }
.stTextArea textarea { font-family:'JetBrains Mono', ui-monospace, monospace !important; font-size:14px; line-height:1.7; min-height:130px; }
.stButton > button, .stDownloadButton > button, [data-testid="stPopover"] > button, [data-testid="stBaseButton-secondary"] {
    border-radius:9px; font-weight:500; border:1px solid #DAD8D2; background:#fff; min-height:40px; transition:all .12s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stPopover"] > button:hover { border-color:var(--accent); color:var(--accent); }
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.stButton > button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover { background:#4338CA; border-color:#4338CA; color:#fff; }
[data-testid="stPopover"] > button { border-radius:999px; min-height:36px; font-size:13px; }
.chip-btn .stButton > button { border-radius:999px; min-height:34px; font-size:13px; }
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:12px; background:#fff; }
[data-testid="stExpander"] summary { font-weight:500; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
[data-testid="stSegmentedControl"] button, [data-testid="stBaseButton-segmented_control"] { min-height:34px; }

/* ---------- Chat ---------- */
[data-testid="stChatMessage"] { background:transparent; border:0; padding:14px 4px; gap:14px; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background:var(--accent-soft); border-radius:16px; padding:12px 16px; }
[data-testid="stChatMessageAvatarAssistant"] { background:var(--accent) !important; }
[data-testid="stChatInput"] { border-radius:16px; border:1px solid #DAD8D2; background:#fff; box-shadow:0 4px 16px rgba(20,20,30,.06); }
.badge { display:inline-flex; align-items:center; height:22px; padding:0 9px; border-radius:999px; font-size:12px; font-weight:600; margin-bottom:6px; }
.badge-ok { background:#E8F6EC; color:#14693A; } .badge-warn { background:#FEF6DC; color:#8A5A00; }
.badge-err { background:#FDE8E6; color:#9B1C12; } .badge-info { background:var(--accent-soft); color:#3730A3; }
.empty { text-align:center; padding:26px 10px 10px; }
.empty-ico { width:48px; height:48px; margin:0 auto 12px; border-radius:14px; background:var(--accent-soft); display:flex; align-items:center; justify-content:center; }
.empty h3 { margin:0 0 4px !important; padding:0 !important; font-size:20px !important; font-weight:600 !important; }
.empty p { margin:0; color:var(--muted); font-size:14px; }
.muted { color:var(--muted); font-size:13px; }
</style>
"""


def inject() -> None:
    st.markdown(CSS.replace("__NAV_ICONS__", _nav_icons_css()), unsafe_allow_html=True)


def _e(x) -> str:
    return html.escape(str(x))


def brand() -> None:
    st.markdown(
        '<div class="brand"><div class="brand-logo"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" '
        'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 20V10"/><path d="M12 20V4"/><path d="M19 20v-7"/></svg></div>'
        '<div><div class="brand-name">Agentic Analytics</div><div class="brand-sub">Interroge tes données</div></div></div>',
        unsafe_allow_html=True,
    )


def side_label(text: str) -> None:
    st.markdown(f'<div class="side-label">{_e(text)}</div>', unsafe_allow_html=True)


def side_meta(text: str) -> None:
    st.markdown(f'<div class="side-meta">{_e(text)}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str, crumb: str, pills: list[str] | None = None) -> None:
    pills_html = "".join(f'<span class="pill">{_e(p)}</span>' for p in (pills or []))
    st.markdown(
        f'<div class="page-head"><div><div class="crumb">Datasets / {_e(crumb)}</div>'
        f'<h1 class="page-title">{_e(title)}</h1><p class="page-sub">{_e(subtitle)}</p></div>'
        f'<div class="pills">{pills_html}</div></div>',
        unsafe_allow_html=True,
    )


def tile(label: str, value, hint: str = "") -> None:
    hint_html = f'<div class="tile-hint">{_e(hint)}</div>' if hint else ""
    st.markdown(
        f'<div class="tile"><div class="tile-label">{_e(label)}</div><div class="tile-value">{_e(value)}</div>{hint_html}</div>',
        unsafe_allow_html=True,
    )


def kpi_strip(items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="kpi"><div class="kpi-label">{_e(l)}</div><div class="kpi-value">{_e(v)}</div></div>' for l, v in items
    )
    st.markdown(f'<div class="kpis">{cells}</div>', unsafe_allow_html=True)


def card_title(title: str, sub: str = "", count: int | None = None) -> None:
    count_html = f'<span class="count">{count}</span>' if count is not None else ""
    sub_html = f'<p class="card-sub">{_e(sub)}</p>' if sub else ""
    st.markdown(
        f'<div class="title-row"><h2 class="card-title">{_e(title)}</h2>{count_html}</div>{sub_html}',
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="badge badge-{kind}">{_e(text)}</span>'


def empty_state(title: str, text: str, icon: str = "") -> None:
    icon = icon or (
        '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4F46E5" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
    )
    st.markdown(
        f'<div class="empty"><div class="empty-ico">{icon}</div><h3>{_e(title)}</h3><p>{_e(text)}</p></div>',
        unsafe_allow_html=True,
    )


def score_card(score: int) -> None:
    circ = 326.7
    dash = circ * max(0, min(100, score)) / 100
    if score >= 80:
        status, cls, text = "Bonne santé", "status-ok", "Peu de problèmes détectés."
    elif score >= 60:
        status, cls, text = "À surveiller", "status-warn", "Score indicatif, calculé à partir des valeurs manquantes, des doublons et des avertissements."
    else:
        status, cls, text = "À corriger", "status-err", "Plusieurs problèmes de qualité méritent d'être traités."
    st.markdown(
        '<div class="score"><div class="ring">'
        f'<svg role="img" aria-label="Score de santé : {score} sur 100" width="132" height="132" viewBox="0 0 120 120">'
        '<circle cx="60" cy="60" r="52" fill="none" stroke="#EFEDE8" stroke-width="10"/>'
        f'<circle cx="60" cy="60" r="52" fill="none" stroke="#4F46E5" stroke-width="10" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.1f} {circ}" transform="rotate(-90 60 60)"/></svg>'
        f'<div class="ring-num"><b>{score}</b><span>sur 100</span></div></div>'
        f'<div><span class="status {cls}">{status}</span><div style="margin-top:10px;font-size:16px;font-weight:600">Santé des données</div>'
        f'<p class="score-text">{_e(text)}</p></div></div>',
        unsafe_allow_html=True,
    )


_WARN_ICON = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8A5A00" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
    '<path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
)


def warning_rows(items: list[str]) -> None:
    rows = "".join(
        f'<div class="warn-row"><div class="warn-ico">{_WARN_ICON}</div><div class="warn-txt">{_e(w)}</div></div>' for w in items
    )
    st.markdown(rows, unsafe_allow_html=True)


def hbars(rows: list[tuple[str, float, str]], scale: float) -> None:
    """rows = (libellé, valeur, texte affiché)."""
    out = []
    for label, value, text in rows:
        width = max(1.5, min(100.0, value / scale * 100)) if scale else 1.5
        out.append(
            f'<div class="hbar"><div class="hbar-top"><b style="font-weight:600">{_e(label)}</b><span style="color:#44444E">{_e(text)}</span></div>'
            f'<div class="hbar-track"><div class="hbar-fill" style="width:{width:.1f}%"></div></div></div>'
        )
    st.markdown("".join(out), unsafe_allow_html=True)
