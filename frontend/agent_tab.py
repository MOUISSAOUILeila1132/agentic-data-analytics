"""Onglet « Agent IA » pour Streamlit : from agent_tab import render_agent_tab"""
import pandas as pd
import requests
import streamlit as st


def _show_details(msg: dict) -> None:
    with st.expander("Détails : SQL et résultat"):
        st.code(msg["sql"], language="sql")
        if msg.get("rows"):
            st.dataframe(pd.DataFrame(msg["rows"], columns=msg["columns"]), use_container_width=True)
        caption = f"{msg.get('row_count', 0)} ligne(s) · {msg.get('attempts', 1)} tentative(s)"
        if msg.get("truncated"):
            caption += " · résultat tronqué"
        st.caption(caption)


def render_agent_tab(api_url: str, dataset_id: str) -> None:
    key = f"agent_chat_{dataset_id}"
    messages = st.session_state.setdefault(key, [])

    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("sql"):
                _show_details(m)

    question = st.chat_input("Pose une question sur ce dataset…", key=f"agent_input_{dataset_id}")
    if not question:
        return

    history = [
        {"question": m["question"], "sql": m.get("sql")}
        for m in messages
        if m["role"] == "assistant" and m.get("question")
    ][-3:]

    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analyse en cours…"):
            try:
                r = requests.post(
                    f"{api_url.rstrip('/')}/agent/ask",
                    json={"dataset_id": dataset_id, "question": question, "history": history},
                    timeout=180,
                )
                if r.status_code == 200:
                    data = r.json()
                    msg = {
                        "role": "assistant",
                        "question": question,
                        "content": data["answer"],
                        "sql": data.get("sql"),
                        "columns": data.get("columns", []),
                        "rows": data.get("rows", []),
                        "row_count": data.get("row_count", 0),
                        "truncated": data.get("truncated", False),
                        "attempts": data.get("attempts", 1),
                    }
                else:
                    detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
                    msg = {"role": "assistant", "content": f"⚠️ {detail}"}
            except requests.RequestException:
                msg = {"role": "assistant", "content": "⚠️ Impossible de joindre le backend."}
        st.markdown(msg["content"])
        if msg.get("sql"):
            _show_details(msg)
    messages.append(msg)
