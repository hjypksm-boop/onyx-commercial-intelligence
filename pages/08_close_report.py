import json

import pandas as pd
import streamlit as st

from components import context as ctx
from components import ui
from services import ai, auth, exports, reports
from services import formatting as fmt

ui.page_header("Commercial Close Report", "End-of-day report compiled from stored records. Booked revenue and potential "
                                          "pipeline are always reported separately.")
eng = ctx.engine()
as_of = ctx.as_of_date()
d = st.date_input("Report date", value=as_of, max_value=as_of, format="DD/MM/YYYY", key="close_date")
ds = d.isoformat()

with st.spinner("Compiling today's records…"):
    r = reports.compute(eng, ds)
m, t = r["metrics"], r["tables"]
template = reports.default_commentary(r)
vers = reports.versions(eng, ds)

key = f"close_{ds}"
if st.session_state.get("close_key") != key:
    st.session_state["close_key"] = key
    st.session_state["close_comm"] = json.loads(vers.iloc[0]["commentary_json"]) if len(vers) else dict(template)
    st.session_state["close_label"] = (f"Saved version v{vers.iloc[0]['version']}" if len(vers)
                                       else "Template draft — generated from today's records")
    st.session_state["close_nonce"] = st.session_state.get("close_nonce", 0) + 1
comm = st.session_state["close_comm"]
nonce = st.session_state["close_nonce"]

# ------------------------------------------------------------------ headline metrics
c = st.columns(5)
with c[0]:
    ui.kpi_card("Customer meetings", str(m["meetings_completed"]), f"{m['accounts_contacted']} accounts contacted", "blue")
with c[1]:
    ui.kpi_card("Demonstrations", str(m["demonstrations_completed"]), "completed today", "blue")
with c[2]:
    ui.kpi_card("New ACV signed (booked)", ui.gbp(m["booked_acv_pence"]), "Closed Won today — booked revenue", "teal")
with c[3]:
    ui.kpi_card("New potential pipeline", ui.gbp(m["new_opportunities_potential_pence"]),
                f"{m['new_opportunities']} new opportunities · NOT booked", "amber")
with c[4]:
    ui.kpi_card("Revenue at risk", ui.gbp(m["revenue_at_risk_pence"]),
                f"{m['accounts_at_risk']} accounts · {m['escalations']} escalation(s)", "red")
with st.expander("Show SQL", icon=":material/code:"):
    for name, sql in reports.SQL.items():
        st.markdown(f"**{name}**")
        st.code(sql, language="sql")

# ------------------------------------------------------------------ commentary drafting
a, b = st.columns([3, 1])
a.markdown(f"<div class='ai-label'>{st.session_state['close_label']}</div>", unsafe_allow_html=True)
if b.button("Draft commentary with AI", icon=":material/psychology:", width="stretch"):
    with st.spinner("Drafting…"):
        new, res = ai.close_commentary(m, template)
    st.session_state["close_comm"] = comm = new
    st.session_state["close_label"] = res.label + (f" ({res.error})" if res.error and not res.used_ai else "")
    st.session_state["close_nonce"] = nonce = nonce + 1


def table(df: pd.DataFrame, cols: dict, empty: str) -> None:
    if df.empty:
        st.caption(empty)
        return
    out = df[list(cols)].rename(columns=cols).copy()
    for col in out.columns:
        if "£" in col:
            out[col] = (out[col] / 100).astype(int)
    st.dataframe(out, hide_index=True, width="stretch",
                 column_config={c: ui.money_col(c) for c in out.columns if "£" in c})


