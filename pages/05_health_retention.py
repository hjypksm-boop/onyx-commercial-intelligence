import html
from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from components import charts, dialogs, ui
from components import context as ctx
from components.theme import HEALTH_COLORS
from services import ai, auth, customers, db, retention, tasks, value_review
from services import formatting as fmt

ui.page_header("Customer Health & Retention", "Investigate at-risk accounts, separate hypotheses from confirmed causes, "
                                              "and run a guided recovery plan.")
can_edit = auth.can_edit(ctx.user())
eng = ctx.engine()

# ------------------------------------------------------------------ retention metrics
m = ctx.call("retention.retention_metrics")
fc = ctx.call("retention.renewal_forecast", 90)
c = st.columns([1, 1, 1, 2.2])
with c[0]:
    ui.kpi_card("Gross revenue retention", fmt.pct(m["grr"]), f"Cohort ARR 12 months ago {ui.gbp(m['start_arr_pence'])}",
                "teal", db.query_text("retention_cohort"))
with c[1]:
    ui.kpi_card("Net revenue retention", fmt.pct(m["nrr"]), f"Expansion {ui.gbp(m['expansion_pence'])} · downsell/churn "
                f"{ui.gbp(m['downsell_churn_pence'])}", "blue", db.query_text("retention_cohort"))
with c[2]:
    ui.kpi_card("ARR renewing ≤90 days", ui.gbp(fc["arr_pence"].sum() if len(fc) else 0),
                f"{int(fc['accounts'].sum()) if len(fc) else 0} account(s)", "amber", db.query_text("renewal_forecast"))
with c[3]:
    if fc.empty:
        st.caption("No renewals in the next 90 days.")
    else:
        fc["Month"] = fc["renewal_month"].map(fmt.month_label)
        fc["ARR"] = fc["arr_pence"] / 100
        fig = px.bar(fc, x="Month", y="ARR", color="health_category", color_discrete_map=HEALTH_COLORS,
                     title="90-day renewal forecast — ARR by renewal month × health", labels={"health_category": ""})
        fig.update_yaxes(tickprefix="£", tickformat=",.0f")
        charts.show(fig, "renew_fc", 230)

# ------------------------------------------------------------------ at-risk list
st.subheader("Accounts at risk")
include_monitor = st.toggle("Include Monitor accounts", value=True, key="ret_monitor")
cust = ctx.call("kpis.customers", ctx.fsub())
cats = ["At Risk", "Monitor"] if include_monitor else ["At Risk"]
risk = cust[cust["health_category"].isin(cats)].sort_values("priority_score", ascending=False)
if risk.empty:
    ui.empty_state("No accounts are currently At Risk" + (" or Monitor" if include_monitor else "") +
                   " for this selection. Health is recalculated after every change.")
    st.stop()

