import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components import charts, dialogs, ui
from components import context as ctx
from components.theme import AMBER, BLUE, RED, TEAL
from services import ai, auth, customers, health, retention, value_review
from services import formatting as fmt
from services import tasks as task_svc

cust_df = ctx.call("kpis.customers")
cp_df = ctx.call("kpis.counterparties")
options = [f"c:{i}" for i in cust_df["customer_id"]] + [f"p:{i}" for i in cp_df["counterparty_id"]]
labels = {**{f"c:{r.customer_id}": f"{r.customer_name} · {r.vertical}" for r in cust_df.itertuples()},
          **{f"p:{r.counterparty_id}": f"{r.counterparty_name} · Trading relationship" for r in cp_df.itertuples()}}
if st.session_state.get("c360_select") not in options:
    cid0 = st.session_state.get("customer_id")
    st.session_state["c360_select"] = f"c:{cid0}" if f"c:{cid0}" in options else options[0]
choice = st.selectbox("Account", options, format_func=lambda o: labels[o], key="c360_select")
kind, sid = choice.split(":")
sid = int(sid)
can_edit = auth.can_edit(ctx.user())


# =============================================================================================== counterparty layout
def counterparty_view(cp_id: int) -> None:
    st.session_state["counterparty_id"] = cp_id
    r = cp_df[cp_df["counterparty_id"] == cp_id].iloc[0]
    ui.page_header(r["counterparty_name"], f"Trading relationship · {r['region']} · {r['primary_products']}")
    kind_badge = {"Approved": "Healthy", "Pending KYC": "Monitor", "Under Review": "Monitor", "Suspended": "AtRisk"}
    ui.html_block(ui.badge(f"Relationship: {r['relationship_status']}", "Info") + " " +
                  ui.badge(f"Approval: {r['approval_status']}", kind_badge[r["approval_status"]]) + " " +
                  ui.badge("No subscription · excluded from ARR, adoption and health", "Neutral"))
    st.write("")
    c = st.columns(4)
    with c[0]:
        ui.kpi_card("Trades (12 months)", fmt.num(r["trades_12m"]), "executed trades", "blue")
    with c[1]:
        ui.kpi_card("Trading notional (12m)", fmt.usd(r["notional_usd_12m"]), "Trading notional — not revenue", "amber")
    with c[2]:
        ui.kpi_card("Open issues", str(r["open_issues"]), "execution / service / operational", "red" if r["open_issues"] else "teal")
    with c[3]:
        ui.kpi_card("Relationship owner", r["owner_name"], f"Last contact {fmt.fdate(r['last_contact_date'])}", "teal")

    if can_edit:
        a = st.columns(5)
        if a[0].button("Create follow-up task", icon=":material/add_task:"):
            dialogs.task_dialog(counterparty_id=cp_id, default_category="Customer escalation")
        if a[1].button("Add note", icon=":material/note_add:"):
            dialogs.note_dialog(counterparty_id=cp_id)
        if a[2].button("Record interaction", icon=":material/groups:"):
            contacts = ctx.q("SELECT name FROM contacts WHERE counterparty_id = :c", {"c": cp_id})["name"].tolist()
            dialogs.meeting_dialog(counterparty_id=cp_id, contacts=contacts)
    tabs = st.tabs(["Trading activity", "Issues & follow-ups", "Status", "Timeline & notes", "Audit"])
    with tabs[0]:
        ta = ctx.q("SELECT month, trade_count, notional_usd FROM trading_activity WHERE counterparty_id = :c ORDER BY month",
                   {"c": cp_id})
        if ta.empty or ta["trade_count"].sum() == 0:
            ui.empty_state("No trading activity recorded — counterparty approval may still be pending.")
        else:
            ta["Month"] = ta["month"].map(fmt.month_label)
            fig = go.Figure()
            fig.add_bar(x=ta["Month"], y=ta["notional_usd"], name="Trading notional (USD) — not revenue",
                        marker_color=AMBER, opacity=.55, yaxis="y2")
            fig.add_scatter(x=ta["Month"], y=ta["trade_count"], name="Trades", mode="lines+markers", line_color=BLUE)
            fig.update_layout(title="Monthly trading activity", yaxis=dict(title="Trades"),
                              yaxis2=dict(title="Notional USD (not revenue)", overlaying="y", side="right",
                                          showgrid=False, tickprefix="$", tickformat=".2s"))
            charts.show(fig, "cp_trades")
    with tabs[1]:
        iss = ctx.q("""SELECT i.issue_id, i.issue_type, i.description, i.severity, i.status, i.opened_date, i.resolved_date,
                       ow.name AS owner FROM counterparty_issues i LEFT JOIN owners ow ON ow.owner_id = i.owner_id
                       WHERE i.counterparty_id = :c ORDER BY i.status, i.opened_date DESC""", {"c": cp_id})
        if iss.empty:
            st.caption("No execution or service issues recorded.")
        for i in iss.itertuples():
            cols = st.columns([5, 1.3])
            cols[0].markdown(f"{ui.badge(i.severity, {'Low': 'Neutral', 'Medium': 'Monitor'}.get(i.severity, 'AtRisk'))} "
                             f"**{i.issue_type}** — {html.escape(i.description)}  <span class='muted'>· opened "
                             f"{fmt.fdate(i.opened_date)} · {i.status}{' · resolved ' + fmt.fdate(i.resolved_date) if fmt.txt(i.resolved_date) else ''}"
                             f" · {i.owner}</span>", unsafe_allow_html=True)
            if can_edit and i.status != "Resolved" and cols[1].button("Resolve", key=f"res_{i.issue_id}"):
                if ctx.run_safely(customers.resolve_counterparty_issue, ctx.engine(), ctx.user_email(), i.issue_id,
                                  success="Issue resolved"):
                    st.rerun()
        if can_edit:
            with st.form("cp_issue"):
                st.markdown("**Log execution / service issue**")
                c1, c2 = st.columns(2)
                typ = c1.selectbox("Type", ["Execution", "Settlement", "Confirmation", "Service", "Credit"])
                sev = c2.selectbox("Severity", ["Low", "Medium", "High", "Critical"], index=1)
                desc = st.text_input("Description *")
                if st.form_submit_button("Log issue"):
                    if ctx.run_safely(customers.add_counterparty_issue, ctx.engine(), ctx.user_email(), cp_id,
                                      issue_type=typ, description=desc, severity=sev, owner_id=int(r["owner_id"]),
                                      success="Issue logged"):
                        st.rerun()
        st.markdown("**Operational follow-ups**")
        _task_list(ctx.q("SELECT * FROM tasks WHERE counterparty_id = :c ORDER BY status = 'Done', due_date", {"c": cp_id}))
    with tabs[2]:
        if can_edit:
            with st.form("cp_status"):
                rel_opts = ["Active", "Developing", "Dormant", "On hold"]
                ap_opts = ["Approved", "Pending KYC", "Under Review", "Suspended"]
                rs = st.selectbox("Relationship status", rel_opts, index=rel_opts.index(r["relationship_status"]))
                ap = st.selectbox("Counterparty approval status", ap_opts, index=ap_opts.index(r["approval_status"]))
                owners = ctx.call("kpis.owners")
                oid = st.selectbox("Relationship owner", owners["owner_id"].tolist(),
                                   index=owners["owner_id"].tolist().index(int(r["owner_id"])),
                                   format_func=dict(zip(owners["owner_id"], owners["name"])).get)
                if st.form_submit_button("Save status", type="primary"):
                    if ctx.run_safely(customers.update_counterparty, ctx.engine(), ctx.user_email(), cp_id,
                                      relationship_status=rs, approval_status=ap, owner_id=oid, success="Status saved"):
                        st.rerun()
        else:
            st.write(f"Relationship: **{r['relationship_status']}** · Approval: **{r['approval_status']}**")
    with tabs[3]:
        _timeline(ctx.q("""SELECT activity_id, activity_date, activity_type, subject, summary, attendees, sentiment
                           FROM activities WHERE counterparty_id = :c ORDER BY activity_date DESC, activity_id DESC""",
                        {"c": cp_id}))
        _notes(ctx.q("SELECT note_date, author, body FROM account_notes WHERE counterparty_id = :c ORDER BY note_date DESC",
                     {"c": cp_id}))
    with tabs[4]:
        _audit(ctx.q("SELECT ts, user_email, action, entity, summary, changes_json FROM audit_log WHERE counterparty_id = :c "
                     "ORDER BY audit_id DESC", {"c": cp_id}))


