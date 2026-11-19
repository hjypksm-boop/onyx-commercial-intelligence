import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components import charts, ui
from components import context as ctx
from components.theme import AMBER, BLUE, TEAL
from services import formatting as fmt

ui.page_header("Product Analytics", "Adoption and usage by vertical. Responds to the sidebar filters and date range.")

cust = ctx.call("kpis.customers", ctx.fsub())
start, end = ctx.date_range()
sm, em = start[:7], end[:7]

USAGE_SQL = """SELECT k.customer_name, k.vertical, k.licensed_seats, u.month, u.mau, u.sessions, u.logins,
       u.pricing_queries, u.analytics_runs, u.reports_downloaded, u.api_calls
FROM v_monthly_usage u JOIN v_customer_kpis k ON k.customer_id = u.customer_id
WHERE k.vertical = :vertical AND u.month BETWEEN :sm AND :em
ORDER BY u.month"""


def vertical_tab(vertical: str) -> None:
    sub = cust[cust["vertical"] == vertical]
    if sub.empty:
        ui.empty_state(f"No {vertical} accounts match the current filters.")
        return
    u = ctx.q(USAGE_SQL, {"vertical": vertical, "sm": sm, "em": em})
    u = u[u["customer_name"].isin(sub["customer_name"])].copy()
    if u.empty:
        ui.empty_state("No usage in the selected date range.")
        return
    u["Month"] = u["month"].map(fmt.month_label)
    u["adoption_pct"] = 100 * u["mau"] / u["licensed_seats"]

    c = st.columns(4)
    with c[0]:
        ui.kpi_card("Accounts", str(len(sub)), f"{int(sub['licensed_seats'].sum())} licensed seats", "blue")
    with c[1]:
        ui.kpi_card("Seat adoption", fmt.pct(100 * sub["active_users"].sum() / sub["licensed_seats"].sum()),
                    f"{int(sub['active_users'].sum())} active users", "teal")
    with c[2]:
        ui.kpi_card("ARR", ui.gbp(sub["arr_pence"].sum()), "subscription revenue", "teal")
    with c[3]:
        ui.kpi_card("Avg time to first value", f"{sub['ttfv_days'].astype(float).mean():.0f} days",
                    f"range {int(sub['ttfv_days'].min())}–{int(sub['ttfv_days'].max())} days", "amber")

    left, right = st.columns(2)
    with left:
        fig = px.line(u, x="Month", y="adoption_pct", color="customer_name", markers=True,
                      labels={"adoption_pct": "MAU ÷ licensed (%)", "customer_name": ""}, title="Adoption over time")
        fig.update_yaxes(ticksuffix="%", range=[0, 105])
        charts.show(fig, f"adopt_{vertical}")
        ui.show_sql(USAGE_SQL)
    with right:
        tt = sub.sort_values("ttfv_days")
        fig = go.Figure(go.Bar(y=tt["customer_name"], x=tt["ttfv_days"], orientation="h", marker_color=AMBER,
                               text=tt["ttfv_days"].astype(int).astype(str) + " days", textposition="outside"))
        fig.update_layout(title="Time to first value (days from contract start)", xaxis_title="Days")
        charts.show(fig, f"ttfv_{vertical}")

    fa = ctx.q("""SELECT customer_name, feature, adopted, usage_count_90d FROM v_feature_adoption WHERE vertical = :v""",
               {"v": vertical})
    fa = fa[fa["customer_name"].isin(sub["customer_name"])]
    if not fa.empty:
        piv = fa.pivot_table(index="customer_name", columns="feature", values="usage_count_90d", aggfunc="sum").fillna(0)
        adopt = fa.pivot_table(index="customer_name", columns="feature", values="adopted", aggfunc="max").fillna(0)
        text = [[("✓ " if adopt.loc[i, col] else "✗ ") + f"{int(piv.loc[i, col]):,}" for col in piv.columns]
                for i in piv.index]
        fig = go.Figure(go.Heatmap(z=adopt.values, x=list(piv.columns), y=list(piv.index), text=text,
                                   texttemplate="%{text}", colorscale=[[0, "#1E293B"], [1, TEAL]], showscale=False,
                                   hovertemplate="%{y} · %{x}<br>%{text} uses (90 days)<extra></extra>"))
        fig.update_layout(title="Feature adoption heatmap (✓ adopted · usage count, last 90 days)")
        charts.show(fig, f"heat_{vertical}", 90 + 45 * len(piv))

    if vertical == "Flux Bunkers":
        left, right = st.columns(2)
        with left:
            agg = u.groupby("Month", sort=False)[["pricing_queries", "sessions"]].sum().reset_index()
            fig = px.bar(agg, x="Month", y="pricing_queries", title="Pricing-tool queries per month",
                         labels={"pricing_queries": "Queries"}, color_discrete_sequence=[BLUE])
            charts.show(fig, "fb_pq")
        with right:
            pa = ctx.q("""SELECT c.name AS customer_name, p.name AS port, SUM(pa.price_lookups) AS lookups,
                          SUM(pa.stems_reported) AS stems
                          FROM port_activity pa JOIN ports p ON p.port_id = pa.port_id
                          JOIN customers c ON c.customer_id = pa.customer_id
                          WHERE pa.month BETWEEN :sm AND :em GROUP BY c.name, p.name""", {"sm": sm, "em": em})
            pa = pa[pa["customer_name"].isin(sub["customer_name"])]
            fig = px.bar(pa, x="port", y="lookups", color="customer_name", barmode="group",
                         title="Port activity — price lookups by port", labels={"lookups": "Lookups", "port": "",
                                                                                 "customer_name": ""})
            charts.show(fig, "fb_ports")
        ports = ctx.q("""SELECT p.name AS port, p.latitude, p.longitude, COALESCE(SUM(pa.price_lookups + pa.stems_reported), 0)
                         AS activity, MAX(cp.subscribed) AS covered
                         FROM ports p LEFT JOIN port_activity pa ON pa.port_id = p.port_id AND pa.month BETWEEN :sm AND :em
                         LEFT JOIN customer_ports cp ON cp.port_id = p.port_id
                         GROUP BY p.name, p.latitude, p.longitude""", {"sm": sm, "em": em})
        ports["Coverage"] = ports["covered"].map({1: "Covered by a customer", 0: "Activity, not covered"}).fillna("No activity")
        fig = px.scatter_geo(ports, lat=ports["latitude"].astype(float), lon=ports["longitude"].astype(float),
                             size=ports["activity"].astype(float).clip(lower=8), color="Coverage", hover_name="port",
                             hover_data={"activity": True}, projection="natural earth",
                             color_discrete_map={"Covered by a customer": TEAL, "Activity, not covered": AMBER,
                                                 "No activity": "#64748B"},
                             title="Port coverage map — bubble size = price lookups + stems reported")
        fig.update_geos(bgcolor="rgba(0,0,0,0)", landcolor="#1E293B", showocean=True, oceancolor="#0B1220",
                        showcountries=False, coastlinecolor="#334155")
        charts.show(fig, "fb_map", 380)
    elif vertical == "Flux Analytics":
        left, right = st.columns(2)
        with left:
            agg = u.groupby(["Month", "customer_name"], sort=False)[["sessions", "logins", "analytics_runs"]].sum().reset_index()
            fig = px.bar(agg, x="Month", y="sessions", color="customer_name", barmode="group",
                         title="Sessions per month", labels={"customer_name": ""})
            charts.show(fig, "fa_sessions")
        with right:
            inc = ctx.q("""SELECT c.name AS customer_name, substr(i.incident_date, 1, 7) AS month, COUNT(*) AS incidents,
                           SUM(i.duration_hours) AS hours FROM data_incidents i JOIN customers c ON c.customer_id = i.customer_id
                           WHERE i.incident_date BETWEEN :s AND :e GROUP BY c.name, substr(i.incident_date, 1, 7)
                           ORDER BY month""", {"s": start, "e": end})
            if inc.empty:
                st.caption("No data incidents in range.")
            else:
                inc["Month"] = inc["month"].map(fmt.month_label)
                fig = px.bar(inc, x="Month", y="incidents", color="customer_name", title="Data availability incidents",
                             labels={"customer_name": "", "incidents": "Incidents"})
                charts.show(fig, "fa_inc")
        agg = u.groupby("Month", sort=False)[["analytics_runs", "api_calls"]].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(x=agg["Month"], y=agg["analytics_runs"], name="Analytics runs", marker_color=BLUE)
        fig.add_scatter(x=agg["Month"], y=agg["api_calls"], name="API calls", yaxis="y2", line_color=AMBER)
        fig.update_layout(title="Analytics usage", yaxis2=dict(overlaying="y", side="right", showgrid=False))
        charts.show(fig, "fa_runs")
    else:
        left, right = st.columns(2)
        with left:
            agg = u.groupby(["Month", "customer_name"], sort=False)["reports_downloaded"].sum().reset_index()
            fig = px.bar(agg, x="Month", y="reports_downloaded", color="customer_name", barmode="group",
                         title="Report consumption (downloads)", labels={"customer_name": "", "reports_downloaded": "Reports"})
            charts.show(fig, "off_reports")
        with right:
            agg = u.groupby(["Month", "customer_name"], sort=False)[["logins", "api_calls"]].sum().reset_index()
            agg["data_access"] = agg["logins"] + agg["api_calls"]
            fig = px.line(agg, x="Month", y="data_access", color="customer_name", markers=True,
                          title="Data access frequency (logins + API calls)", labels={"customer_name": "",
                                                                                     "data_access": "Accesses"})
            charts.show(fig, "off_access")
        bc = ctx.q("""SELECT c.name AS customer_name, b.benchmark, b.region, b.licensed FROM benchmark_coverage b
                      JOIN customers c ON c.customer_id = b.customer_id""")
        bc = bc[bc["customer_name"].isin(sub["customer_name"])]
        if not bc.empty:
            st.markdown("**Benchmark and market coverage**")
            piv = bc.pivot_table(index="benchmark", columns="customer_name", values="licensed", aggfunc="max").fillna(0)
            st.dataframe(piv.map(lambda x: "Licensed" if x else "—"), width="stretch")


