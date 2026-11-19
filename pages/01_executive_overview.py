import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components import charts, ui
from components import context as ctx
from components.theme import VERTICAL_COLORS
from services import ai, db, sqlguard
from services import formatting as fmt
from services.priority import EXPLANATION as PRIORITY_EXPLANATION

ui.page_header("Executive Overview", f"Subscription portfolio as of {fmt.fdate(ctx.as_of())} · trading counterparties "
                                     "are reported separately and never counted as revenue")

fs = ctx.fsub()
k = ctx.call("kpis.portfolio_kpis", fs)
cust = ctx.call("kpis.customers", fs)
health_res = {r.customer_id: r for r in ctx.call("health.compute")}
pipe = ctx.call("opportunities.pipeline")

if cust.empty:
    ui.empty_state("No subscription accounts match the current filters. Clear filters in the sidebar to see the portfolio.")
    st.stop()

# ------------------------------------------------------------------ three questions
st.subheader("The three commercial questions")
a, b, c = st.columns(3)


def _usage_phrase(cid):
    r = health_res.get(cid)
    comp = r.components["usage_trend"] if r else {}
    return comp.get("phrase", "usage trend not measurable")


with a, st.container(border=True):
    st.markdown("<div class='answer-tile'><div class='q' style='color:#14B8A6'>Who is getting value?</div></div>",
                unsafe_allow_html=True)
    val = cust[cust["health_category"] == "Healthy"].sort_values("health_score", ascending=False)
    if val.empty:
        st.caption("No healthy accounts in the current selection.")
    for r in val.itertuples():
        hr = health_res.get(r.customer_id)
        sent = hr.components["sentiment"].get("phrase", "no sentiment recorded") if hr else ""
        if st.button(f"{r.customer_name} →", key=f"v_{r.customer_id}", type="tertiary"):
            ctx.goto("c360", customer_id=r.customer_id)
        st.caption(f"{r.adoption_pct:.0f}% seat adoption · {_usage_phrase(r.customer_id)} · {sent}")

with b, st.container(border=True):
    st.markdown("<div class='answer-tile'><div class='q' style='color:#EF4444'>Who is at risk?</div></div>",
                unsafe_allow_html=True)
    risk = cust[cust["health_category"].isin(["At Risk", "Monitor"])].sort_values("priority_score", ascending=False)
    if risk.empty:
        st.caption("No at-risk or monitored accounts in the current selection.")
    for r in risk.itertuples():
        hr = health_res.get(r.customer_id)
        sup = hr.components["support"]["phrase"] if hr else ""
        if st.button(f"{r.customer_name} →", key=f"r_{r.customer_id}", type="tertiary"):
            ctx.goto("c360", customer_id=r.customer_id)
        st.caption(f"{r.health_category} {r.health_score:.0f} · {_usage_phrase(r.customer_id)} · renewal in "
                   f"{r.days_to_renewal} days ({ui.gbp(r.arr_pence)}) · {sup}")

with c, st.container(border=True):
    st.markdown("<div class='answer-tile'><div class='q' style='color:#F59E0B'>Where can we grow?</div></div>",
                unsafe_allow_html=True)
    grow = pipe[(pipe["is_open"] == 1) & pipe["customer_id"].isin(cust["customer_id"])].sort_values(
        "expected_value_pence", ascending=False)
    if grow.empty:
        st.caption("No open opportunities for the current selection.")
    for r in grow.itertuples():
        if st.button(f"{r.customer_name} — {r.description} →", key=f"g_{r.opportunity_id}", type="tertiary"):
            st.session_state["focus_customer"] = int(r.customer_id)
            ctx.goto("growth")
        st.caption(f"Expected value {ui.gbp(r.expected_value_pence)} ({ui.gbp(r.potential_arr_pence)} × "
                   f"{float(r.probability) * 100:.0f}%) · {r.stage}")

# ------------------------------------------------------------------ KPI cards
st.write("")
kpi_sql = db.query_text("portfolio_kpis")
c1, c2, c3, c4 = st.columns(4)
with c1:
    ui.kpi_card("Annual Recurring Revenue", ui.gbp(k["arr_pence"]), f"{k['accounts']} subscription accounts", "teal",
                kpi_sql, "arr_pence = SUM(arr_pence) over the filtered accounts.")
with c2:
    ui.kpi_card("Product Adoption", fmt.pct(k["adoption_pct"]),
                f"{k['active_users']} active of {k['licensed_seats']} licensed seats", "blue", kpi_sql,
                "adoption_pct = 100 × SUM(active_users) ÷ SUM(licensed_seats).")
