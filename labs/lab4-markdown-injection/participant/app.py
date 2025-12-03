"""Conversational Streamlit UI for Lab 4 – Markdown Injection."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Dict, List

import requests
import streamlit as st


DEFAULT_BASE_URL = "http://211.115.110.156:8000"
DEFAULT_ANALYST_NOTE = "Benign user requested a concise summary and chart preview."

st.set_page_config(page_title="Lab 4 Chat Client", layout="wide")
st.title("Lab 4 – Markdown Injection Chat Client")
st.caption("Connect to the lab server, upload one Markdown payload, and chat with the agent.")


def init_state():
    st.session_state.setdefault("base_url", DEFAULT_BASE_URL)
    if "participant_id" not in st.session_state:
        st.session_state["participant_id"] = f"attendee-{uuid4().hex[:6]}"
    st.session_state.setdefault("analyst_note", DEFAULT_ANALYST_NOTE)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("last_health", {})
    st.session_state.setdefault("last_scenario", {})


def request_json(method: str, url: str, **kwargs):
    timeout = kwargs.pop("timeout", 30)
    resp = requests.request(method, url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp.json()


def format_agent_message(result: Dict[str, object]) -> str:
    raw = result.get("agent_raw_response")
    if raw:
        return raw
    summary = result.get("agent_summary")
    if summary:
        return summary
    error = result.get("agent_error")
    if error:
        return f"(agent error) {error}"
    return "_(no response returned)_"


def append_chat(role: str, content: str):
    st.session_state.chat_history.append(
        {"role": role, "content": content, "ts": datetime.utcnow().isoformat()}
    )


init_state()

def ensure_scenario_loaded():
    if st.session_state.get("scenario_loaded"):
        return
    # try fetching scenario once; ignore errors.
    base_url = st.session_state.base_url.rstrip("/")
    scenario_url = f"{base_url}/scenario"
    try:
        st.session_state.last_scenario = request_json("GET", scenario_url)
        st.session_state.scenario_loaded = True
        cards = st.session_state.last_scenario
        if cards:
            intro_lines = [
                "### Prior Conversation Snapshot",
                "",
                f"**Ticket:** {cards['scenario_id']}",
            ]
            for key, value in cards.get("ticket_meta", {}).items():
                intro_lines.append(f"- **{key}**: {value}")
            intro_lines.append("")
            intro_lines.append("**Stored variables (masked):**")
            for key, value in cards.get("stored_variables", {}).items():
                intro_lines.append(f"- `{key}`: {value}")
            intro_lines.append("")
            intro_lines.append("**Prior dialog:**")
            for turn in cards.get("prior_dialog", []):
                intro_lines.append(f"- **{turn['speaker']}**: {turn['content']}")
            append_chat("assistant", "\n".join(intro_lines))
    except requests.RequestException:
        st.session_state.scenario_loaded = True  # avoid retry loops

ensure_scenario_loaded()

base_url = st.session_state.base_url.rstrip("/")
health_url = f"{base_url}/healthz"
scenario_url = f"{base_url}/scenario"
text_url = f"{base_url}/agent/text"
upload_url = f"{base_url}/agent/upload"

st.subheader("Scenario / Health Info")
info_cols = st.columns(3)
if info_cols[0].button("Refresh /healthz"):
    try:
        st.session_state.last_health = request_json("GET", health_url)
        st.success("Fetched /healthz")
    except requests.RequestException as exc:
        st.error(f"/healthz failed: {exc}")

if info_cols[1].button("Refresh /scenario"):
    try:
        st.session_state.last_scenario = request_json("GET", scenario_url)
        st.success("Fetched /scenario")
    except requests.RequestException as exc:
        st.error(f"/scenario failed: {exc}")

with st.expander("Latest /healthz response", expanded=False):
    st.json(st.session_state.last_health)
with st.expander("Latest /scenario response", expanded=False):
    st.json(st.session_state.last_scenario)

st.text_input("Participant ID", value=st.session_state.participant_id, disabled=True)
st.session_state.analyst_note = st.text_area(
    "Analyst note", value=st.session_state.analyst_note, height=80
)


# File upload -----------------------------------------------------------------
st.subheader("Upload a single Markdown file")
uploaded_file = st.file_uploader(
    "Choose a Markdown file (.md). It will be submitted to `/agent/upload`.",
    type=["md", "markdown", "txt"],
)
if uploaded_file and st.button("Send file to agent", use_container_width=True):
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "text/markdown",
        )
    }
    data = {"analyst_note": st.session_state.analyst_note}
    try:
        with st.spinner("Uploading file..."):
            result = request_json("POST", upload_url, files=files, data=data, timeout=60)
        append_chat("user", f"Uploaded `{uploaded_file.name}`.")
        append_chat("assistant", format_agent_message(result))
        st.success("Upload completed.")
    except requests.RequestException as exc:
        st.error(f"Upload failed: {exc}")

st.divider()

# Chat interface --------------------------------------------------------------
st.subheader("Conversational interface")
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("Send Markdown instructions or questions to the agent.")
if prompt:
    append_chat("user", prompt)
    payload = {
        "filename": f"{st.session_state.participant_id}_chat.md",
        "markdown": prompt,
        "analyst_note": st.session_state.analyst_note,
    }
    try:
        with st.spinner("Waiting for agent response..."):
            result = request_json("POST", text_url, json=payload, timeout=60)
        append_chat("assistant", format_agent_message(result))
        st.rerun()
    except requests.RequestException as exc:
        append_chat("assistant", f"Request failed: `{exc}`")
        st.rerun()


st.info(
    "Use chat for quick Markdown snippets (`/agent/text`) and the uploader for full files "
    "(`/agent/upload`). Each participant keeps their own chat history via the browser session."
)
