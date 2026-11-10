"""POSANTRA | VERIQ - optional password gate and simple scan rate limit.

Active only if VERIQ_PASSWORD is set (Streamlit secrets or environment).
Per-session limits can be bypassed by opening a new session; real abuse
protection needs a proxy in front of the app.
"""
from __future__ import annotations

import hmac
import os
import time

import streamlit as st

MAX_FAILS = 5
LOCK_SECONDS = 60


def _password() -> str:
    try:
        value = st.secrets.get("VERIQ_PASSWORD", "")
    except Exception:
        value = ""
    return str(value or os.environ.get("VERIQ_PASSWORD", ""))


def require_access() -> None:
    expected = _password()
    if not expected or st.session_state.get("veriq_ok"):
        return
    now = time.time()
    locked = st.session_state.get("veriq_lock", 0.0)
    st.markdown("### 🔒 POSANTRA | VERIQ")
    if now < locked:
        st.error(f"Too many wrong attempts. Try again in {int(locked - now) + 1} seconds.")
        st.stop()
    with st.form("veriq_gate"):
        typed = st.text_input("Access password", type="password", max_chars=100)
        go = st.form_submit_button("Enter")
    if go:
        if hmac.compare_digest(typed.encode(), expected.encode()):
            st.session_state["veriq_ok"] = True
            st.session_state["veriq_fails"] = 0
            st.rerun()
        fails = st.session_state.get("veriq_fails", 0) + 1
        st.session_state["veriq_fails"] = fails
        if fails >= MAX_FAILS:
            st.session_state["veriq_lock"] = now + LOCK_SECONDS
            st.session_state["veriq_fails"] = 0
        st.error("Wrong password.")
    st.stop()


def allow_scan(limit: int = 15, window: int = 600) -> bool:
    now = time.time()
    stamps = [t for t in st.session_state.get("veriq_scans", []) if now - t < window]
    if len(stamps) >= limit:
        st.session_state["veriq_scans"] = stamps
        return False
    stamps.append(now)
    st.session_state["veriq_scans"] = stamps
    return True