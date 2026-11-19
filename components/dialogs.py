"""Action dialogs: each validates, saves to the database, writes audit_log, and refreshes every view."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from components import context as ctx
from services import customers, opportunities, tasks


def _owner_select(label: str, key: str, default_id: int | None = None) -> int | None:
    owners = ctx.call("kpis.owners")
    ids = owners["owner_id"].tolist()
    names = dict(zip(owners["owner_id"], owners["name"]))
    idx = ids.index(default_id) if default_id in ids else (ids.index(ctx.user().get("owner_id"))
                                                           if ctx.user().get("owner_id") in ids else 0)
    return st.selectbox(label, ids, index=idx, format_func=lambda i: names[i], key=key)


def _customer_select(key: str, default_id: int | None = None, include_none: bool = False):
    df = ctx.call("kpis.customers")
    ids = df["customer_id"].tolist()
    names = dict(zip(df["customer_id"], df["customer_name"]))
    opts = ([None] if include_none else []) + ids
    idx = opts.index(default_id) if default_id in opts else 0
    return st.selectbox("Customer", opts, index=idx, key=key,
                        format_func=lambda i: "— None (internal / counterparty) —" if i is None else names[i])


def _done(msg: str) -> None:
    ctx.after_write(msg)
    st.rerun()


@st.dialog("Follow-up task", width="large")
def task_dialog(task: dict | None = None, customer_id: int | None = None, counterparty_id: int | None = None,
                default_title: str = "", default_category: str = "Sales follow-up") -> None:
    t = task or {}
    as_of = ctx.as_of_date()
    with st.form("task_form", border=False):
        title = st.text_input("Title *", value=t.get("title", default_title), max_chars=200)
        c1, c2 = st.columns(2)
        with c1:
            cat = st.selectbox("Category *", tasks.CATEGORIES,
                               index=tasks.CATEGORIES.index(t.get("category", default_category)))
            pri = st.selectbox("Priority *", tasks.PRIORITIES, index=tasks.PRIORITIES.index(t.get("priority", "Medium")))
            status = st.selectbox("Status", tasks.STATUSES, index=tasks.STATUSES.index(t.get("status", "Open")))
        with c2:
            owner = _owner_select("Owner *", "task_owner", t.get("owner_id"))
            due = st.date_input("Due date *", value=date.fromisoformat(t["due_date"]) if t.get("due_date")
                                else as_of + timedelta(days=2), format="DD/MM/YYYY")
            if counterparty_id or t.get("counterparty_id"):
                st.text_input("Counterparty", value="Linked counterparty", disabled=True)
                cid = None
            else:
                cid = _customer_select("task_customer", t.get("customer_id", customer_id), include_none=True)
        notes = st.text_area("Notes", value=t.get("notes") or "", height=80)
        submitted = st.form_submit_button("Save task", type="primary")
    if submitted:
        data = {"title": title, "customer_id": cid, "counterparty_id": counterparty_id or t.get("counterparty_id"),
                "category": cat, "priority": pri, "owner_id": owner, "due_date": due, "status": status, "notes": notes}
        try:
            if t.get("task_id"):
                tasks.update(ctx.engine(), ctx.user_email(), int(t["task_id"]), data)
            else:
                tasks.create(ctx.engine(), ctx.user_email(), data)
        except ValueError as e:
            st.error(str(e))
            return
        _done("Task saved")


@st.dialog("Add account note")
def note_dialog(customer_id: int | None = None, counterparty_id: int | None = None) -> None:
    with st.form("note_form", border=False):
        body = st.text_area("Note *", height=140, max_chars=4000)
        ok = st.form_submit_button("Save note", type="primary")
    if ok:
        try:
            customers.add_note(ctx.engine(), ctx.user_email(), body, customer_id, counterparty_id)
        except ValueError as e:
            st.error(str(e))
            return
        _done("Note added")


@st.dialog("Record customer interaction", width="large")
def meeting_dialog(customer_id: int | None = None, counterparty_id: int | None = None, contacts: list[str] | None = None,
                   default_type: str = "Meeting") -> None:
    as_of = ctx.as_of_date()
    types = ["Meeting", "Call", "Email", "Demo"]
    with st.form("meeting_form", border=False):
        c1, c2 = st.columns(2)
        with c1:
            typ = st.selectbox("Type *", types, index=types.index(default_type))
            d = st.date_input("Date *", value=as_of, max_value=as_of, format="DD/MM/YYYY")
        with c2:
            subject = st.text_input("Subject *", max_chars=200)
            attendees = st.multiselect("Attendees (required for meetings)", contacts or [], default=[])
            extra = st.text_input("Other attendees", placeholder="Comma separated")
        summary = st.text_area("Summary", height=90)
        c3, c4 = st.columns([1, 2])
        with c3:
            record_sent = st.checkbox("Record sentiment", value=typ == "Meeting")
            sentiment = st.slider("Customer sentiment (1 = negative, 5 = very positive)", 1, 5, 3)
        with c4:
            next_steps = st.text_area("Next steps", height=90)
        st.markdown("**Create follow-up tasks** (optional)")
        fups = []
        for i in range(2):
            a, b, c = st.columns([3, 1.4, 1.4])
            t = a.text_input(f"Task {i + 1}", key=f"fu_t{i}", placeholder="Leave blank to skip")
            due = b.date_input("Due", value=as_of + timedelta(days=3 + 4 * i), key=f"fu_d{i}", format="DD/MM/YYYY")
            pri = c.selectbox("Priority", tasks.PRIORITIES, index=1, key=f"fu_p{i}")
            if t.strip():
                fups.append({"title": t, "category": "Sales follow-up", "priority": pri,
                             "owner_id": ctx.user().get("owner_id") or 1, "due_date": due, "status": "Open"})
        ok = st.form_submit_button("Save", type="primary")
    if ok:
        att = ", ".join(attendees + [x.strip() for x in extra.split(",") if x.strip()])
        try:
            customers.log_activity(ctx.engine(), ctx.user_email(), activity_type=typ, activity_date=d, subject=subject,
                                   summary=summary, customer_id=customer_id, counterparty_id=counterparty_id,
                                   attendees=att, sentiment=sentiment if record_sent else None, next_steps=next_steps,
                                   owner_id=ctx.user().get("owner_id"), follow_up_tasks=fups)
        except ValueError as e:
            st.error(str(e))
            return
        _done(f"{typ} recorded" + (f" with {len(fups)} follow-up task(s)" if fups else ""))


@st.dialog("Log support escalation", width="large")
def escalation_dialog(customer_id: int) -> None:
    open_t = ctx.q("""SELECT ticket_id, subject, severity, status FROM support_tickets WHERE customer_id = :c
                      AND status NOT IN ('Resolved', 'Closed') ORDER BY opened_date DESC""", {"c": customer_id})
    opts = [None] + open_t["ticket_id"].tolist()
    labels = {r.ticket_id: f"#{r.ticket_id} {r.severity} — {r.subject} ({r.status})" for r in open_t.itertuples()}
    with st.form("esc_form", border=False):
        tid = st.selectbox("Ticket", opts, format_func=lambda i: "➕ Open a new escalated ticket" if i is None else labels[i])
        subject = st.text_input("New ticket subject (if opening a new ticket)")
        sev = st.selectbox("Severity", customers.SEVERITIES, index=2)
        reason = st.text_area("Escalation reason *", height=100)
        ok = st.form_submit_button("Escalate", type="primary")
    if ok:
        try:
            customers.log_escalation(ctx.engine(), ctx.user_email(), customer_id, reason=reason, ticket_id=tid,
                                     subject=subject, severity=sev, owner_id=ctx.user().get("owner_id"))
        except ValueError as e:
            st.error(str(e))
            return
        _done("Escalation logged")


@st.dialog("Expansion opportunity", width="large")
def opportunity_dialog(opp: dict | None = None, customer_id: int | None = None) -> None:
    o = opp or {}
    as_of = ctx.as_of_date()
    cdf = ctx.call("kpis.customers")
    product_by_customer = dict(zip(cdf["customer_id"], cdf["vertical"]))
    prod_ids = {"Flux Bunkers": "FB", "Flux Analytics": "FA", "The Officials": "OFF"}
    with st.form("opp_form", border=False):
        cid = _customer_select("opp_customer", o.get("customer_id", customer_id))
        desc = st.text_input("Description *", value=o.get("description", ""), max_chars=200)
        c1, c2, c3 = st.columns(3)
        with c1:
            pounds = st.number_input("Potential annual revenue (£) *", min_value=0, step=1000,
                                     value=int((o.get("potential_arr_pence") or 0) / 100))
        with c2:
            prob = st.slider("Close probability (%)", 0, 100, int(round(float(o.get("probability", 0.2)) * 100)), 5)
        with c3:
            stage = st.selectbox("Stage", opportunities.STAGES,
                                 index=opportunities.STAGES.index(o.get("stage", "Identified")))
        c4, c5 = st.columns(2)
        with c4:
            close = st.date_input("Expected close date *", value=date.fromisoformat(o["expected_close_date"])
                                  if o.get("expected_close_date") else as_of + timedelta(days=60), format="DD/MM/YYYY")
        with c5:
            owner = _owner_select("Owner *", "opp_owner", o.get("owner_id"))
        nxt = st.text_input("Next action", value=o.get("next_action") or "")
        st.caption(f"Expected value = potential × probability = £{pounds * prob / 100:,.0f}")
        ok = st.form_submit_button("Save opportunity", type="primary")
    if ok:
        data = {"customer_id": cid, "product_id": prod_ids[product_by_customer[cid]], "description": desc,
                "potential_arr_pence": pounds * 100, "probability": prob / 100, "stage": stage,
                "expected_close_date": close, "owner_id": owner, "next_action": nxt}
        try:
            if o.get("opportunity_id"):
                changed = {k: v for k, v in data.items()
                           if k != "expected_close_date" or v.isoformat() != o.get("expected_close_date")}
                opportunities.update(ctx.engine(), ctx.user_email(), int(o["opportunity_id"]), changed)
            else:
                opportunities.create(ctx.engine(), ctx.user_email(), data)
        except ValueError as e:
            st.error(str(e))
            return
        _done("Opportunity saved")


@st.dialog("Edit account details")
def account_dialog(customer_id: int, licensed: int, active: int, owner_id: int | None) -> None:
    with st.form("acct_form", border=False):
        lic = st.number_input("Licensed seats", min_value=0, value=int(licensed), step=1)
        act = st.number_input("Active users", min_value=0, value=int(active), step=1)
        owner = _owner_select("Relationship owner", "acct_owner", owner_id)
        ok = st.form_submit_button("Save", type="primary")
    if ok:
        try:
            customers.update_account(ctx.engine(), ctx.user_email(), customer_id, licensed_seats=lic,
                                     active_users=act, owner_id=owner)
        except ValueError as e:
            st.error(str(e))
            return
        _done("Account updated")


@st.dialog("Confirm delete")
def confirm_delete(kind: str, label: str, fn, *args) -> None:
    st.warning(f"Delete {kind} **{label}**? This cannot be undone (the deletion is recorded in the audit trail).")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", key="confirm_del"):
        try:
            fn(ctx.engine(), ctx.user_email(), *args)
        except ValueError as e:
            st.error(str(e))
            return
        _done(f"{kind.capitalize()} deleted")
    if c2.button("Cancel", key="cancel_del"):
        st.rerun()