rows = []
for r in risk.itertuples():
    dec = customers.mau_decline(eng, r.customer_id)
    hi = db.query_one(eng, "SELECT * FROM v_health_inputs WHERE customer_id = :c", {"c": r.customer_id})
    plan = retention.get_plan(eng, r.customer_id)
    rec = "Investigate usage decline & champion change" if dec and dec["change"] <= -0.25 else "Review engagement gaps"
    if hi["open_high"]:
        rec += "; resolve high-severity tickets"
    rows.append({"Customer": r.customer_name, "Revenue at risk": int(r.arr_pence / 100), "Health": round(r.health_score),
                 "Usage change": round(dec["change"] * 100, 1) if dec else None,
                 "Renewal": f"{fmt.fdate(r.renewal_date)} ({r.days_to_renewal}d)",
                 "Open issues": int(hi["open_high"] + hi["open_medium"] + hi["open_low"]),
                 "Last contact": fmt.fdate(r.last_contact_date), "Recommended investigation": rec, "Owner": r.owner_name,
                 "Recovery status": plan["status"] if plan else "Not started"})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
             column_config={"Revenue at risk": ui.money_col("Revenue at risk"),
                            "Usage change": st.column_config.NumberColumn("Usage change (6m)", format="%+.1f%%"),
                            "Health": st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%d")})

# ------------------------------------------------------------------ workflow
ids = risk["customer_id"].tolist()
names = dict(zip(risk["customer_id"], risk["customer_name"]))
focus = st.session_state.get("focus_customer")
cid = st.selectbox("Recovery workspace for", ids, index=ids.index(focus) if focus in ids else 0,
                   format_func=names.get, key="ret_customer")
st.session_state["focus_customer"] = cid
row = risk[risk["customer_id"] == cid].iloc[0]
plan = retention.get_plan(eng, cid)
if not plan:
    st.info(f"No recovery plan yet for {names[cid]}.")
    if can_edit and st.button("Open recovery plan", type="primary", icon=":material/flag:"):
        if ctx.run_safely(retention.ensure_plan, eng, ctx.user_email(), cid, int(row["owner_id"]),
                          success="Recovery plan opened"):
            st.rerun()
    if not can_edit:
        ui.require_edit()
    st.stop()

cur = int(plan["current_step"])
ui.html_block("<div class='stepper'>" + "".join(
    f"<span class='s {'done' if n < cur else 'cur' if n == cur else ''}'>{n}. {t}</span>" for n, t in retention.STEPS)
    + "</div>")
st.markdown(f"Status: {ui.badge(plan['status'], 'AtRisk' if plan['status'] in ('Not started', 'Churned') else 'Monitor' if plan['status'] != 'Renewed' else 'Healthy')}"
            f" · started {fmt.fdate(plan['started_on'])} · owner {row['owner_name']}", unsafe_allow_html=True)
step = st.radio("Step", [n for n, _ in retention.STEPS], index=cur - 1, horizontal=True, key=f"ret_step_{cid}",
                format_func=lambda n: dict(retention.STEPS)[n])
STATUS_AFTER = {1: "Investigating", 2: "Investigating", 3: "Customer contacted", 4: "Plan agreed", 5: "Improving"}


def advance(n: int, status: str | None = None) -> None:
    if ctx.run_safely(retention.update_plan, eng, ctx.user_email(), cid, current_step=min(6, max(cur, n + 1)),
                      status=status or STATUS_AFTER.get(n), success=f"Step {n} complete"):
        st.rerun()


def step_notes(n: int) -> None:
    note = st.text_area("Step notes", value=plan["step_notes"].get(str(n), ""), key=f"note_{cid}_{n}", height=80,
                        disabled=not can_edit)
    if can_edit and note != plan["step_notes"].get(str(n), "") and st.button("Save notes", key=f"savenote_{cid}_{n}"):
        if ctx.run_safely(retention.update_plan, eng, ctx.user_email(), cid, note_step=n, note=note, success="Notes saved"):
            st.rerun()


with st.container(border=True):
    if step == 1:
        st.markdown("#### 1 · Investigate account data")
        ev = retention.evidence(eng, cid)
        dot = {"red": "🔴", "amber": "🟠", "teal": "🟢"}
        for e in ev:
            st.markdown(f"{dot[e['signal']]} **{e['area']}** — {html.escape(e['finding'])}", unsafe_allow_html=True)
        st.markdown("**Do not assume low usage means dissatisfaction — check alternative explanations:**")
        for t, how in retention.ALTERNATIVE_EXPLANATIONS:
            st.markdown(f"- **{t}:** {how}")
        step_notes(1)
        if can_edit and st.button("Investigation complete →", type="primary"):
            advance(1)
    elif step == 2:
        st.markdown("#### 2 · Identify potential root causes")
        hy = retention.list_hypotheses(eng, cid)
        meetings = ctx.q("SELECT activity_id, activity_date, activity_type, subject FROM activities WHERE customer_id = :c "
                         "AND activity_type IN ('Meeting', 'Call') ORDER BY activity_date DESC", {"c": cid})
        if hy.empty:
            st.caption("No causes logged yet.")
        for h in hy.itertuples():
            kind = {"Confirmed": "AtRisk", "Hypothesis": "Monitor", "Rejected": "Neutral"}[h.status]
            with st.container(border=True):
                st.markdown(f"{ui.badge(h.status.upper(), kind)} {ui.badge(h.source)} {ui.badge(h.category, 'Info')} "
                            f"**{html.escape(h.cause)}**", unsafe_allow_html=True)
                if fmt.txt(h.evidence):
                    st.caption(f"Evidence: {h.evidence}")
                if h.status == "Confirmed":
                    st.caption(f"Confirmed by {h.confirmed_by} — from conversation: {fmt.txt(h.confirmed_in)} "
                               f"({fmt.fdate(h.confirmed_on)})")
                if can_edit and h.status == "Hypothesis":
                    a, b = st.columns([3, 1])
                    with a.popover("Confirm with customer evidence"):
                        acts = meetings["activity_id"].tolist()
                        if not acts:
                            st.caption("Record a customer meeting or call first.")
                        else:
                            act = st.selectbox("Confirming conversation", acts, key=f"cact_{h.hypothesis_id}",
                                               format_func=lambda i: " · ".join(
                                                   str(x) for x in meetings[meetings.activity_id == i]
                                                   [["activity_date", "activity_type", "subject"]].iloc[0]))
                            evd = st.text_area("Evidence (what the customer said)", key=f"cev_{h.hypothesis_id}")
                            if st.button("Confirm cause", key=f"cbtn_{h.hypothesis_id}", type="primary"):
                                if ctx.run_safely(retention.confirm_hypothesis, eng, ctx.user_email(), h.hypothesis_id,
                                                  act, evd, success="Root cause confirmed"):
                                    st.rerun()
                    if b.button("Reject", key=f"rej_{h.hypothesis_id}"):
                        if ctx.run_safely(retention.set_hypothesis_status, eng, ctx.user_email(), h.hypothesis_id,
                                          "Rejected", success="Hypothesis rejected"):
                            st.rerun()
        if can_edit:
            with st.form("add_hyp", clear_on_submit=True):
                st.markdown("**Log a potential root cause** (saved as *Hypothesis*)")
                a, b = st.columns([2, 1])
                cause = a.text_input("Potential cause *")
                cat = b.selectbox("Category", retention.CAUSE_CATEGORIES)
                evd = st.text_input("Supporting evidence")
                if st.form_submit_button("Log hypothesis"):
                    if ctx.run_safely(retention.add_hypothesis, eng, ctx.user_email(), cid, cause, cat, evd,
                                      success="Hypothesis logged"):
                        st.rerun()
            if st.button("Suggest hypotheses (AI)", icon=":material/psychology:"):
                as_of = ctx.as_of()
                f = value_review.facts_for_ai(value_review.facts(eng, cid, f"{int(as_of[:4]) - 1}{as_of[4:]}", as_of))
                with st.spinner("Analysing evidence…"):
                    st.session_state[f"ai_hyp_{cid}"] = ai.root_cause_hypotheses(f, retention.evidence(eng, cid))
            sugg = st.session_state.get(f"ai_hyp_{cid}")
            if sugg:
                items, res = sugg
                st.markdown(f"<div class='ai-label'>{res.label} — nothing is saved until you click Save</div>",
                            unsafe_allow_html=True)
                for i, s in enumerate(items):
                    a, b = st.columns([5, 1])
                    a.markdown(f"**{html.escape(s['cause'])}** <span class='muted'>· {s['category']} · "
                               f"{html.escape(s['evidence'])}</span>", unsafe_allow_html=True)
                    if b.button("Save", key=f"save_sugg_{cid}_{i}"):
                        if ctx.run_safely(retention.add_hypothesis, eng, ctx.user_email(), cid, s["cause"], s["category"],
                                          s["evidence"], "AI" if res.used_ai else "System",
                                          success="Saved as Hypothesis"):
                            st.rerun()
                with st.expander("Data used"):
                    st.json(res.facts, expanded=False)
        step_notes(2)
        if can_edit and st.button("Root causes identified →", type="primary"):
            advance(2)
    elif step == 3:
        st.markdown("#### 3 · Contact customer")
        since = plan["started_on"] or ctx.as_of()
        recent = ctx.q("SELECT activity_date, activity_type, subject, sentiment FROM activities WHERE customer_id = :c "
                       "AND activity_date >= :s AND activity_type IN ('Meeting','Call','Email','Demo') "
                       "ORDER BY activity_date DESC", {"c": cid, "s": since})
        if recent.empty:
            st.warning(f"No customer contact recorded since the plan started ({fmt.fdate(since)}).")
        else:
            st.dataframe(recent, hide_index=True, width="stretch")
        if can_edit:
            contacts = ctx.q("SELECT name FROM contacts WHERE customer_id = :c AND status = 'Active'", {"c": cid})
            if st.button("Record customer conversation", icon=":material/groups:"):
                dialogs.meeting_dialog(customer_id=cid, contacts=contacts["name"].tolist())
            if st.button("Prepare talking points (meeting brief)", icon=":material/psychology:"):
                as_of = ctx.as_of()
                f = value_review.facts_for_ai(value_review.facts(eng, cid, f"{int(as_of[:4]) - 1}{as_of[4:]}", as_of))
                st.session_state[f"ret_brief_{cid}"] = ai.meeting_brief(f)
            if st.session_state.get(f"ret_brief_{cid}"):
                ui.ai_output(st.session_state[f"ret_brief_{cid}"], key=f"ret_brief_txt_{cid}", height=300)
        step_notes(3)
        if can_edit and st.button("Customer contacted →", type="primary", disabled=recent.empty):
            advance(3)
    elif step == 4:
        st.markdown("#### 4 · Agree recovery actions")
        pt = ctx.q("SELECT t.title, t.due_date, t.status, t.priority, ow.name AS owner FROM tasks t JOIN owners ow "
                   "ON ow.owner_id = t.owner_id WHERE t.customer_id = :c AND t.source = 'Recovery plan' "
                   "ORDER BY t.due_date", {"c": cid})
        if not pt.empty:
            st.dataframe(pt, hide_index=True, width="stretch")
        if can_edit:
            owners = ctx.call("kpis.owners")
            with st.form("recovery_actions", clear_on_submit=True):
                st.markdown("**Recovery actions** — each creates an owned, dated task")
                new = []
                for i in range(3):
                    a, b, d = st.columns([3, 1.4, 1.3])
                    t = a.text_input(f"Action {i + 1}", key=f"ra_t{i}")
                    o = b.selectbox("Owner", owners["owner_id"].tolist(), key=f"ra_o{i}",
                                    format_func=dict(zip(owners["owner_id"], owners["name"])).get)
                    due = d.date_input("Due", value=ctx.as_of_date() + timedelta(days=7 * (i + 1)), key=f"ra_d{i}",
                                       format="DD/MM/YYYY")
                    if t.strip():
                        new.append({"title": t, "customer_id": cid, "category": "Customer escalation", "priority": "High",
                                    "owner_id": o, "due_date": due, "status": "Open"})
                if st.form_submit_button("Create tasks", type="primary"):
                    if not new:
                        st.error("Enter at least one action.")
                    else:
                        ok = all(ctx.run_safely(tasks.create, eng, ctx.user_email(), t, "Recovery plan") for t in new)
                        if ok:
                            st.rerun()
        step_notes(4)
        if can_edit and st.button("Plan agreed with customer →", type="primary", disabled=pt.empty):
            advance(4)
    elif step == 5:
        st.markdown("#### 5 · Track improvements")
        pr = retention.progress(eng, cid)
        if not pr:
            st.caption("Plan not started yet.")
        else:
            a, b, d = st.columns(3)
            a.metric("Active users", pr["current_mau"], delta=int(pr["current_mau"] - (pr["baseline_mau"] or 0)),
                     help=f"Baseline at plan start ({fmt.fdate(pr['started_on'])}): {pr['baseline_mau']}")
            b.metric("Health score", f"{float(pr['current_score']):.0f}",
                     delta=round(float(pr["current_score"]) - float(pr["baseline_score"] or 0), 1),
                     help=f"Baseline: {pr['baseline_score']}")
            d.metric("Contacts / tasks done since start", f"{pr['contacts_since']} / {pr['tasks_done_since']}")
            if can_edit:
                with st.popover("Update active users"):
                    lic = int(row["licensed_seats"])
                    act = st.number_input("Active users", 0, lic, int(row["active_users"]))
                    if st.button("Save", key="upd_act"):
                        if ctx.run_safely(customers.update_account, eng, ctx.user_email(), cid, licensed_seats=lic,
                                          active_users=act, owner_id=int(row["owner_id"]), success="Active users updated"):
                            st.rerun()
        step_notes(5)
        if can_edit and st.button("Mark improving →", type="primary"):
            advance(5)
    else:
        st.markdown("#### 6 · Review renewal outcome")
        if plan["outcome"]:
            st.success(f"Outcome recorded: **{plan['outcome']}**" + (f" — {plan['outcome_reason']}"
                                                                     if plan["outcome_reason"] else ""))
        if can_edit:
            with st.form("outcome"):
                out = st.radio("Renewal outcome", retention.OUTCOMES, horizontal=True)
                reason = st.text_area("Reason / notes (required for churn)")
                if st.form_submit_button("Record outcome", type="primary"):
                    status = "Churned" if out == "Churned" else "Renewed"
                    if ctx.run_safely(retention.update_plan, eng, ctx.user_email(), cid, outcome=out,
                                      outcome_reason=reason, status=status, current_step=6, success="Outcome recorded"):
                        st.rerun()
        st.caption("Recording the outcome closes the recovery plan. Contract changes (renewal terms) are managed outside "
                   "this demo — see Known limitations.")
