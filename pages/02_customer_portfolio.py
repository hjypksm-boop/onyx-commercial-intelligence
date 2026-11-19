import pandas as pd
import streamlit as st

from components import context as ctx
from components import ui
from services import exports
from services import formatting as fmt
from services.priority import EXPLANATION as PRIORITY_EXPLANATION

ui.page_header("Customer Portfolio", "Search, filter and open any account. Sidebar filters apply in addition to these.")

tab_subs, tab_cp = st.tabs(["Subscription customers", "Trading Relationships"])

with tab_subs:
    df = ctx.call("kpis.customers", ctx.fsub())
    if df.empty:
        ui.empty_state("No accounts match the sidebar filters.")
        st.stop()
    max_rev = int(df["arr_pence"].max() / 100)
    c1, c2, c3, c4 = st.columns([2, 1.2, 1.6, 1.2])
    search = c1.text_input("Search", placeholder="Customer, owner or vertical", key="pf_search")
    window = c2.selectbox("Renewal window", ["All", "≤30 days", "≤60 days", "≤90 days", "≤180 days"], key="pf_window")
    rev = c3.slider("Annual revenue (£)", 0, max(max_rev, 1000), (0, max(max_rev, 1000)), step=1000, key="pf_rev")
    sort = c4.selectbox("Sort by", ["Commercial priority", "Revenue", "Adoption", "Renewal date"], key="pf_sort")

    v = df.copy()
    if search:
        s = search.lower()
        v = v[v["customer_name"].str.lower().str.contains(s, regex=False)
              | v["owner_name"].str.lower().str.contains(s, regex=False)
              | v["vertical"].str.lower().str.contains(s, regex=False)]
    if window != "All":
        v = v[v["days_to_renewal"] <= int(window.strip("≤ days"))]
    v = v[(v["arr_pence"] / 100 >= rev[0]) & (v["arr_pence"] / 100 <= rev[1])]
    key, asc = {"Commercial priority": ("priority_score", False), "Revenue": ("arr_pence", False),
                "Adoption": ("adoption_pct", False), "Renewal date": ("renewal_date", True)}[sort]
    v = v.sort_values(key, ascending=asc).reset_index(drop=True)

    table = pd.DataFrame({
        "Customer": v["customer_name"], "Vertical": v["vertical"], "ACV": (v["arr_pence"] / 100).astype(int),
        "Licensed": v["licensed_seats"], "Active": v["active_users"], "Adoption": v["adoption_pct"].round(1),
        "Health": v.apply(lambda r: f"{r.health_category} · {r.health_score:.0f}"
                          + (" (partial)" if r.components_available < 5 else ""), axis=1),
        "Renewal": pd.to_datetime(v["renewal_date"]), "Owner": v["owner_name"],
        "Expansion": (v["potential_expansion_pence"] / 100).astype(int),
        "Last contact": pd.to_datetime(v["last_contact_date"]), "Priority": v["priority_score"]})
    st.caption(f"{len(v)} of {len(df)} accounts · total ACV {ui.gbp(v['arr_pence'].sum())}. "
               "Select a row to open Customer 360.")
    sel = st.dataframe(
        table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key=f"pf_table_{st.session_state.get('pf_nonce', 0)}",
        column_config={
            "ACV": ui.money_col("Annual contract value"), "Expansion": ui.money_col("Potential expansion"),
            "Adoption": st.column_config.ProgressColumn("Adoption %", min_value=0, max_value=100, format="%.1f%%"),
            "Renewal": st.column_config.DateColumn("Renewal date", format="D MMM YYYY"),
            "Last contact": st.column_config.DateColumn("Last contact", format="D MMM YYYY"),
            "Priority": st.column_config.ProgressColumn("Commercial priority", min_value=0, max_value=100, format="%.0f",
                                                        help=PRIORITY_EXPLANATION),
        })
    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        st.session_state["pf_nonce"] = st.session_state.get("pf_nonce", 0) + 1
        ctx.goto("c360", customer_id=int(v.iloc[rows[0]]["customer_id"]))
    csv = table.assign(Renewal=table["Renewal"].dt.date, **{"Last contact": table["Last contact"].dt.date})
    st.download_button("Export filtered view (CSV)", exports.df_csv(csv), "customer_portfolio.csv", "text/csv",
                       icon=":material/download:")
    with st.expander("How is commercial priority calculated?"):
        st.write(PRIORITY_EXPLANATION)
        st.dataframe(v[["customer_name", "p_revenue", "p_risk", "p_renewal", "p_expansion", "priority_score"]]
                     .rename(columns={"customer_name": "Customer", "p_revenue": "Revenue exposure",
                                      "p_risk": "Risk", "p_renewal": "Renewal urgency", "p_expansion": "Expansion",
                                      "priority_score": "Priority"}).round(1), hide_index=True, width="stretch")

with tab_cp:
    st.markdown(ui.badge("Trading notional — not revenue", "Monitor") +
                " <span class='muted'>Counterparties have no ARR or seats and are excluded from every revenue, adoption "
                "and health KPI.</span>", unsafe_allow_html=True)
    cp = ctx.call("kpis.counterparties", ctx.fsub())
    if cp.empty:
        ui.empty_state("No counterparties match the owner filter.")
    else:
        t = pd.DataFrame({"Counterparty": cp["counterparty_name"], "Region": cp["region"],
                          "Relationship": cp["relationship_status"], "Approval": cp["approval_status"],
                          "Trades (12m)": cp["trades_12m"],
                          "Notional 12m (USD, not revenue)": cp["notional_usd_12m"].map(fmt.usd),
                          "Open issues": cp["open_issues"], "Owner": cp["owner_name"],
                          "Last contact": cp["last_contact_date"].map(fmt.fdate)})
        sel2 = st.dataframe(t, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                            key=f"cp_table_{st.session_state.get('pf_nonce', 0)}")
        rows2 = sel2.selection.rows if sel2 and sel2.selection else []
        if rows2:
            st.session_state["pf_nonce"] = st.session_state.get("pf_nonce", 0) + 1
            ctx.goto("c360", counterparty_id=int(cp.iloc[rows2[0]]["counterparty_id"]))
        st.download_button("Export counterparties (CSV)", exports.df_csv(t), "trading_relationships.csv", "text/csv",
                           icon=":material/download:")
