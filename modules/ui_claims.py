"""POSANTRA | VERIQ - claim and evidence panel (Step 11).

Streamlit UI for the Claim / Evidence / Context / Assessment flow. Text from
the web or from images is rendered as plain text, never as HTML.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

import config
from modules import claim_analyzer as ca
from modules import source_research as sr
from modules import verdict_engine as ve

_COLOURS = {
    ve.AUTHENTIC: "#2ea36b", ve.MANIPULATED: "#e5534b", ve.CONTRADICTED: "#e5534b",
    ve.MISLEADING_CONTEXT: "#d29922", ve.UNVERIFIED: "#d29922",
    ve.INSUFFICIENT_EVIDENCE: "#8b949e",
}
_AUTO_TIER = "Classify from the web domain"
_TIER_OPTIONS = {_AUTO_TIER: None, **{f"{n}. {label}": n for n, label in sr.TIERS.items() if n}}


def render_claim_investigation(sources: list[tuple[str, str]], key_prefix: str,
                               published: str = "", has_media: bool = False,
                               user_provided: bool = False,
                               heading: str = "Claim Analysis") -> None:
    combined = "\n".join(text for _, text in sources if text)
    if not combined.strip():
        st.info("No text is available to analyse for claims.")
        return

    tag = hashlib.sha256(combined.encode("utf-8", errors="ignore")).hexdigest()[:12]
    base = f"{key_prefix}_{tag}"
    evidence: list = st.session_state.setdefault(f"veriq_ev_{base}", [])
    claims = ca.extract_claims(sources)

    _render_claims(claims, heading)
    claim_id = _render_search(base, claims, combined, evidence)
    _render_manual_form(base, claim_id, evidence)
    _render_evidence_table(base, evidence)
    _render_timeline(published, claims, evidence)
    _render_assessment(claims, evidence, user_provided)


def _render_claims(claims, heading: str) -> None:
    st.markdown(f"#### {heading}")
    st.caption("Candidate claims are proposed by simple pattern rules. They are not "
               "judgements of truth, and place names are a rough guess.")
    if not claims:
        st.write("No checkable statements were identified in the text.")
    else:
        st.table([{
            "ID": c.id, "Claim": c.text, "Looks like": ", ".join(c.kinds),
            "Dates in text": ", ".join(c.dates) or "-",
            "Places (guess)": ", ".join(c.places) or "-",
        } for c in claims])
        with st.expander("Questions requiring verification"):
            for c in claims:
                st.markdown(f"**{c.id}**")
                for q in c.questions:
                    st.text("- " + q)
            st.markdown("**General**")
            for q in ca.GENERAL_QUESTIONS:
                st.text("- " + q)
    st.markdown("**Context**")
    st.caption("Context means information needed to read the claim correctly, such as "
               "when and where media was first published. Record it as evidence below "
               "using the type 'Earlier publication of the media' or 'Background / context'.")


def _render_search(base: str, claims, combined: str, evidence: list) -> str:
    st.markdown("#### Evidence Search")
    st.caption("Free public sources only: Wikipedia and the GDELT news index. Clicking "
               "Search sends only the query text shown below to en.wikipedia.org and "
               "api.gdeltproject.org. Results are not judged by VERIQ.")
    labels = {"general": "General / whole text"}
    labels.update({c.id: f"{c.id}: {c.text[:80]}" for c in claims})
    choice = st.selectbox("Claim to research", list(labels), format_func=labels.get,
                          key=f"claim_{base}")
    seed = next((c.text for c in claims if c.id == choice), combined)
    query = st.text_input("Search query (edit as needed)", value=sr.default_query(seed),
                          key=f"q_{base}_{choice}", max_chars=sr.MAX_QUERY_CHARS)

    state_key = f"veriq_sr_{base}"
    if st.button("Search public sources", key=f"search_{base}"):
        with st.spinner("Searching..."):
            results, errors = sr.search_all(query)
        previous = st.session_state.get(state_key, {})
        st.session_state[state_key] = {"results": results, "errors": errors,
                                       "claim": choice, "nonce": previous.get("nonce", 0) + 1}

    state = st.session_state.get(state_key)
    if not state:
        return choice
    for error in state["errors"]:
        st.warning(error)
    results = state["results"]
    if not results:
        st.write("No results were returned. This says nothing about whether other sources exist.")
        return choice

    st.markdown("**Results.** Tick a row, choose a stance and type, and explain why it matters.")
    df = pd.DataFrame([{
        "Include": False, "Stance": sr.NOT_ASSESSED, "Evidence type": sr.TYPE_BACKGROUND,
        "Explanation (why it matters)": "", "Source": r.title, "Domain": r.domain,
        "Source tier": r.tier_label, "Date": r.published, "Provider": r.provider, "URL": r.url,
    } for r in results])
    edited = st.data_editor(
        df, key=f"editor_{base}_{state['nonce']}", hide_index=True, use_container_width=True,
        disabled=["Source", "Domain", "Source tier", "Date", "Provider", "URL"],
        column_config={
            "Include": st.column_config.CheckboxColumn(),
            "Stance": st.column_config.SelectboxColumn(options=list(sr.STANCES), required=True),
            "Evidence type": st.column_config.SelectboxColumn(options=list(sr.EVIDENCE_TYPES), required=True),
            "URL": st.column_config.LinkColumn(),
        })
    st.caption("GDELT dates show when GDELT first saw an article. Links open external "
               "sites that VERIQ has not checked.")

    if st.button("Add ticked rows to the evidence list", key=f"add_{base}"):
        problems, added = [], 0
        for i, row in edited.iterrows():
            if not bool(row["Include"]):
                continue
            item, error = sr.evidence_from_result(
                results[i], row["Stance"], row["Evidence type"],
                row["Explanation (why it matters)"], state["claim"])
            if error:
                problems.append(error)
            elif sr.add_unique(evidence, item):
                added += 1
        for p in problems:
            st.error(p)
        if added:
            st.success(f"Added {added} source(s).")
    return choice


def _render_manual_form(base: str, claim_id: str, evidence: list) -> None:
    with st.expander("Add a source manually"):
        with st.form(f"manual_ev_{base}"):
            title = st.text_input("Source title", max_chars=200)
            url = st.text_input("Source URL", max_chars=2048)
            published = st.text_input("Publication date (as shown on the source)", max_chars=100)
            etype = st.selectbox("Evidence type", list(sr.EVIDENCE_TYPES))
            stance = st.selectbox("Stance", list(sr.STANCES), index=len(sr.STANCES) - 1)
            tier_label = st.selectbox("Source tier", list(_TIER_OPTIONS))
            explanation = st.text_area("Why does this source matter?", max_chars=1000)
            submitted = st.form_submit_button("Add source")
        st.caption("The URL is stored as text and is not fetched by VERIQ.")
        if submitted:
            item, error = sr.make_manual_evidence(
                title, url, published, etype, stance, explanation, claim_id,
                _TIER_OPTIONS[tier_label])
            if error:
                st.error(error)
            elif sr.add_unique(evidence, item):
                st.success("Source added.")
            else:
                st.info("That source is already in the list for this claim.")


def _render_evidence_table(base: str, evidence: list) -> None:
    st.markdown("#### Evidence")
    if not evidence:
        st.write("No sources have been recorded yet.")
        return
    st.dataframe(pd.DataFrame([{
        "Stance": e.stance, "Source": e.source_title, "Domain": e.domain,
        "Source tier": e.tier_label, "Type": e.evidence_type, "Published": e.published,
        "Retrieved": e.retrieved, "Claim": e.relevance, "Why it matters": e.explanation,
        "Added by": e.added_by, "URL": e.url,
    } for e in evidence]), hide_index=True, use_container_width=True,
        column_config={"URL": st.column_config.LinkColumn()})
    if st.button("Clear all recorded evidence", key=f"clear_{base}"):
        evidence.clear()
        st.rerun()


def _render_timeline(published: str, claims, evidence: list) -> None:
    st.markdown("#### Timeline")
    rows = ca.build_timeline(published, claims, evidence)
    if rows:
        st.table(rows)
        st.caption("Dates are as reported and not independently verified. Entries whose "
                   "format VERIQ cannot parse are listed after dated ones.")
    else:
        st.write("No dates are available yet.")


def _render_assessment(claims, evidence: list, user_provided: bool) -> None:
    st.markdown("#### Claim Assessment")
    verdict = ve.evaluate_claims(claims, evidence, user_provided)
    colour = _COLOURS.get(verdict.assessment, "#8b949e")
    st.markdown(
        f'<div class="verdict-box" style="border-left-color:{colour}">'
        f'<div class="verdict-label">ASSESSMENT</div>'
        f'<div class="verdict-value" style="color:{colour}">{verdict.assessment}</div></div>',
        unsafe_allow_html=True)
    st.markdown(f"**Evidence strength:** {verdict.strength}")
    st.markdown("**Reason**")
    st.write(verdict.reason)
    if verdict.findings:
        st.table([{"Area": f.area, "Finding": f.text, "Weight": f.weight}
                  for f in verdict.findings])
    with st.expander("Limitations of this assessment"):
        for text in verdict.limitations:
            st.markdown(f"- {text}")
    with st.expander("Suggested manual checks"):
        for text in verdict.suggested_checks:
            st.markdown(f"- {text}")