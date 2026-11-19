import html

import streamlit as st

from components import context as ctx
from components import dialogs, ui
from services import auth, tasks
from services import formatting as fmt

ui.page_header("Tasks & Follow-ups", "Every task created anywhere in the app appears here immediately.")
can_edit = auth.can_edit(ctx.user())
eng = ctx.engine()
df = ctx.call("tasks.list_all")

counts = df["bucket"].value_counts()
c = st.columns(4)
with c[0]:
    ui.kpi_card("Overdue", str(counts.get("Overdue", 0)), "open, past due", "red")
with c[1]:
    ui.kpi_card("Due today", str(counts.get("Due today", 0)), fmt.fdate(ctx.as_of()), "amber")
with c[2]:
    ui.kpi_card("Upcoming", str(counts.get("Upcoming", 0)), "open, future", "blue")
with c[3]:
    ui.kpi_card("Completed", str(counts.get("Done", 0)), "all time", "teal")

a, b, cc, d, e = st.columns([1.6, 1.4, 1.6, 1.6, 1.2])
view = a.segmented_control("View", ["Overdue", "Due today", "Upcoming", "My tasks", "All"], default="All",
                           key="task_view") or "All"
owner = b.selectbox("Owner", ["All"] + sorted(df["owner_name"].unique()), key="task_owner_f")
cat = cc.selectbox("Category", ["All"] + tasks.CATEGORIES, key="task_cat_f")
acct = d.selectbox("Account", ["All"] + sorted(df["account_name"].dropna().unique()), key="task_acct_f")
show_done = e.toggle("Show done", value=False, key="task_done_f")

v = df.copy()
if view in ("Overdue", "Due today", "Upcoming"):
    v = v[v["bucket"] == view]
elif view == "My tasks":
    v = v[v["owner_id"] == ctx.user().get("owner_id")]
if owner != "All":
    v = v[v["owner_name"] == owner]
if cat != "All":
    v = v[v["category"] == cat]
if acct != "All":
    v = v[v["account_name"] == acct]
if not show_done:
    v = v[v["status"] != "Done"]

if can_edit and st.button("New task", type="primary", icon=":material/add_task:"):
    dialogs.task_dialog()

if v.empty:
    ui.empty_state("No tasks match this view.")
    st.stop()

selected = []
kind = {"Overdue": "AtRisk", "Due today": "Monitor", "Upcoming": "Info", "Done": "Healthy"}
for t in v.itertuples():
    with st.container(border=True):
        cols = st.columns([0.35, 5, 0.9, 0.9, 0.9])
        if can_edit and t.status != "Done" and cols[0].checkbox(" ", key=f"sel_{t.task_id}", label_visibility="collapsed"):
            selected.append(int(t.task_id))
        cols[1].markdown(
            f"{ui.badge(t.bucket, kind[t.bucket])} {ui.badge(t.priority, 'AtRisk' if t.priority == 'Critical' else 'Monitor' if t.priority == 'High' else 'Neutral')} "
            f"**{html.escape(t.title)}**<br><span class='muted'>{t.category} · {html.escape(fmt.txt(t.account_name) or 'Internal')} · "
            f"{t.owner_name} · due {fmt.fdate(t.due_date)} · {t.status}"
            f"{' · ' + html.escape(fmt.txt(t.notes)) if fmt.txt(t.notes) else ''}</span>", unsafe_allow_html=True)
        if can_edit:
            if t.status != "Done" and cols[2].button("Done", key=f"done_{t.task_id}"):
                if ctx.run_safely(tasks.complete, eng, ctx.user_email(), [int(t.task_id)], success="Task completed"):
                    st.rerun()
            if cols[3].button("Edit", key=f"edit_{t.task_id}"):
                dialogs.task_dialog(task=tasks.get(eng, int(t.task_id)))
            if cols[4].button("Delete", key=f"delt_{t.task_id}"):
                dialogs.confirm_delete("task", t.title, tasks.delete, int(t.task_id))

if can_edit:
    if st.button(f"Complete selected ({len(selected)})", disabled=not selected, icon=":material/done_all:"):
        if ctx.run_safely(tasks.complete, eng, ctx.user_email(), selected, success=f"{len(selected)} task(s) completed"):
            for i in selected:
                st.session_state.pop(f"sel_{i}", None)
            st.rerun()
else:
    ui.require_edit()
