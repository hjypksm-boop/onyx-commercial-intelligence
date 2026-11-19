import html
import json
from datetime import date

import pandas as pd
import streamlit as st

from components import context as ctx
from components import dialogs, ui
from services import auth, db, opportunities
from services import formatting as fmt

ui.page_header("Growth Opportunities", "Expansion and cross-sell pipeline. Expected value = potential annual revenue × "
                                       "probability. Booked revenue is shown separately from pipeline.")
can_edit = auth.can_edit(ctx.user())
eng = ctx.engine()

pipe = ctx.call("opportunities.pipeline")
cust = ctx.call("kpis.customers", ctx.fsub())
pipe = pipe[pipe["customer_id"].isin(cust["customer_id"])]
names = dict(zip(cust["customer_id"], cust["customer_name"]))
focus_opts = [None] + list(names)
focus = st.session_state.get("focus_customer")
c1, c2, c3 = st.columns([2, 1.4, 1])
fc = c1.selectbox("Customer", focus_opts, index=focus_opts.index(focus) if focus in focus_opts else 0,
                  format_func=lambda i: "All customers" if i is None else names[i], key="growth_focus")
view = c2.segmented_control("View", ["Board", "Table"], default="Board", key="growth_view") or "Board"
if can_edit and c3.button("New opportunity", type="primary", icon=":material/add:", width="stretch"):
    dialogs.opportunity_dialog(customer_id=fc)
if fc is not None:
    pipe = pipe[pipe["customer_id"] == fc]

open_p = pipe[pipe["is_open"] == 1]
won = pipe[pipe["stage"] == "Closed Won"]
as_of = ctx.as_of()
k = st.columns(4)
sql = db.query_text("pipeline_totals")
with k[0]:
    ui.kpi_card("Total potential expansion", ui.gbp(open_p["potential_arr_pence"].sum()),
                f"{len(open_p)} open opportunities · unweighted", "amber", sql)
with k[1]:
    ui.kpi_card("Probability-weighted pipeline", ui.gbp(open_p["expected_value_pence"].sum()),
                "Σ potential × probability", "blue", sql)
with k[2]:
    ui.kpi_card("Booked new ACV — today", ui.gbp(won[won["closed_date"] == as_of]["potential_arr_pence"].sum()),
                "Closed Won on the workspace date", "teal", sql)
with k[3]:
    ui.kpi_card("Booked new ACV — all time", ui.gbp(won["potential_arr_pence"].sum()),
                f"{len(won)} Closed Won deal(s) · not pipeline", "teal", sql)

if pipe.empty:
    ui.empty_state("No opportunities for this selection. Create one with 'New opportunity'.")
    st.stop()


def card(o) -> None:
    with st.container(border=True):
        st.markdown(f"**{html.escape(o.description)}**  \n<span class='muted'>{html.escape(o.customer_name)} · "
                    f"{o.product}</span>", unsafe_allow_html=True)
        tone = "booked" if o.stage == "Closed Won" else "pipeline" if o.is_open else ""
        st.markdown(f"<div class='{tone}' style='font-size:.82rem'>{ui.gbp(o.potential_arr_pence)} × "
                    f"{float(o.probability) * 100:.0f}% = <b>{ui.gbp(o.expected_value_pence)}</b><br>"
                    f"<span class='muted'>Close {fmt.fdate(o.expected_close_date)} · {o.owner_name}</span><br>"
                    f"<span class='muted'>Next: {html.escape(fmt.txt(o.next_action) or '—')}</span></div>",
                    unsafe_allow_html=True)
        if can_edit:
            others = [s for s in opportunities.STAGES if s != o.stage]
            mv = st.selectbox("Move to…", [""] + others, key=f"mv_{o.opportunity_id}", label_visibility="collapsed",
                              format_func=lambda s: "Move to…" if s == "" else s)
            if mv:
                if ctx.run_safely(opportunities.move_stage, eng, ctx.user_email(), int(o.opportunity_id), mv,
                                  success=f"Moved to {mv}"):
                    st.session_state.pop(f"mv_{o.opportunity_id}", None)
                    st.rerun()
            a, b = st.columns(2)
            if a.button("Edit", key=f"ed_{o.opportunity_id}", width="stretch"):
                dialogs.opportunity_dialog(opp=opportunities.get(eng, int(o.opportunity_id)))
            if b.button("Delete", key=f"del_{o.opportunity_id}", width="stretch"):
                dialogs.confirm_delete("opportunity", o.description, opportunities.delete, int(o.opportunity_id))


if view == "Board":
    show_closed = st.toggle("Show closed deals", value=False, key="growth_closed")
    stages = opportunities.STAGES if show_closed else opportunities.OPEN_STAGES
    cols = st.columns(len(stages))
    for col, stage in zip(cols, stages):
        sub = pipe[pipe["stage"] == stage]
        with col:
            st.markdown(f"<div class='kanban-head'>{stage} · {len(sub)}<br>{ui.gbp(sub['potential_arr_pence'].sum())}</div>",
                        unsafe_allow_html=True)
            for o in sub.itertuples():
                card(o)
