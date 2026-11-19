"""Sidebar: user, Demo Mode selector + guided scenario steps, global filters, interview tour."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from components import context as ctx
from services import demo_mode
from services import formatting as fmt
from services.kpis import HEALTH_CATEGORIES, VERTICALS

TOUR = [
    ("Who is getting value?", "overview", None,
     "Start on the Executive Overview: the 'Who is getting value?' tile lists accounts with strong adoption, rising "
     "usage and positive sentiment — each reason is computed from stored records."),
    ("Evidence of value", "c360", "Northstar Energy Trading",
     "Northstar: 85% seat adoption, MAU up for 12 months, every analytics feature adopted, heavy API use."),
    ("Who is at risk?", "overview", None,
     "Back on the overview, 'Who is at risk?' and the attention list rank accounts by commercial priority."),
    ("Diagnose the risk", "c360", "Gulf Marine Fuels",
     "Gulf Marine: the MAU chart and the computed 60% decline warning, an SLA-breached ticket and a champion who left."),
    ("Act on the risk", "retention", "Gulf Marine Fuels",
     "The retention workspace separates hypotheses from confirmed causes and turns the recovery plan into tasks."),
    ("Where can we grow?", "growth", None,
     "The pipeline separates unweighted potential (£62,000) from the probability-weighted value (£30,200)."),
    ("Report the day", "close", None,
     "The close report compiles today's activity from records and keeps booked revenue apart from pipeline."),
]


def _customer_id_by_name(name: str) -> int | None:
    df = ctx.call("kpis.customers")
    m = df[df["customer_name"] == name]
    return int(m.iloc[0]["customer_id"]) if len(m) else None


def render() -> None:
    sb = st.sidebar
    sb.markdown('<div class="onyx-wordmark">ONYX <span>| Commercial Intelligence</span></div>', unsafe_allow_html=True)
    u = ctx.user()
    c1, c2 = sb.columns([3, 1.3])
    c1.markdown(f"**{u.get('display_name')}**  \n<span class='muted'>{u.get('role_label')}</span>",
                unsafe_allow_html=True)
    if c2.button("Log out", key="logout", type="tertiary"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    # ---- Demo mode
    sb.divider()
    modes = list(demo_mode.MODES)
    sb.selectbox("Demo Mode", modes, format_func=lambda m: demo_mode.MODES[m], key="demo_mode",
                 help="Scenarios run on sandbox copies of the baseline database — exploring them never changes the "
                      "seeded data or the live workspace.")
    m = ctx.mode()
    sb.caption(f"Workspace date: **{fmt.fdate(ctx.as_of())}**")
    if m != "live":
        _scenario_panel(m)

    # ---- Global filters
    sb.divider()
    sb.markdown("**Filters**")
    f = ctx.filters()
    owners = ctx.call("kpis.owners")["name"].tolist()
    as_of = ctx.as_of_date()
    ss = st.session_state
    ss.setdefault("f_verticals", f["verticals"])
    ss.setdefault("f_owners", f["owners"])
    ss.setdefault("f_health", f["health"])
    ss.setdefault("f_dates", (f["start"], f["end"]))
    f["verticals"] = sb.multiselect("Product vertical", VERTICALS, key="f_verticals", placeholder="All verticals")
    f["owners"] = sb.multiselect("Relationship owner", owners, key="f_owners", placeholder="All owners")
    f["health"] = sb.multiselect("Health status", HEALTH_CATEGORIES, key="f_health", placeholder="All statuses")
    rng = sb.date_input("Date range", key="f_dates", max_value=as_of, min_value=as_of - timedelta(days=400),
                        format="DD/MM/YYYY")
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        f["start"], f["end"] = rng
    if sb.button("Clear filters", type="tertiary", key="clear_filters"):
        for k in ("filters", "f_verticals", "f_owners", "f_health", "f_dates"):
            ss.pop(k, None)
        st.rerun()
    st.session_state["filters"] = f

    # ---- Tour
    sb.divider()
    _tour_panel()


def _scenario_panel(m: str) -> None:
    sb = st.sidebar
    sc = demo_mode.SCENARIOS[m]
    with sb.container(border=True):
        st.markdown(f"**{sc['title']}**")
        st.caption(sc["intro"])
        done = st.session_state.setdefault(f"scenario_done_{m}", set())
        for i, (title, narration, page, focus) in enumerate(sc["steps"]):
            cols = st.columns([0.14, 0.64, 0.22])
            checked = cols[0].checkbox(" ", value=i in done, key=f"sc_{m}_{i}", label_visibility="collapsed")
            (done.add if checked else done.discard)(i)
            cols[1].markdown(f"<span style='font-size:.82rem'>{i + 1}. {title}</span>", unsafe_allow_html=True)
            if cols[2].button("Go", key=f"sc_go_{m}_{i}", type="tertiary", help=narration):
                st.session_state["scenario_narration"] = f"Step {i + 1}: {narration}"
                cid = _customer_id_by_name(focus) if focus else None
                if page in ("retention", "growth") and cid:
                    st.session_state["focus_customer"] = cid
                ctx.goto(page, customer_id=cid if page == "c360" else None)
        st.progress(len(done) / len(sc["steps"]), text=f"{len(done)}/{len(sc['steps'])} steps")
        if st.button("Reset scenario", key=f"reset_sc_{m}", icon=":material/restart_alt:"):
            demo_mode.reset_sandbox(m)
            st.session_state[f"scenario_done_{m}"] = set()
            st.cache_data.clear()
            st.session_state["_toast"] = "Scenario sandbox reset from baseline"
            st.rerun()


def _tour_panel() -> None:
    sb = st.sidebar
    step = st.session_state.get("tour_step")
    if step is None:
        if sb.button("Start tour", icon=":material/tour:", key="tour_start",
                     help="Walk through: Who is getting value? Who is at risk? Where can we grow?"):
            st.session_state["tour_step"] = 0
            _tour_go(0)
        return
    title, _, _, text = TOUR[step]
    with sb.container(border=True):
        st.markdown(f"**Tour {step + 1}/{len(TOUR)} — {title}**")
        st.caption(text)
        c1, c2, c3 = st.columns(3)
        if c1.button("Back", disabled=step == 0, key="tour_back"):
            st.session_state["tour_step"] = step - 1
            _tour_go(step - 1)
        if step < len(TOUR) - 1:
            if c2.button("Next", type="primary", key="tour_next"):
                st.session_state["tour_step"] = step + 1
                _tour_go(step + 1)
        if c3.button("End", key="tour_end"):
            st.session_state.pop("tour_step")
            st.rerun()


def _tour_go(i: int) -> None:
    _, page, focus, _ = TOUR[i]
    cid = _customer_id_by_name(focus) if focus else None
    if cid and page == "retention":
        st.session_state["focus_customer"] = cid
    ctx.goto(page, customer_id=cid if page == "c360" else None)


def narration() -> None:
    """Show the current tour / scenario narration at the top of a page."""
    step = st.session_state.get("tour_step")
    if step is not None:
        st.info(f"**Tour — {TOUR[step][0]}.** {TOUR[step][3]}", icon=":material/tour:")
    n = st.session_state.pop("scenario_narration", None)
    if n and ctx.mode() != "live":
        st.info(n, icon=":material/play_circle:")