with c3:
    ui.kpi_card("Revenue at Risk", ui.gbp(k["revenue_at_risk_pence"]),
                f"{k['at_risk_accounts']} account(s) with calculated health < 60", "red", kpi_sql,
                "revenue_at_risk_pence = ARR of accounts whose latest calculated health category is At Risk.")
with c4:
    ui.kpi_card("Potential Expansion Revenue", ui.gbp(k["potential_expansion_pence"]),
                f"Open, uncommitted · weighted {ui.gbp(k['weighted_pipeline_pence'])}", "amber", kpi_sql,
                "potential_expansion_pence = unweighted potential of open opportunities (not Closed Won/Lost).")

# ------------------------------------------------------------------ charts row 1
st.write("")
left, right = st.columns([1.3, 1])
with left:
    sql = f"""SELECT vertical, SUM(arr_pence) AS arr_pence, COUNT(*) AS accounts
FROM v_customer_kpis
WHERE {ctx.FILTER_SQL}
GROUP BY vertical ORDER BY arr_pence DESC"""
    rv = ctx.q(sql, ctx.filter_params())
    fig = go.Figure(go.Bar(x=rv["vertical"], y=rv["arr_pence"] / 100,
                           marker_color=[VERTICAL_COLORS.get(v) for v in rv["vertical"]],
                           text=[fmt.gbp_compact(v) for v in rv["arr_pence"]], textposition="outside",
                           customdata=rv["accounts"],
                           hovertemplate="%{x}<br>ARR £%{y:,.0f}<br>%{customdata} account(s)<extra></extra>"))
    fig.update_layout(title="Revenue by product vertical", yaxis_title="ARR (£)", yaxis_tickprefix="£",
                      yaxis_tickformat=",.0f")
    charts.show(fig, "rev_vertical")
    ui.show_sql(sql)
with right:
    hsql = f"""SELECT health_category, COUNT(*) AS accounts, SUM(arr_pence) AS arr_pence
FROM v_customer_kpis
WHERE {ctx.FILTER_SQL}
GROUP BY health_category"""
    hd = ctx.q(hsql, ctx.filter_params())
    charts.show(charts.health_bar(dict(zip(hd["health_category"], hd["accounts"]))), "health_dist")
    ui.show_sql(hsql)

# ------------------------------------------------------------------ adoption trend
start, end = ctx.date_range()
tr = ctx.call("kpis.adoption_trend", start[:7], end[:7], fs)
if tr.empty:
    ui.empty_state("No usage data in the selected date range.")
