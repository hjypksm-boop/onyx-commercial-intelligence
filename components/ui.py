"""Reusable presentational components: banner, KPI cards, badges, Show SQL, empty states, AI output."""
from __future__ import annotations

import html

import streamlit as st

from services import auth
from services import formatting as fmt
from services.config import DISCLAIMER


def banner() -> None:
    st.markdown(f'<div class="onyx-banner"><b>Demonstration environment</b> — '
                f'{html.escape(DISCLAIMER.split("— ", 1)[1])}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="muted" style="margin-top:-10px;margin-bottom:10px">{html.escape(subtitle)}</div>',
                    unsafe_allow_html=True)


def kpi_card(label: str, value: str, sub: str = "", tone: str = "teal", sql: str | None = None,
             help_text: str | None = None) -> None:
    st.markdown(f'<div class="kpi {tone}"><div class="label">{html.escape(label)}</div>'
                f'<div class="value">{html.escape(value)}</div><div class="sub">{html.escape(sub)}</div></div>',
                unsafe_allow_html=True)
    if sql:
        show_sql(sql, help_text)


def show_sql(sql: str, note: str | None = None, label: str = "Show SQL") -> None:
    with st.expander(label, icon=":material/code:"):
        if note:
            st.caption(note)
        st.code(sql.strip(), language="sql")


def health_badge(category: str | None, score=None, available: int | None = None) -> str:
    if not category:
        return '<span class="badge Missing">Missing data</span>'
    cls = category.replace(" ", "")
    s = f"{category}" + (f" · {float(score):.0f}" if score is not None else "")
    out = f'<span class="badge {cls}">{html.escape(s)}</span>'
    if available is not None and int(available) < 5:
        out += f' <span class="badge Missing">Partial score — {int(available)} of 5 components</span>'
    return out


def badge(text: str, kind: str = "Neutral") -> str:
    return f'<span class="badge {kind}">{html.escape(str(text))}</span>'


def html_block(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def empty_state(message: str, cta_label: str | None = None, page_key: str | None = None) -> None:
    st.info(message, icon=":material/info:")
    if cta_label and page_key:
        from components import context as ctx
        if st.button(cta_label, key=f"cta_{page_key}_{abs(hash(message))}"):
            ctx.goto(page_key)


def ai_output(result, key: str, height: int = 260) -> str:
    """Render an AI/template draft in an editable box with its label and a 'Data used' expander."""
    st.markdown(f'<div class="ai-label">{html.escape(result.label)}</div>', unsafe_allow_html=True)
    if result.error and not result.used_ai:
        st.caption(f"Reason: {result.error}")
    text = st.text_area("Draft (editable)", value=result.text, height=height, key=key, label_visibility="collapsed")
    with st.expander("Data used", icon=":material/dataset:"):
        st.caption("Only these structured, synthetic facts were sent to the model:")
        st.json(result.facts, expanded=False)
    return text


def require_edit() -> bool:
    """True if the current user may edit; otherwise shows a read-only notice."""
    from components import context as ctx
    if auth.can_edit(ctx.user()):
        return True
    st.caption(":material/lock: Read-only for the Commercial Director role.")
    return False


def money_col(label: str):
    return st.column_config.NumberColumn(label, format="£%,d")


def pct_col(label: str):
    return st.column_config.NumberColumn(label, format="%.1f%%")


def gbp(p) -> str:
    return fmt.gbp(p)
