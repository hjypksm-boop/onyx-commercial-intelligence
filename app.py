"""ONYX | Commercial Intelligence — entry point: auth gate, navigation, theme, demo mode."""
from __future__ import annotations

import logging

import streamlit as st

from components import context as ctx
from components import sidebar, theme, ui
from services import auth, config, db, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="ONYX | Commercial Intelligence", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")
theme.inject_css()


@st.cache_resource(show_spinner="Preparing demonstration database…")
def _bootstrap(url: str) -> bool:
    seed.ensure_ready()
    return True


_bootstrap(config.database_url())


def login() -> None:
    ui.banner()
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.markdown('<div class="onyx-wordmark" style="font-size:1.3rem;margin-top:6vh">ONYX '
                    '<span>| Commercial Intelligence</span></div>', unsafe_allow_html=True)
        st.caption("Customer success & revenue operations — internal demonstration")
        with st.form("login"):
            email = st.text_input("Email", value="cs.exec@demo.local")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", width="stretch")
        if ok:
            user = auth.authenticate(db.get_engine(config.database_url()), email, pw)
            if user:
                st.session_state["user"] = user
                st.rerun()
            st.error("Invalid email or password.")
        with st.container(border=True):
            st.markdown("**Demo credentials**")
            for e, p, role in auth.DEMO_CREDENTIALS:
                st.markdown(f"`{e}` / `{p}`  \n<span class='muted'>{role}</span>", unsafe_allow_html=True)


if not st.session_state.get("user"):
    login()
    st.stop()

pages = [st.Page(path, title=title, icon=icon, default=(key == "overview"), url_path=key)
         for key, (path, title, icon) in ctx.PAGES.items()]
nav = st.navigation(pages, position="sidebar")
sidebar.render()
ui.banner()
ctx.show_pending_toast()
sidebar.narration()
nav.run()