# =============================================================================================== shared renderers
def _task_list(t: pd.DataFrame, prefix: str = "t") -> None:
    if t.empty:
        st.caption("No tasks.")
        return
    as_of = ctx.as_of()
    for row in t.itertuples():
        b = task_svc.bucket(row.due_date, row.status, as_of)
        kind = {"Overdue": "AtRisk", "Due today": "Monitor", "Upcoming": "Info", "Done": "Healthy"}[b]
        cols = st.columns([5, 1.2])
        cols[0].markdown(f"{ui.badge(b, kind)} {ui.badge(row.priority)} **{html.escape(row.title)}** "
                         f"<span class='muted'>· due {fmt.fdate(row.due_date)} · {row.status}</span>",
                         unsafe_allow_html=True)
        if can_edit and row.status != "Done" and cols[1].button("Complete", key=f"{prefix}_done_{row.task_id}"):
            if ctx.run_safely(task_svc.complete, ctx.engine(), ctx.user_email(), [int(row.task_id)],
                              success="Task completed"):
                st.rerun()


def _timeline(acts: pd.DataFrame, customer: dict | None = None) -> None:
    if acts.empty:
        st.caption("No meetings or correspondence recorded.")
        return
    icons = {"Meeting": "🤝", "Call": "📞", "Email": "✉️", "Demo": "🖥️", "Escalation": "⚠️", "Note": "📝"}
    for a in acts.head(25).itertuples():
        sent = f" · sentiment {int(a.sentiment)}/5" if pd.notna(a.sentiment) else ""
        st.markdown(f"<div class='timeline-item'><div class='t'>{fmt.fdate(a.activity_date)} · {a.activity_type}{sent}</div>"
                    f"{icons.get(a.activity_type, '•')} <b>{html.escape(a.subject)}</b><br>"
                    f"<span class='muted'>{html.escape(fmt.txt(a.summary))}"
                    f"{' · Attendees: ' + html.escape(fmt.txt(a.attendees)) if fmt.txt(a.attendees) else ''}</span></div>",
                    unsafe_allow_html=True)
        if customer and a.activity_type == "Meeting" and can_edit:
            with st.popover("Draft follow-up email", icon=":material/mail:"):
                first = (fmt.txt(a.attendees) or "there").split(",")[0].split()[0]
                res = ai.followup_email({"customer": customer["customer_name"], "subject": a.subject,
                                         "date": fmt.fdate(a.activity_date), "summary": fmt.txt(a.summary),
                                         "next_steps": fmt.txt(getattr(a, "next_steps", None)), "first_name": first,
                                         "sender": ctx.user().get("display_name")}) \
                    if st.button("Generate draft", key=f"em_{a.activity_id}") else None
                if res:
                    st.session_state[f"email_{a.activity_id}"] = res
                if st.session_state.get(f"email_{a.activity_id}"):
                    ui.ai_output(st.session_state[f"email_{a.activity_id}"], key=f"email_txt_{a.activity_id}", height=220)
                    st.caption("Drafts are not sent or saved — copy into your email client.")