else:
    tr["Month"] = tr["month"].map(fmt.month_label)
    fig = px.line(tr, x="Month", y="adoption_pct", color="vertical", markers=True, color_discrete_map=VERTICAL_COLORS,
                  labels={"adoption_pct": "Monthly active ÷ licensed (%)", "vertical": ""},
                  title="Adoption trend — monthly active users ÷ licensed seats")
    fig.update_traces(hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>")
    fig.update_yaxes(ticksuffix="%", range=[0, 105])
    charts.show(fig, "adoption_trend")
    ui.show_sql(db.query_text("adoption_trend"))

# ------------------------------------------------------------------ attention + renewals
left, right = st.columns([1.25, 1])
with left:
    st.subheader("Accounts requiring immediate attention")
    st.caption(PRIORITY_EXPLANATION)
    att = cust.sort_values("priority_score", ascending=False).head(6)
    for r in att.itertuples():
        hr = health_res.get(r.customer_id)
        cols = st.columns([0.9, 2.6, 1.3])
        cols[0].markdown(f"<div class='kpi' style='min-height:0;padding:6px 8px;text-align:center'><div class='label'>"
                         f"Priority</div><div class='value' style='font-size:1.2rem'>{r.priority_score:.0f}</div></div>",
                         unsafe_allow_html=True)
        with cols[1]:
            if st.button(f"{r.customer_name} →", key=f"att_{r.customer_id}", type="tertiary"):
                ctx.goto("c360", customer_id=r.customer_id)
            st.caption(hr.reason if hr else "")
        cols[2].markdown(ui.health_badge(r.health_category, r.health_score, r.components_available) +
                         f"<div class='muted'>{ui.gbp(r.arr_pence)} · renews in {r.days_to_renewal}d</div>",
                         unsafe_allow_html=True)
with right:
    st.subheader("Upcoming renewals")
    window = st.segmented_control("Window", [30, 60, 90, 180], default=90, format_func=lambda d: f"≤{d} days",
                                  key="renew_window", label_visibility="collapsed") or 90
    ren = cust[cust["days_to_renewal"] <= window].sort_values("days_to_renewal")
    if ren.empty:
        st.caption(f"No renewals in the next {window} days for this selection.")
    else:
        st.dataframe(pd.DataFrame({
            "Customer": ren["customer_name"], "Renewal": ren["renewal_date"].map(fmt.fdate),
            "Days": ren["days_to_renewal"], "ARR": (ren["arr_pence"] / 100).astype(int),
            "Health": ren["health_category"] + " (" + ren["health_score"].round(0).astype(int).astype(str) + ")"}),
            hide_index=True, width="stretch", column_config={"ARR": ui.money_col("ARR")})
        st.markdown(f"<span class='muted'>ARR renewing ≤{window} days: <b>{ui.gbp(ren['arr_pence'].sum())}</b> · at risk "
                    f"{ui.gbp(ren[ren.health_category == 'At Risk']['arr_pence'].sum())}</span>", unsafe_allow_html=True)

    st.subheader("Top growth opportunities")
    if grow.empty:
        st.caption("No open opportunities.")
    else:
        st.dataframe(pd.DataFrame({
            "Customer": grow["customer_name"], "Opportunity": grow["description"],
            "Potential": (grow["potential_arr_pence"] / 100).astype(int),
            "Prob.": (grow["probability"].astype(float) * 100), "Expected": (grow["expected_value_pence"] / 100).astype(int),
            "Stage": grow["stage"]}), hide_index=True, width="stretch",
            column_config={"Potential": ui.money_col("Potential"), "Expected": ui.money_col("Expected value"),
                           "Prob.": st.column_config.NumberColumn("Prob.", format="%d%%")})

# ------------------------------------------------------------------ activity feed
st.subheader("Recent customer activity")
feed = ctx.call("kpis.activity_feed", start, end)
names = set(cust["customer_name"])
feed = feed[feed["account_name"].isin(names) | feed["counterparty_id"].notna()]
if feed.empty:
    ui.empty_state("No activity recorded in the selected date range.")
else:
    st.dataframe(pd.DataFrame({
        "Date": feed["activity_date"].map(fmt.fdate), "Type": feed["activity_type"], "Account": feed["account_name"],
        "Subject": feed["subject"], "Sentiment": feed["sentiment"], "Owner": feed["owner_name"]}).head(15),
        hide_index=True, width="stretch",
        column_config={"Sentiment": st.column_config.NumberColumn("Sentiment", format="%d / 5")})

# ------------------------------------------------------------------ ask the portfolio
st.subheader("Ask the portfolio")
st.caption("Natural-language question → read-only SELECT over a documented set of views. The SQL is validated "
           "(single SELECT, allow-listed views, 500-row limit) and executed on a read-only connection.")
mode_ai = ai.available()
c1, c2 = st.columns([2, 1])
with c1:
    question = st.text_input("Question", placeholder="e.g. Which accounts renew in the next 90 days and what is their health?",
                             key="ask_q", disabled=not mode_ai,
                             help=None if mode_ai else "AI unavailable — choose an example question instead.")
with c2:
    example = st.selectbox("…or an example (no AI needed)", ["—"] + list(sqlguard.EXAMPLES), key="ask_ex")
if not mode_ai:
    st.caption("AI unavailable — add GROQ_API_KEY to .env to ask free-text questions. Examples use pre-written SQL.")
if st.button("Run", type="primary", key="ask_run"):
    if example != "—" and not question:
        st.session_state["ask_sql"] = sqlguard.EXAMPLES[example]
        st.session_state["ask_label"] = "Example query"
    elif question:
        with st.spinner("Generating SQL…"):
            res = ai.nl_to_sql(question, sqlguard.SCHEMA_DOC)
        if not res.used_ai or not res.text:
            st.error(f"AI unavailable — {res.error or 'no SQL returned'}.")
        st.session_state["ask_sql"] = res.text if res.used_ai else ""
        st.session_state["ask_label"] = "AI-generated SQL — review before relying on results"
    else:
        st.warning("Type a question or pick an example.")
sql = st.session_state.get("ask_sql")
if sql:
    st.markdown(f"<div class='ai-label'>{st.session_state.get('ask_label', '')}</div>", unsafe_allow_html=True)
    st.code(sql, language="sql")
    ok, cleaned, err = sqlguard.validate(sql)
    if not ok:
        st.error(f"Rejected: {err}")
    else:
        try:
            out = sqlguard.run_readonly(ctx.engine(), cleaned)
            st.dataframe(out, hide_index=True, width="stretch")
            num = out.select_dtypes("number").columns.tolist()
            txt = [c for c in out.columns if c not in num]
            if len(out) > 1 and num and txt:
                fig = px.bar(out, x=txt[0], y=num[-1], title=f"{num[-1]} by {txt[0]}")
                charts.show(fig, "ask_chart", 280)
        except Exception as e:
            st.error(f"Query failed: {e}")