else:
    owners = ctx.call("kpis.owners")
    oname = dict(zip(owners["owner_id"], owners["name"]))
    oid = {v: k for k, v in oname.items()}
    t = pd.DataFrame({
        "id": pipe["opportunity_id"], "Customer": pipe["customer_name"], "Description": pipe["description"],
        "Potential (£)": (pipe["potential_arr_pence"] / 100).astype(int),
        "Probability (%)": (pipe["probability"].astype(float) * 100).round().astype(int),
        "Expected value (£)": (pipe["expected_value_pence"] / 100).astype(int), "Stage": pipe["stage"],
        "Expected close": pd.to_datetime(pipe["expected_close_date"]).dt.date,
        "Owner": pipe["owner_id"].map(oname), "Next action": pipe["next_action"].fillna("")}).reset_index(drop=True)
    edited = st.data_editor(
        t, hide_index=True, width="stretch", disabled=True if not can_edit else ["id", "Customer", "Expected value (£)"],
        key=f"opp_editor_{st.session_state.get('opp_nonce', 0)}",
        column_config={"id": None, "Stage": st.column_config.SelectboxColumn("Stage", options=opportunities.STAGES),
                       "Owner": st.column_config.SelectboxColumn("Owner", options=list(oid)),
                       "Potential (£)": st.column_config.NumberColumn(min_value=1, step=500, format="£%,d"),
                       "Expected value (£)": st.column_config.NumberColumn(format="£%,d"),
                       "Probability (%)": st.column_config.NumberColumn(min_value=0, max_value=100, step=5),
                       "Expected close": st.column_config.DateColumn(format="D MMM YYYY")})
    if can_edit and st.button("Save table changes", type="primary"):
        errors, n = [], 0
        for (_, a), (_, b) in zip(t.iterrows(), edited.iterrows()):
            changes = {}
            if a["Description"] != b["Description"]:
                changes["description"] = b["Description"]
            if a["Potential (£)"] != b["Potential (£)"]:
                changes["potential_arr_pence"] = int(b["Potential (£)"] or 0) * 100
            if a["Probability (%)"] != b["Probability (%)"]:
                changes["probability"] = float(b["Probability (%)"] or 0) / 100
            if a["Stage"] != b["Stage"]:
                changes["stage"] = b["Stage"]
            if a["Expected close"] != b["Expected close"]:
                changes["expected_close_date"] = b["Expected close"].isoformat() if isinstance(b["Expected close"], date) else None
            if a["Owner"] != b["Owner"]:
                changes["owner_id"] = oid.get(b["Owner"])
            if a["Next action"] != b["Next action"]:
                changes["next_action"] = b["Next action"]
            if changes:
                try:
                    opportunities.update(eng, ctx.user_email(), int(a["id"]), changes)
                    n += 1
                except ValueError as e:
                    errors.append(f"{a['Description']}: {e}")
        for e in errors:
            st.error(e)
        if n:
            st.session_state["opp_nonce"] = st.session_state.get("opp_nonce", 0) + 1
            ctx.after_write(f"{n} opportunit{'y' if n == 1 else 'ies'} updated")
            if not errors:
                st.rerun()
    st.download_button("Export pipeline (CSV)", t.drop(columns=["id"]).to_csv(index=False).encode(), "pipeline.csv",
                       "text/csv", icon=":material/download:")

# ------------------------------------------------------------------ qualification & history
st.subheader("Qualification & stage history")
op_ids = pipe["opportunity_id"].tolist()
od = dict(zip(pipe["opportunity_id"], pipe["customer_name"] + " — " + pipe["description"]))
sel = st.selectbox("Opportunity", op_ids, format_func=od.get, key="qual_opp")
o = opportunities.get(eng, int(sel))
a, b = st.columns(2)
with a:
    st.markdown("**Qualification checklist**")
    q = json.loads(o["qualification"] or "{}")
    vals = {item: st.checkbox(item, value=q.get(item, False), key=f"q_{sel}_{item}", disabled=not can_edit)
            for item in opportunities.QUALIFICATION}
    notes = st.text_input("Qualification notes", value=q.get("notes", ""), key=f"qn_{sel}", disabled=not can_edit)
    st.caption(f"{sum(vals.values())} of {len(vals)} criteria met")
    if can_edit and st.button("Save qualification", key="save_q"):
        if ctx.run_safely(opportunities.update, eng, ctx.user_email(), int(sel),
                          {"qualification": json.dumps({**vals, "notes": notes})}, success="Qualification saved"):
            st.rerun()
with b:
    st.markdown("**Stage history**")
    h = opportunities.stage_history(eng, int(sel))
    st.dataframe(pd.DataFrame({"Date": h["changed_on"].map(fmt.fdate), "From": h["from_stage"].fillna("—"),
                               "To": h["to_stage"], "By": h["changed_by"]}), hide_index=True, width="stretch")
    if o["stage"] == "Closed Won":
        st.markdown(f"<div class='booked'>Booked new ACV: <b>{ui.gbp(o['potential_arr_pence'])}</b> on "
                    f"{fmt.fdate(o['closed_date'])} — no longer counted as potential expansion.</div>", unsafe_allow_html=True)
