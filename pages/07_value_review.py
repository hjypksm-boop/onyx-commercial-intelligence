import json
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

from components import charts, ui
from components import context as ctx
from components.theme import BLUE, TEAL
from services import ai, exports, health, value_review
from services import formatting as fmt

ui.page_header("Value Review Builder", "Generate an editable customer business review from stored account data. "
                                       "Assumptions and missing information are marked explicitly.")
eng = ctx.engine()
cust = ctx.call("kpis.customers")
ids = cust["customer_id"].tolist()
names = dict(zip(cust["customer_id"], cust["customer_name"]))
default = st.session_state.get("vr_customer", st.session_state.get("customer_id"))
c1, c2, c3 = st.columns([2, 1.4, 2])
cid = c1.selectbox("Customer", ids, index=ids.index(default) if default in ids else 0, format_func=names.get,
                   key="vr_select")
period = c2.selectbox("Reporting period", ["Last quarter", "Last 6 months", "Last 12 months", "Custom range"],
                      index=1, key="vr_period")
as_of = ctx.as_of_date()
if period == "Custom range":
    rng = c3.date_input("Custom range", value=(as_of - timedelta(days=180), as_of), max_value=as_of, format="DD/MM/YYYY")
    start, end = (rng if isinstance(rng, (tuple, list)) and len(rng) == 2 else (as_of - timedelta(days=180), as_of))
else:
    days = {"Last quarter": 91, "Last 6 months": 182, "Last 12 months": 364}[period]
    start, end = as_of - timedelta(days=days), as_of
    c3.markdown(f"<div class='muted' style='margin-top:30px'>{fmt.fdate(start)} – {fmt.fdate(end)}</div>",
                unsafe_allow_html=True)
start_s, end_s = start.isoformat(), end.isoformat()
key = f"vr_{cid}_{start_s}_{end_s}"

if st.button("Generate review from account data", type="primary", icon=":material/auto_awesome:") or \
        st.session_state.get("vr_key") != key:
    with st.spinner("Compiling account data…"):
        f = value_review.facts(eng, cid, start_s, end_s)
        st.session_state["vr_key"] = key
        st.session_state["vr_facts"] = f
        st.session_state["vr_sections"] = value_review.default_sections(f)
        st.session_state["vr_summary_label"] = "Template draft — built only from stored data"
        st.session_state["vr_nonce"] = st.session_state.get("vr_nonce", 0) + 1

f = st.session_state["vr_facts"]
secs = st.session_state["vr_sections"]
nonce = st.session_state["vr_nonce"]
if f["missing"]:
    st.warning("Assumptions / missing information: " + " ".join(f["missing"]), icon=":material/help:")

# --------------------------------------------------- executive summary
st.subheader("Executive summary")
a, b = st.columns([3, 1])
with b:
    if st.button("Draft summary with AI", icon=":material/psychology:"):
        with st.spinner("Drafting…"):
            res = ai.value_review_summary(value_review.facts_for_ai(f), secs["summary"])
        secs["summary"] = res.text
        st.session_state["vr_summary_label"] = res.label + (f" ({res.error})" if res.error and not res.used_ai else "")
        st.session_state["vr_summary_facts"] = res.facts
        st.session_state["vr_nonce"] = nonce = nonce + 1
with a:
    st.markdown(f"<div class='ai-label'>{st.session_state['vr_summary_label']}</div>", unsafe_allow_html=True)
secs["summary"] = st.text_area("Executive summary", secs["summary"], height=140, key=f"vr_sum_{nonce}",
                               label_visibility="collapsed")
if st.session_state.get("vr_summary_facts"):
    with st.expander("Data used"):
        st.json(st.session_state["vr_summary_facts"], expanded=False)

# --------------------------------------------------- charts
usage = f["usage"]
mau_png = None
if not usage.empty:
    months = usage["month"].map(fmt.month_label).tolist()
    fig = go.Figure()
    fig.add_scatter(x=months, y=usage["mau"], name="Monthly active users", mode="lines+markers", line_color=TEAL)
    fig.add_bar(x=months, y=usage["sessions"], name="Sessions", marker_color=BLUE, opacity=.35, yaxis="y2")
    fig.add_hline(y=f["licensed_seats"], line_dash="dash", line_color="#64748B", annotation_text="Licensed seats")
    fig.update_layout(title="Usage and adoption in period", yaxis=dict(rangemode="tozero", title="MAU"),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Sessions"))
    charts.show(fig, "vr_usage", 280)
    mau_png = exports.line_chart_png(months, {"Monthly active users": usage["mau"].tolist(),
                                              "Licensed seats": [f["licensed_seats"]] * len(months)},
                                     "Monthly active users vs licensed seats", "Users")

# --------------------------------------------------- editable sections
st.subheader("Review sections")
for k, label in value_review.SECTIONS[1:]:
    secs[k] = st.text_area(label, secs[k], height=90 if len(secs[k]) < 300 else 140, key=f"vr_{k}_{nonce}")
hres = f["health_result"]
with st.expander("Customer health breakdown (included in exports)"):
    bd = health.breakdown(hres, ctx.call("health.get_weights"))
    st.dataframe(bd, hide_index=True, width="stretch")

# --------------------------------------------------- save / export
st.divider()
title = f"Customer Value Review — {f['customer']}"
subtitle = (f"Period {fmt.fdate(start_s)} – {fmt.fdate(end_s)} · prepared by {ctx.user().get('display_name')} · "
            f"generated from stored account data")
sections = [exports.Section(value_review.SECTIONS[0][1], secs["summary"], note=st.session_state["vr_summary_label"])]
for k, label in value_review.SECTIONS[1:]:
    s = exports.Section(label, secs[k])
    if k == "usage":
        s.chart_png = mau_png
    if k == "health":
        s.table = bd
    if k == "opportunities" and len(f["opportunities"]):
        s.tone = "pipeline"
    sections.append(s)
c1, c2, c3 = st.columns(3)
if c1.button("Save version", type="primary", icon=":material/save:", width="stretch"):
    if ctx.run_safely(value_review.save, eng, ctx.user_email(), cid, start_s, end_s, secs, success="Value review saved"):
        st.rerun()
c2.download_button("Export PDF", exports.build_pdf(title, subtitle, sections),
                   f"value_review_{f['customer'].replace(' ', '_')}.pdf", "application/pdf", icon=":material/picture_as_pdf:",
                   width="stretch")
html_doc = exports.build_html(title, subtitle, sections)
c3.download_button("Print-friendly HTML", html_doc.encode(), f"value_review_{f['customer'].replace(' ', '_')}.html",
                   "text/html", icon=":material/print:", width="stretch")
with st.expander("Print preview"):
    st.html(html_doc)

vers = value_review.versions(eng, cid)
st.subheader("Saved versions")
if vers.empty:
    st.caption("No saved versions for this customer yet.")
for v in vers.itertuples():
    cols = st.columns([4, 1])
    cols[0].markdown(f"**v{v.version}** · {fmt.fdate(v.period_start)} – {fmt.fdate(v.period_end)} · {v.created_by} · "
                     f"{v.created_at}")
    if cols[1].button("Load", key=f"load_vr_{v.review_id}"):
        st.session_state["vr_sections"] = json.loads(v.content_json)
        st.session_state["vr_nonce"] = nonce + 1
        st.rerun()
