"""POSANTRA | VERIQ - report and saved-records UI (Step 12)."""
from __future__ import annotations

import sqlite3
from typing import Callable

import streamlit as st

from database import database as local_db
from modules import report_generator as rg


def render_report_panel(build_data: Callable[[str], dict], report_key: str) -> None:
    st.markdown("#### Investigation Report")
    st.caption(
        "Generates a VERIQ Investigation Report from the results above, as an HTML file. "
        "Open it in a browser and choose Print, then Save as PDF. The uploaded image itself "
        "is not included. If you change the evidence, generate the report again."
    )
    ids = st.session_state.setdefault("veriq_report_ids", {})
    report_id = ids.setdefault(report_key, rg.new_investigation_id())

    if st.button("Generate report from the current results", key=f"gen_{report_key}"):
        try:
            data = build_data(report_id)
            st.session_state["veriq_report"] = {
                "key": report_key, "data": data, "html": rg.render_html(data), "saved": False,
            }
        except Exception as exc:
            st.error(f"The report could not be generated ({type(exc).__name__}).")

    current = st.session_state.get("veriq_report")
    if not current or current["key"] != report_key:
        st.caption("No report has been generated for this investigation yet.")
        return

    data = current["data"]
    head, strength = rg.headline(data)
    st.success(f"Report {data['investigation_id']} generated at {data['generated_utc']} (UTC).")
    st.write(f"Assessment: {head}")
    st.write(f"Evidence strength: {strength}")

    st.download_button(
        "Download report (HTML)",
        data=current["html"].encode("utf-8"),
        file_name=f"{data['investigation_id']}.html",
        mime="text/html",
        key=f"dl_{report_key}",
    )

    st.caption(
        "Saving stores this report's data in a local SQLite file on this machine: metadata "
        "(including GPS, if present), extracted or provided text, claims, evidence, "
        "assessments and limitations. The image itself is never stored."
    )
    if st.button("Save investigation record locally", key=f"save_{report_key}"):
        try:
            local_db.save_investigation(data)
            current["saved"] = True
        except (sqlite3.Error, ValueError, TypeError) as exc:
            st.error(f"The record could not be saved ({type(exc).__name__}).")
    if current.get("saved"):
        st.caption(f"Record {data['investigation_id']} is saved locally.")


def render_saved_records() -> None:
    with st.expander("Saved investigation records"):
        try:
            rows = local_db.list_investigations()
        except sqlite3.Error:
            st.caption("The saved records could not be read.")
            return
        if not rows:
            st.caption("No investigation records are saved.")
            return
        st.dataframe(rows, hide_index=True, use_container_width=True)
        choice = st.selectbox("Record", [r["id"] for r in rows], key="veriq_saved_choice")
        record = local_db.get_investigation(choice)
        if record:
            st.download_button(
                "Download this record as a report (HTML)",
                data=rg.render_html(record).encode("utf-8"),
                file_name=f"{choice}.html", mime="text/html", key="veriq_saved_dl",
            )
        else:
            st.caption("That record could not be read.")
        if st.button("Delete all saved investigation records", key="veriq_saved_clear"):
            try:
                removed = local_db.clear_investigations()
            except sqlite3.Error:
                st.error("The records could not be deleted.")
                return
            st.success(f"Deleted {removed} record(s).")
            st.rerun()