def _notes(n: pd.DataFrame) -> None:
    st.markdown("**Account notes**")
    if n.empty:
        st.caption("No notes.")
    for r in n.itertuples():
        st.markdown(f"<div class='timeline-item'><div class='t'>{fmt.fdate(r.note_date)} · {html.escape(r.author)}</div>"
                    f"{html.escape(r.body)}</div>", unsafe_allow_html=True)


def _audit(a: pd.DataFrame) -> None:
    if a.empty:
        st.caption("No changes recorded for this account yet.")
        return
    st.dataframe(a.rename(columns={"ts": "When", "user_email": "Who", "action": "Action", "entity": "Entity",
                                   "summary": "What", "changes_json": "Old → new"}), hide_index=True, width="stretch")


# =============================================================================================== subscription layout
def customer_view(cid: int) -> None:
    st.session_state["customer_id"] = cid
    p = customers.profile(ctx.engine(), cid)
    hres = next(r for r in ctx.call("health.compute") if r.customer_id == cid)
    weights = ctx.call("health.get_weights")
    ui.page_header(p["customer_name"], f"{p['vertical']} · {p['segment']} · {p['hq_region']} · Owner: {p['owner_name']}"
                                       f" · Customer since {fmt.fdate(p['customer_since'])}")
    ui.html_block(ui.health_badge(hres.category, hres.score, hres.available) + " " +
                  ui.badge(f"Contract {p['contract_status']}", "Info") + " " +
                  ui.badge(f"Renews {fmt.fdate(p['renewal_date'])} · {p['days_to_renewal']} days",
                           "AtRisk" if p["days_to_renewal"] <= 30 else "Monitor" if p["days_to_renewal"] <= 60 else "Neutral"))
    st.caption(hres.reason)

    dec = customers.mau_decline(ctx.engine(), cid)
    if dec and dec["change"] <= -0.25:
        st.markdown(f"<div class='warn'>⚠ Active users declined {abs(dec['change']) * 100:.0f}% from "
                    f"{fmt.month_name(dec['from_month'])} to {fmt.month_name(dec['to_month'])} "
                    f"({dec['from_mau']} → {dec['to_mau']}).</div>", unsafe_allow_html=True)

    c = st.columns(5)
    with c[0]:
        ui.kpi_card("Annual contract value", ui.gbp(p["arr_pence"]), f"{p['billing_frequency']} billing", "teal")
    with c[1]:
        ui.kpi_card("Seats", f"{p['active_users']} / {p['licensed_seats']}", f"{p['adoption_pct']:.1f}% active",
                    "teal" if p["adoption_pct"] >= 70 else "amber" if p["adoption_pct"] >= 50 else "red")
    with c[2]:
        ui.kpi_card("Renewal", f"{p['days_to_renewal']} days", fmt.fdate(p["renewal_date"]),
                    "red" if p["days_to_renewal"] <= 30 else "amber" if p["days_to_renewal"] <= 60 else "blue")
    with c[3]:
        ui.kpi_card("Time to first value", f"{p['ttfv_days']} days" if p["ttfv_days"] is not None else "—",
                    f"Onboarding {p['milestones_done']}/{p['milestones_total']} milestones", "blue")
    with c[4]:
        ui.kpi_card("Potential expansion", ui.gbp(p["potential_expansion_pence"]),
                    f"Weighted {ui.gbp(p['weighted_expansion_pence'])}", "amber")

    contacts = ctx.q("SELECT name, title, email, is_champion, is_decision_maker, status, left_date FROM contacts "
                     "WHERE customer_id = :c ORDER BY status, is_champion DESC", {"c": cid})
    # ---------------------------------------------------------------- action panel
    st.markdown("##### Customer actions")
    if can_edit:
        a = st.columns(7)
        if a[0].button("Follow-up task", icon=":material/add_task:", width="stretch"):
            dialogs.task_dialog(customer_id=cid)
        if a[1].button("Account note", icon=":material/note_add:", width="stretch"):
            dialogs.note_dialog(customer_id=cid)
        if a[2].button("Record meeting", icon=":material/groups:", width="stretch"):
            dialogs.meeting_dialog(customer_id=cid, contacts=contacts[contacts.status == "Active"]["name"].tolist())
        if a[3].button("Escalation", icon=":material/priority_high:", width="stretch"):
            dialogs.escalation_dialog(cid)
        if a[4].button("Opportunity", icon=":material/trending_up:", width="stretch"):
            dialogs.opportunity_dialog(customer_id=cid)
        if a[5].button("Value review", icon=":material/summarize:", width="stretch"):
            st.session_state["vr_customer"] = cid
            ctx.goto("value_review")
        if a[6].button("Edit account", icon=":material/edit:", width="stretch"):
            dialogs.account_dialog(cid, p["licensed_seats"], p["active_users"], p["owner_id"])
    else:
        ui.require_edit()
        if st.button("Generate value review", icon=":material/summarize:"):
            st.session_state["vr_customer"] = cid
            ctx.goto("value_review")

    with st.expander("Prepare customer conversation — meeting brief", icon=":material/psychology:"):
        st.caption("Builds a brief from this account's stored facts only. Nothing is saved.")
        if st.button("Generate meeting brief", key="brief_btn"):
            as_of = ctx.as_of()
            f = value_review.facts(ctx.engine(), cid, f"{int(as_of[:4]) - 1}{as_of[4:]}", as_of)
            with st.spinner("Drafting…"):
                st.session_state[f"brief_{cid}"] = ai.meeting_brief(value_review.facts_for_ai(f))
        if st.session_state.get(f"brief_{cid}"):
            ui.ai_output(st.session_state[f"brief_{cid}"], key=f"brief_txt_{cid}", height=320)

    tabs = st.tabs(["Overview", "Usage", "Adoption & onboarding", "Support", "Timeline", "Health score",
                    "Risks & opportunities", "Tasks", "Audit trail"])
    # ---------------------------------------------------------------- overview
    with tabs[0]:
        lc, rc = st.columns([1.3, 1])
        with lc:
            st.markdown("**Contacts**")
            st.dataframe(pd.DataFrame({
                "Name": contacts["name"], "Title": contacts["title"], "Email": contacts["email"],
                "Role": contacts.apply(lambda x: ", ".join(k for k, v in [("Champion", x.is_champion),
                                                                          ("Decision maker", x.is_decision_maker)] if v),
                                       axis=1),
                "Status": contacts.apply(lambda x: x.status + (f" ({fmt.fdate(x.left_date)})" if fmt.txt(x.left_date) else ""),
                                         axis=1)}), hide_index=True, width="stretch")
            _notes(ctx.q("SELECT note_date, author, body FROM account_notes WHERE customer_id = :c ORDER BY note_date DESC",
                         {"c": cid}))
        with rc:
            st.markdown("**Subscription & contract**")
            st.markdown(f"- Product: **{p['vertical']}**\n- Modules: {p['modules']}\n- Term: {p['term_months']} months from "
                        f"{fmt.fdate(p['start_date'])}\n- Renewal: **{fmt.fdate(p['renewal_date'])}** "
                        f"({p['days_to_renewal']} days)\n- Contract status: {p['contract_status']} · "
                        f"{p['billing_frequency']} billing\n- Annual contract value: **{ui.gbp(p['arr_pence'])}**")
            hist = ctx.q("SELECT start_date, renewal_date, arr_pence, status FROM contracts WHERE customer_id = :c "
                         "ORDER BY start_date", {"c": cid})
            st.dataframe(pd.DataFrame({"Start": hist["start_date"].map(fmt.fdate), "End": hist["renewal_date"].map(fmt.fdate),
                                       "ACV": (hist["arr_pence"] / 100).astype(int), "Status": hist["status"]}),
                         hide_index=True, width="stretch", column_config={"ACV": ui.money_col("ACV")})
        if p["product_id"] == "FB":
            ports = ctx.q("""SELECT pt.name AS port, pt.country, pt.latitude, pt.longitude, cp.subscribed,
                             COALESCE(SUM(pa.price_lookups), 0) AS lookups_12m, COALESCE(SUM(pa.stems_reported), 0) AS stems_12m
                             FROM customer_ports cp JOIN ports pt ON pt.port_id = cp.port_id
                             LEFT JOIN port_activity pa ON pa.customer_id = cp.customer_id AND pa.port_id = cp.port_id
                             WHERE cp.customer_id = :c GROUP BY pt.name, pt.country, pt.latitude, pt.longitude, cp.subscribed
                             ORDER BY lookups_12m DESC""", {"c": cid})
            st.markdown("**Port coverage**")
            pc1, pc2 = st.columns([1, 1.3])
            pc1.dataframe(pd.DataFrame({"Port": ports["port"], "Coverage": ports["subscribed"].map({1: "Subscribed",
                                                                                                   0: "Not covered"}),
                                        "Price lookups (12m)": ports["lookups_12m"], "Stems reported (12m)": ports["stems_12m"]}),
                          hide_index=True, width="stretch")
            ports["activity"] = ports["lookups_12m"] + ports["stems_12m"]
            ports["Coverage"] = ports["subscribed"].map({1: "Subscribed", 0: "Not covered (activity seen)"})
            fig = px.scatter_geo(ports, lat=ports["latitude"].astype(float), lon=ports["longitude"].astype(float),
                                 size=ports["activity"].clip(lower=5), color="Coverage", hover_name="port",
                                 color_discrete_map={"Subscribed": TEAL, "Not covered (activity seen)": AMBER},
                                 projection="natural earth", title="Port coverage & activity")
            fig.update_geos(bgcolor="rgba(0,0,0,0)", landcolor="#1E293B", showocean=True, oceancolor="#0B1220",
                            showcountries=False, coastlinecolor="#334155")
            with pc2:
                charts.show(fig, "c360_ports", 300)
    # ---------------------------------------------------------------- usage
    with tabs[1]:
        mu = customers.monthly_usage(ctx.engine(), cid)
        if mu.empty:
            ui.empty_state("No usage records for this account.")
        else:
            months = mu["month"].tolist()
            rng = st.select_slider("Date range", options=months, value=(months[max(0, len(months) - 12)], months[-1]),
                                   format_func=fmt.month_label, key=f"usage_rng_{cid}")
            mu = mu[(mu["month"] >= rng[0]) & (mu["month"] <= rng[1])].copy()
            metric = {"FB": ("pricing_queries", "Pricing-tool queries"), "FA": ("analytics_runs", "Analytics runs"),
                      "OFF": ("reports_downloaded", "Reports downloaded")}[p["product_id"]]
            mu["Month"] = mu["month"].map(fmt.month_label)
            fig = go.Figure()
            fig.add_bar(x=mu["Month"], y=mu[metric[0]], name=metric[1], marker_color=BLUE, opacity=.45, yaxis="y2")
            fig.add_scatter(x=mu["Month"], y=mu["sessions"], name="Sessions", mode="lines", line=dict(color=AMBER, dash="dot"),
                            yaxis="y2")
            fig.add_scatter(x=mu["Month"], y=mu["mau"], name="Monthly active users", mode="lines+markers+text",
                            text=mu["mau"], textposition="top center", line=dict(color=RED if dec and dec["change"] <= -0.25
                                                                                   else TEAL, width=3))
            fig.add_hline(y=p["licensed_seats"], line_dash="dash", line_color="#64748B",
                          annotation_text=f"Licensed seats ({p['licensed_seats']})", annotation_position="top left")
            fig.update_layout(title="Monthly usage", yaxis=dict(title="Monthly active users", rangemode="tozero"),
                              yaxis2=dict(title="Volume", overlaying="y", side="right", showgrid=False, rangemode="tozero"))
            charts.show(fig, f"usage_{cid}", 360)
            ui.show_sql("SELECT month, mau, sessions, logins, pricing_queries, analytics_runs, reports_downloaded, api_calls\n"
                        "FROM v_monthly_usage WHERE customer_id = :customer_id ORDER BY month\n\n"
                        "-- v_monthly_usage: COUNT(DISTINCT user_key) per month from usage_daily (logins > 0)")
            st.caption(f"Seat utilisation: {p['active_users']} of {p['licensed_seats']} licensed seats active "
                       f"({p['adoption_pct']:.1f}%). API calls in range: {int(mu['api_calls'].sum()):,}.")
    # ---------------------------------------------------------------- adoption / onboarding
    with tabs[2]:
        feats = ctx.q("SELECT feature, adopted, usage_count_90d, first_used_date FROM v_feature_adoption WHERE customer_id = :c "
                      "ORDER BY usage_count_90d DESC", {"c": cid})
        lc, rc = st.columns([1.2, 1])
        with lc:
            st.markdown(f"**Feature adoption** — {int(feats['adopted'].sum())} of {len(feats)} features adopted")
            st.dataframe(pd.DataFrame({"Feature": feats["feature"],
                                       "Status": feats["adopted"].map({1: "Adopted", 0: "Not adopted"}),
                                       "Usage (90 days)": feats["usage_count_90d"],
                                       "First used": feats["first_used_date"].map(fmt.fdate)}),
                         hide_index=True, width="stretch")
        with rc:
            ms = ctx.q("SELECT seq, milestone, target_date, completed_date FROM onboarding_milestones WHERE customer_id = :c "
                       "ORDER BY seq", {"c": cid})
            done = ms["completed_date"].notna().sum()
            st.markdown(f"**Onboarding progress** — {done}/{len(ms)} milestones")
            st.progress(done / len(ms) if len(ms) else 0)
            for m in ms.itertuples():
                ok = pd.notna(m.completed_date)
                st.markdown(f"{'✅' if ok else '⬜'} {m.milestone} <span class='muted'>· target {fmt.fdate(m.target_date)}"
                            f"{' · done ' + fmt.fdate(m.completed_date) if ok else ' · outstanding'}</span>",
                            unsafe_allow_html=True)
    # ---------------------------------------------------------------- support
    with tabs[3]:
        tk = ctx.q("SELECT ticket_id, subject, severity, status, opened_date, closed_date, sla_hours, sla_breached, escalated "
                   "FROM support_tickets WHERE customer_id = :c ORDER BY closed_date IS NOT NULL, opened_date DESC", {"c": cid})
        if tk.empty:
            st.caption("No support tickets.")
        for t in tk.itertuples():
            cols = st.columns([5, 1.6])
            flags = (" " + ui.badge("SLA breached", "AtRisk") if t.sla_breached else "") + \
                    (" " + ui.badge("Escalated", "Monitor") if t.escalated else "")
            cols[0].markdown(f"{ui.badge(t.severity, {'Low': 'Neutral', 'Medium': 'Monitor'}.get(t.severity, 'AtRisk'))}"
                             f"{flags} **#{t.ticket_id} {html.escape(t.subject)}** <span class='muted'>· {t.status} · opened "
                             f"{fmt.fdate(t.opened_date)}{' · closed ' + fmt.fdate(t.closed_date) if fmt.txt(t.closed_date) else ''}"
                             f" · SLA {t.sla_hours}h</span>", unsafe_allow_html=True)
            if can_edit and t.status not in ("Resolved", "Closed"):
                new = cols[1].selectbox("Status", ["Open", "In progress", "Resolved"], key=f"tk_{t.ticket_id}",
                                        index=["Open", "In progress", "Resolved"].index(t.status), label_visibility="collapsed")
                if new != t.status and ctx.run_safely(customers.update_ticket_status, ctx.engine(), ctx.user_email(),
                                                      int(t.ticket_id), new, success="Ticket updated"):
                    st.rerun()
        inc = ctx.q("SELECT incident_date, dataset, duration_hours, impact, resolved_date FROM data_incidents "
                    "WHERE customer_id = :c ORDER BY incident_date DESC", {"c": cid})
        if p["product_id"] == "FA":
            st.markdown("**Data availability incidents**")
            if inc.empty:
                st.caption("None recorded.")
            else:
                st.dataframe(pd.DataFrame({"Date": inc["incident_date"].map(fmt.fdate), "Dataset": inc["dataset"],
                                           "Duration (h)": inc["duration_hours"].astype(float), "Impact": inc["impact"],
                                           "Resolved": inc["resolved_date"].map(fmt.fdate)}), hide_index=True, width="stretch")
    # ---------------------------------------------------------------- timeline
    with tabs[4]:
        _timeline(ctx.q("""SELECT activity_id, activity_date, activity_type, subject, summary, attendees, sentiment, next_steps
                           FROM activities WHERE customer_id = :c ORDER BY activity_date DESC, activity_id DESC""",
                        {"c": cid}), customer=p)
    # ---------------------------------------------------------------- health
    with tabs[5]:
        st.markdown(ui.health_badge(hres.category, hres.score, hres.available), unsafe_allow_html=True)
        st.write(hres.reason)
        st.dataframe(health.breakdown(hres, weights), hide_index=True, width="stretch")
        snaps = ctx.q("SELECT snapshot_date, score, category FROM health_snapshots WHERE customer_id = :c ORDER BY snapshot_date",
                      {"c": cid})
        if len(snaps) > 1:
            fig = go.Figure(go.Scatter(x=pd.to_datetime(snaps["snapshot_date"]), y=snaps["score"].astype(float),
                                       mode="lines+markers", line_color=TEAL))
            fig.add_hrect(y0=80, y1=100, fillcolor=TEAL, opacity=.06, line_width=0)
            fig.add_hrect(y0=60, y1=80, fillcolor=AMBER, opacity=.06, line_width=0)
            fig.add_hrect(y0=0, y1=60, fillcolor=RED, opacity=.06, line_width=0)
            fig.update_layout(title="Health score history (month-end snapshots)", yaxis=dict(range=[0, 100]))
            charts.show(fig, f"hh_{cid}", 260)
        with st.expander("Component definitions"):
            for k, label in health.COMPONENTS:
                st.markdown(f"- **{label}** ({weights[k]}%): {health.DEFINITIONS[k]}")
    # ---------------------------------------------------------------- risks & opps
    with tabs[6]:
        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Identified risks**")
            hy = retention.list_hypotheses(ctx.engine(), cid)
            if hy.empty:
                st.caption("No risks logged. Use the Health & Retention workspace to investigate.")
            for h in hy.itertuples():
                kind = {"Confirmed": "AtRisk", "Hypothesis": "Monitor", "Rejected": "Neutral"}[h.status]
                st.markdown(f"{ui.badge(h.status, kind)} {ui.badge(h.source)} **{html.escape(h.cause)}** "
                            f"<span class='muted'>· {h.category}"
                            f"{' · confirmed by ' + fmt.txt(h.confirmed_by) + ' in ' + html.escape(fmt.txt(h.confirmed_in)) if h.status == 'Confirmed' else ''}"
                            f"</span>", unsafe_allow_html=True)
            if hres.category in ("At Risk", "Monitor") and st.button("Open retention workspace", key="to_ret"):
                st.session_state["focus_customer"] = cid
                ctx.goto("retention")
        with rc:
            st.markdown("**Expansion opportunities**")
            op = ctx.q("SELECT * FROM v_pipeline WHERE customer_id = :c ORDER BY is_open DESC, expected_value_pence DESC",
                       {"c": cid})
            if op.empty:
                st.caption("No opportunities recorded.")
            for o in op.itertuples():
                st.markdown(f"{ui.badge(o.stage, 'Healthy' if o.stage == 'Closed Won' else 'Neutral' if not o.is_open else 'Info')}"
                            f" **{html.escape(o.description)}** <span class='muted'>· {ui.gbp(o.potential_arr_pence)} × "
                            f"{float(o.probability) * 100:.0f}% = {ui.gbp(o.expected_value_pence)} · close "
                            f"{fmt.fdate(o.expected_close_date)}</span>", unsafe_allow_html=True)
            if st.button("Open pipeline", key="to_growth"):
                st.session_state["focus_customer"] = cid
                ctx.goto("growth")
    # ---------------------------------------------------------------- tasks
    with tabs[7]:
        _task_list(ctx.q("SELECT * FROM tasks WHERE customer_id = :c ORDER BY status = 'Done', due_date", {"c": cid}))
    with tabs[8]:
        _audit(ctx.q("SELECT ts, user_email, action, entity, summary, changes_json FROM audit_log WHERE customer_id = :c "
                     "ORDER BY audit_id DESC", {"c": cid}))


if kind == "c":
    customer_view(sid)
else:
    counterparty_view(sid)