acts = t["activities"]
for k, label in reports.SECTIONS:
    st.subheader(label)
    if k == "performance":
        st.markdown(f"<div class='booked'><b>Booked revenue</b> — new annual contract value signed: "
                    f"<b>{ui.gbp(m['booked_acv_pence'])}</b></div>", unsafe_allow_html=True)
        table(t["booked"], {"customer_name": "Customer", "description": "Deal", "booked_acv_pence": "Booked ACV £",
                            "owner_name": "Owner"}, "No deals closed on this date.")
        st.caption(f"Meetings {m['meetings_completed']} · accounts contacted {m['accounts_contacted']} · demonstrations "
                   f"{m['demonstrations_completed']}")
    elif k == "developments":
        table(acts[acts["activity_type"].isin(["Meeting", "Call", "Email", "Demo"])],
              {"activity_type": "Type", "account_name": "Account", "account_type": "Kind", "subject": "Subject",
               "sentiment": "Sentiment", "owner_name": "Owner"}, "No customer activity recorded on this date.")
    elif k == "risks":
        table(t["at_risk"], {"customer_name": "Account", "arr_pence": "ARR £", "score": "Health", "renewal_date": "Renewal"},
              "No at-risk accounts.")
        esc = acts[acts["activity_type"] == "Escalation"]
        table(pd.concat([esc.rename(columns={"subject": "description"})[["account_name", "description"]],
                         t["cp_issues"][["account_name", "description"]]]),
              {"account_name": "Account", "description": "Escalation / issue"}, "No escalations logged.")
    elif k == "growth":
        st.markdown(f"<div class='pipeline'><b>Potential pipeline — not booked.</b> New today: "
                    f"{ui.gbp(m['new_opportunities_potential_pence'])} potential / "
                    f"{ui.gbp(m['new_opportunities_weighted_pence'])} weighted. Total open pipeline "
                    f"{ui.gbp(m['open_pipeline_potential_pence'])} / {ui.gbp(m['open_pipeline_weighted_pence'])} weighted."
                    f"</div>", unsafe_allow_html=True)
        table(t["new_opps"], {"customer_name": "Customer", "description": "Opportunity", "potential_arr_pence": "Potential £",
                              "expected_value_pence": "Expected value £", "stage": "Stage"},
              "No new opportunities identified on this date.")
        table(t["stage_moves"], {"customer_name": "Customer", "description": "Opportunity", "from_stage": "From",
                                 "to_stage": "To"}, "No pipeline stage changes on this date.")
    else:
        table(t["next_day"], {"priority": "Priority", "title": "Task", "account_name": "Account", "owner_name": "Owner",
                              "due_date": "Due", "reason": "Why"}, "Nothing scheduled for tomorrow.")
        st.caption(f"Outstanding tasks (due on or before this date, not done): {m['outstanding_tasks']}")
        table(t["renewals_30"], {"customer_name": "Renewing ≤30 days", "arr_pence": "ARR £", "renewal_date": "Renewal",
                                 "health_category": "Health"}, "No renewals in the next 30 days.")
    comm[k] = st.text_area(f"Commentary — {label}", comm.get(k, ""), key=f"cc_{k}_{nonce}", height=80)

# ------------------------------------------------------------------ save / approve / export
st.divider()
c1, c2, c3, c4 = st.columns(4)
if c1.button("Save version", type="primary", icon=":material/save:", width="stretch"):
    if ctx.run_safely(reports.save, eng, ctx.user_email(), ds, m, comm, success="Close report saved"):
        st.session_state.pop("close_key", None)
        st.rerun()
if auth.can_approve(ctx.user()) and len(vers) and vers.iloc[0]["status"] == "Draft":
    if c2.button(f"Approve v{vers.iloc[0]['version']}", icon=":material/verified:", width="stretch"):
        if ctx.run_safely(reports.approve, eng, ctx.user_email(), int(vers.iloc[0]["report_id"]), success="Report approved"):
            st.rerun()
elif not auth.can_approve(ctx.user()):
    c2.caption("Approval: Commercial Director")

secs = []
for k, label in reports.SECTIONS:
    s = exports.Section(label, comm.get(k, ""))
    if k == "performance":
        s.tone, s.table = "booked", pd.DataFrame({"Metric": ["Meetings", "Accounts contacted", "Demonstrations",
                                                             "New ACV signed (booked)"],
                                                  "Value": [m["meetings_completed"], m["accounts_contacted"],
                                                            m["demonstrations_completed"], fmt.gbp(m["booked_acv_pence"])]})
    elif k == "risks":
        s.table = pd.DataFrame({"Account": t["at_risk"]["customer_name"], "ARR": t["at_risk"]["arr_pence"].map(fmt.gbp),
                                "Health": t["at_risk"]["score"]})
    elif k == "growth":
        s.tone = "pipeline"
        s.table = pd.DataFrame({"Customer": t["new_opps"]["customer_name"], "Opportunity": t["new_opps"]["description"],
                                "Potential (not booked)": t["new_opps"]["potential_arr_pence"].map(fmt.gbp)})
    elif k == "priorities":
        s.table = pd.DataFrame({"Priority": t["next_day"]["priority"], "Task": t["next_day"]["title"],
                                "Owner": t["next_day"]["owner_name"]})
    secs.append(s)
title = f"Commercial Close Report — {fmt.fdate(ds)}"
c3.download_button("Export PDF", exports.build_pdf(title, f"Prepared by {ctx.user().get('display_name')} · "
                                                          f"{st.session_state['close_label']}", secs),
                   f"close_report_{ds}.pdf", "application/pdf", icon=":material/picture_as_pdf:", width="stretch")
c4.download_button("Export CSV", reports.to_csv(r), f"close_report_{ds}.csv", "text/csv", icon=":material/download:",
                   width="stretch")
if len(vers):
    st.caption("Saved versions: " + " · ".join(f"v{v.version} {v.status}" + (f" (approved by {v.approved_by})"
                                                                            if v.status == "Approved" else "")
                                               for v in vers.itertuples()))
