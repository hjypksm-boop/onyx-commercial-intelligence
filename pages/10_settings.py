import pandas as pd
import streamlit as st

from components import context as ctx
from components import ui
from services import ai, auth, config, db, demo_mode, health, seed
from services import formatting as fmt

ui.page_header("Settings", "Health-score weights, AI configuration, demonstration data, audit trail and data quality.")
eng = ctx.engine()
can_edit = auth.can_edit(ctx.user())
tabs = st.tabs(["Health score weights", "AI settings", "Demo data", "Audit trail", "Data quality"])

# ============================================================== weights
with tabs[0]:
    current = health.get_weights(eng)
    if st.session_state.get("w_reset"):
        for k, _ in health.COMPONENTS:
            st.session_state[f"w_{k}"] = health.DEFAULT_WEIGHTS[k]
        st.session_state.pop("w_reset")
    st.caption("Components are normalised to 0–100. Categories: 80–100 Healthy · 60–79 Monitor · below 60 At Risk. Missing "
               "components are excluded and the remaining weights re-normalised (a 'Partial score' badge is shown).")
    cols = st.columns(5)
    proposed = {}
    for col, (k, label) in zip(cols, health.COMPONENTS):
        with col:
            st.session_state.setdefault(f"w_{k}", current[k])
            proposed[k] = int(st.number_input(f"{label} (%)", 0, 100, step=5, key=f"w_{k}", disabled=not can_edit))
            st.caption(health.DEFINITIONS[k])
    total = sum(proposed.values())
    errors = health.validate_weights(proposed)
    if errors:
        st.error(f"Total: {total}% — " + " ".join(errors))
    else:
        st.success(f"Total: {total}% ✓")

    st.markdown("**Preview — how scores would change**")
    now = {r.customer_id: r for r in health.compute(eng, current)}
    prev = health.compute(eng, proposed) if not errors else []
    if prev:
        st.dataframe(pd.DataFrame([{
            "Customer": p.customer_name, "Current score": now[p.customer_id].score,
            "Current category": now[p.customer_id].category, "New score": p.score, "New category": p.category,
            "Change": round(p.score - now[p.customer_id].score, 1),
            "Category changes": "⚠ yes" if p.category != now[p.customer_id].category else ""} for p in prev]),
            hide_index=True, width="stretch")
    if can_edit:
        a, b = st.columns([1, 1])
        if a.button("Save weights & recalculate", type="primary", disabled=bool(errors) or proposed == current):
            if ctx.run_safely(health.save_weights, eng, proposed, ctx.user_email(), success="Weights saved — health recalculated"):
                st.rerun()
        if b.button("Restore defaults (30/25/15/15/15)"):
            st.session_state["w_reset"] = True
            st.rerun()
    else:
        ui.require_edit()
    hist = ctx.q("SELECT effective_from, adoption, usage_trend, support, engagement, sentiment, changed_by "
                 "FROM health_weights ORDER BY weights_id DESC")
    with st.expander("Weight history"):
        st.dataframe(hist, hide_index=True, width="stretch")

# ============================================================== AI
with tabs[1]:
    st.markdown(f"- Provider: **Groq** (Meta Llama) · model: `{config.groq_model()}` (set `GROQ_MODEL` in `.env`)\n"
                f"- API key: **{'configured' if ai.available() else 'not configured — template fallbacks in use'}**")
    if st.button("Test connection", disabled=not ai.available()):
        with st.spinner("Calling Groq…"):
            ok, msg = ai.test_connection()
        (st.success if ok else st.error)(msg)
    st.markdown("**Guardrails**")
    st.markdown("- Only structured, synthetic facts for the relevant account are sent; a *Data used* expander shows them.\n"
                "- The system prompt forbids inventing figures and requires missing data to be flagged.\n"
                "- Every output is labelled *AI draft — review before use*; nothing is saved without clicking Save.\n"
                "- AI-suggested root causes are always saved as *Hypothesis*.\n"
                "- Ask the portfolio only runs validated, read-only SELECTs over allow-listed views.\n"
                "- Low temperature (0.2), 25 s timeout, 2 retries, in-process response cache.")
    with st.expander("System prompt"):
        st.code(ai.SYSTEM_PROMPT, language="text")