tabs = st.tabs(["Flux Bunkers", "Flux Analytics", "The Officials", "Trading Relationships"])
for tab, v in zip(tabs[:3], ["Flux Bunkers", "Flux Analytics", "The Officials"]):
    with tab:
        vertical_tab(v)

with tabs[3]:
    st.markdown(ui.badge("Trading notional — not revenue", "Monitor") +
                " <span class='muted'>Counterparties are tracked separately: no ARR, seats or subscription health.</span>",
                unsafe_allow_html=True)
    cp = ctx.call("kpis.counterparties", ctx.fsub())
    ta = ctx.q("""SELECT cp.name AS counterparty, t.month, t.trade_count, t.notional_usd FROM trading_activity t
                  JOIN counterparties cp ON cp.counterparty_id = t.counterparty_id
                  WHERE t.month BETWEEN :sm AND :em ORDER BY t.month""", {"sm": sm, "em": em})
    ta = ta[ta["counterparty"].isin(cp["counterparty_name"])]
    left, right = st.columns(2)
    with left:
        if not ta.empty:
            ta["Month"] = ta["month"].map(fmt.month_label)
            fig = px.bar(ta, x="Month", y="trade_count", color="counterparty", title="Trading activity — trades per month",
                         labels={"trade_count": "Trades", "counterparty": ""})
            charts.show(fig, "tr_trades")
    with right:
        appr = cp.groupby("approval_status").size().reset_index(name="count")
        fig = px.bar(appr, x="approval_status", y="count", title="Counterparty approval status",
                     labels={"approval_status": "", "count": "Counterparties"}, color_discrete_sequence=[AMBER])
        charts.show(fig, "tr_appr")
    iss = ctx.q("""SELECT cp.name AS counterparty, i.issue_type, i.severity, i.status, i.opened_date, i.description
                   FROM counterparty_issues i JOIN counterparties cp ON cp.counterparty_id = i.counterparty_id
                   ORDER BY i.status, i.opened_date DESC""")
    st.markdown("**Execution and service issues**")
    st.dataframe(pd.DataFrame({"Counterparty": iss["counterparty"], "Type": iss["issue_type"], "Severity": iss["severity"],
                               "Status": iss["status"], "Opened": iss["opened_date"].map(fmt.fdate),
                               "Description": iss["description"]}), hide_index=True, width="stretch")
    if not ta.empty:
        nt = ta.groupby("counterparty")["notional_usd"].sum().reset_index()
        st.caption("Trading notional in range (USD, not revenue): " +
                   " · ".join(f"{r.counterparty} {fmt.usd(r.notional_usd)}" for r in nt.itertuples()))
