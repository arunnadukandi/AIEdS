"""
session_guard.py
Place this file alongside login.py (i.e. /home/ece/IEAS/login/session_guard.py)

Usage in every page:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from session_guard import require_role
    require_role("student")   # or "instructor" or "admin"
"""

import streamlit as st
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "sahayak.db")


def _validate_token(user_id: int, token: str) -> bool:
    """Check that the token in session state matches the DB record."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT token FROM session_tokens WHERE user_id=?",
                (user_id,)
            ).fetchone()
        return row is not None and row[0] == token
    except Exception:
        return False


def require_role(role: str):
    """
    Call at the very top of every page (after set_page_config).
    - Checks role matches
    - Checks session token is valid against DB
    - If either fails: clears session, shows error, stops page
    """
    uid   = st.session_state.get("user_id")
    token = st.session_state.get("session_token")
    r     = st.session_state.get("role")

    # Guard 1: basic session keys must exist
    if not uid or not token or r != role:
        st.session_state.clear()
        st.error("⚠️ Session expired or unauthorised. Please log in again.")
        if st.button("Go to Login"):
            st.switch_page("login.py")
        st.stop()

    # Guard 2: token must match DB — prevents back-button misuse
    if not _validate_token(uid, token):
        st.session_state.clear()
        st.error("⚠️ Your session is no longer valid. Please log in again.")
        if st.button("Go to Login"):
            st.switch_page("login.py")
        st.stop()


def logout(redirect: str = "login.py"):
    """
    Call from any logout button.
    Invalidates the DB token then clears session and redirects.
    """
    uid   = st.session_state.get("user_id")
    if uid:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "DELETE FROM session_tokens WHERE user_id=?", (uid,)
                )
                conn.commit()
        except Exception:
            pass
    st.session_state.clear()
    st.switch_page(redirect)