# ============================================================== demo data
with tabs[2]:
    meta = ctx.q("SELECT key, value FROM app_config")
    st.dataframe(meta, hide_index=True, width="stretch")
    mode = ctx.mode()
    if mode != "live":
        st.info(f"You are in **{demo_mode.MODES[mode]}**. Resetting here rebuilds only this sandbox from the baseline.")
        if st.button("Reset this scenario sandbox", icon=":material/restart_alt:"):
            demo_mode.reset_sandbox(mode)
            st.cache_data.clear()
            st.session_state["_toast"] = "Scenario sandbox reset"
            st.rerun()
    else:
        st.warning("Reset demonstration database rebuilds the baseline from the deterministic seed and replaces the live "
                   "workspace. All changes (tasks, opportunities, notes, weights…) are lost. Scenario sandboxes are also "
                   "reset.")
        confirm = st.checkbox("I understand — reset the demonstration database", key="reset_confirm",
                              disabled=not can_edit)
        if st.button("Reset demonstration database", type="primary", disabled=not confirm, icon=":material/restart_alt:"):
            with st.spinner("Rebuilding from seed…"):
                seed.reset_live()
            st.cache_data.clear()
            st.session_state.pop("reset_confirm", None)
            st.session_state["_toast"] = "Demonstration database reset"
            st.rerun()

# ============================================================== audit
with tabs[3]:
    au = ctx.q("""SELECT a.ts, a.user_email, a.action, a.entity, a.entity_id, COALESCE(c.name, cp.name) AS account,
                  a.summary, a.changes_json FROM audit_log a LEFT JOIN customers c ON c.customer_id = a.customer_id
                  LEFT JOIN counterparties cp ON cp.counterparty_id = a.counterparty_id ORDER BY a.audit_id DESC""")
    a, b = st.columns(2)
    ent = a.multiselect("Entity", sorted(au["entity"].unique()), key="au_ent")
    usr = b.multiselect("User", sorted(au["user_email"].unique()), key="au_usr")
    if ent:
        au = au[au["entity"].isin(ent)]
    if usr:
        au = au[au["user_email"].isin(usr)]
    st.dataframe(au.rename(columns={"ts": "When", "user_email": "Who", "changes_json": "Old → new"}), hide_index=True,
                 width="stretch")
    st.download_button("Export audit log (CSV)", au.to_csv(index=False).encode(), "audit_log.csv", "text/csv")

# ============================================================== data quality
with tabs[4]:
    as_of = ctx.as_of()
    checks = {
        "Customers with no meeting sentiment in the last 90 days": db.render_sql(eng, """
            SELECT c.name AS account FROM customers c WHERE c.status = 'Active' AND NOT EXISTS (
              SELECT 1 FROM activities a WHERE a.customer_id = c.customer_id AND a.activity_type = 'Meeting'
              AND a.sentiment IS NOT NULL AND a.activity_date > {{ADD_DAYS({{AS_OF}}, -90)}})"""),
        "Stale contact — no meaningful contact for more than 45 days": db.render_sql(eng, """
            SELECT customer_name AS account, last_contact_date FROM v_customer_kpis
            WHERE last_contact_date IS NULL OR last_contact_date < {{ADD_DAYS({{AS_OF}}, -45)}}
            UNION ALL
            SELECT counterparty_name, last_contact_date FROM v_counterparty_summary
            WHERE last_contact_date IS NULL OR last_contact_date < {{ADD_DAYS({{AS_OF}}, -45)}}"""),
        "Accounts without an owner": """SELECT name AS account FROM customers WHERE owner_id IS NULL
            UNION ALL SELECT name FROM counterparties WHERE owner_id IS NULL""",
        "Open opportunities without a next action": """SELECT customer_name AS account, description FROM v_pipeline
            WHERE is_open = 1 AND (next_action IS NULL OR TRIM(next_action) = '')""",
        "Open opportunities with a close date in the past": db.render_sql(eng, """SELECT customer_name AS account,
            description, expected_close_date FROM v_pipeline WHERE is_open = 1 AND expected_close_date < {{AS_OF}}"""),
        "Customers with a partial health score": """SELECT customer_name AS account, components_available
            FROM v_customer_kpis WHERE components_available < 5""",
    }
    for title, sql in checks.items():
        res = ctx.q(sql)
        icon = "✅" if res.empty else "⚠️"
        with st.expander(f"{icon} {title} — {len(res)}", expanded=not res.empty):
            if res.empty:
                st.caption("No issues found.")
            else:
                st.dataframe(res, hide_index=True, width="stretch")
            ui.show_sql(sql)
    st.caption(f"Checked as of {fmt.fdate(as_of)}.")
