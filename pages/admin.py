import streamlit as st
import pandas as pd
import json
import os
import sqlite3

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "sahayak.db")
CACHE_DB_PATH = os.path.join(BASE_DIR, "semantic_cache.db")
QUIZ_BANK_PATH = os.path.join(BASE_DIR, "quiz_bank.json")
USER_PROFILES_DIR = os.path.join(BASE_DIR, "user_profiles")

st.set_page_config(page_title="AIEdS - Admin Panel", layout="wide")

# --- 🛡️ SECTION 1: ACCESS CONTROL ---
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from session_guard import require_role, logout
from theme import inject_theme_polish
# subject_catalog.build_subject_manuals() is the SAME function student.py's
# dashboard uses (via get_ready_subjects) to derive a subject's clean display
# name from its FAISS stem / _meta.json. Previously this page independently
# title-cased the raw FAISS filename to build "Assign to Subject", which
# produced a *different* string than subject_catalog would derive for the
# same book whenever a _meta.json's "subject" field didn't literally prefix
# the FAISS stem. That mismatch was silent: the CSV upload succeeded and
# quiz_bank.json got the questions, but has_qb_coverage()'s prefix match
# against build_subject_manuals()'s subject never fired, so the subject
# never appeared for students even though "everything was uploaded". Sourcing
# the dropdown from build_subject_manuals() directly guarantees the subject
# string written into quiz_bank.json is byte-identical to the one
# get_ready_subjects() will later look for.
from subject_catalog import build_subject_manuals
require_role("admin")
inject_theme_polish()

# --- 🛡️ SECTION 2: MAIN ADMIN INTERFACE ---
st.title("🛡️ AIEdS Administrative Control")

tabs = st.tabs(["📝 Question Bank Manager", "💬 Feedback Analyzer", "📊 System Overview"])

# --- TAB 1: QUESTION BANK (UPDATED WITH SUBJECT DROPDOWN) ---
with tabs[0]:
    st.header("Upload Central Question Bank")

    # NEW FEATURE: Dynamic Subject Selection
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        assigned_term = st.selectbox("Assign to Term", [f"Term_{i}" for i in range(1, 9)])

    # subject_manuals: {subject_display: [(manual_display, stem), ...]} — the
    # exact same shape/derivation student.py's dashboard consumes. A subject
    # can have multiple indexed books (manuals); the admin now picks the
    # subject first, then the specific book (manual) to attach the CSV's
    # subject_key to, mirroring the two-level Subject / Subject Manual
    # selectors on the student side.
    subject_manuals = build_subject_manuals(BASE_DIR, assigned_term)
    available_subjects = sorted(subject_manuals.keys())

    with col_b:
        if available_subjects:
            assigned_subject_display = st.selectbox("Assign to Subject", available_subjects)
        else:
            st.warning("No subjects found in this term. Enter name manually:")
            assigned_subject_display = st.text_input("Manual Subject Name", "General")

    manual_options = subject_manuals.get(assigned_subject_display, [])
    manual_display_names = [m[0] for m in manual_options]

    with col_c:
        if manual_options:
            assigned_manual_display = st.selectbox("Assign to Manual (Book)", manual_display_names)
            assigned_subject_key = next(
                stem for disp, stem in manual_options if disp == assigned_manual_display
            )
        else:
            # No indexed book yet (or manual-entry fallback above) — fall
            # back to a slug of the typed subject name, same as before.
            assigned_manual_display = None
            assigned_subject_key = assigned_subject_display.lower().replace(" ", "_")

    st.info("""
    **CSV Requirements:** Headers must be: `question`, `opt1`, `opt2`, `opt3`, `opt4`, `correct_opt`, `di`
    *(The 'subject' will be assigned automatically based on your selection above)*
    """)

    uploaded_file = st.file_uploader(
        "Choose CSV Question Bank",
        type="csv",
        key=f"csv_uploader_{assigned_term}_{assigned_subject_key}"
    )

    if st.button("Process & Save Question Bank", use_container_width=True):
        if uploaded_file and assigned_subject_display:
            try:
                df = pd.read_csv(uploaded_file)
                # Load existing data to append, not overwrite
                current_data = []
                if os.path.exists(QUIZ_BANK_PATH):
                    with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
                        current_data = json.load(f)

                new_entries = 0
                for _, row in df.iterrows():
                    current_data.append({
                        "id": len(current_data) + 1,
                        "term": assigned_term,
                        "subject": assigned_subject_display,
                        "subject_key": assigned_subject_key,
                        "text": str(row['question']),
                        "options": [str(row['opt1']), str(row['opt2']), str(row['opt3']), str(row['opt4'])],
                        "answer": str(row['correct_opt']),
                        "di": float(row['di'])
                    })
                    new_entries += 1

                with open(QUIZ_BANK_PATH, "w", encoding="utf-8") as f:
                    json.dump(current_data, f, indent=4, ensure_ascii=False)
                manual_note = f" / manual '{assigned_manual_display}'" if assigned_manual_display else ""
                st.success(
                    f"✅ Successfully added {new_entries} questions under "
                    f"'{assigned_subject_display}'{manual_note} (key: {assigned_subject_key})!"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}. Check if CSV headers match exactly.")
        else:
            st.warning("Please upload a file and ensure a subject is selected.")

    st.divider()
    st.subheader("Current Question Inventory")
    if os.path.exists(QUIZ_BANK_PATH):
        with open(QUIZ_BANK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data:
            inventory_df = pd.DataFrame(data)
            # Add a filter to see questions by subject
            filter_sub = st.selectbox("Filter Inventory by Subject", ["All"] + list(inventory_df['subject'].unique()))
            if filter_sub != "All":
                inventory_df = inventory_df[inventory_df['subject'] == filter_sub]
            st.dataframe(inventory_df, use_container_width=True)

            # Quick visibility into whether each term's subjects are actually
            # "ready" (book + QB) from the student's point of view, without
            # leaving this page to run a diagnostic script.
            st.divider()
            st.subheader("Readiness Check (Book + Question Bank)")
            check_term = st.selectbox(
                "Check Term", [f"Term_{i}" for i in range(1, 9)],
                index=[f"Term_{i}" for i in range(1, 9)].index(assigned_term),
                key="readiness_term"
            )
            from subject_catalog import qb_subject_keys, has_qb_coverage
            _manuals = build_subject_manuals(BASE_DIR, check_term)
            _qb_keys = qb_subject_keys(BASE_DIR, check_term)
            if _manuals:
                rows = [
                    {"Subject": subj, "Ready for Students": "✅" if has_qb_coverage(_qb_keys, subj) else "❌ No QB"}
                    for subj in sorted(_manuals)
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption(f"No indexed books found for {check_term}.")

            if st.button("🗑️ Wipe Entire Question Bank"):
                os.remove(QUIZ_BANK_PATH)
                st.rerun()

# --- TAB 2: FEEDBACK ANALYZER (NEW) ---
with tabs[1]:
    st.header("Student Feedback & AI Performance")
    if os.path.exists(CACHE_DB_PATH):
        try:
            with sqlite3.connect(CACHE_DB_PATH) as conn:
                # Retrieve only queries that have received a thumbs up or down
                feedback_df = pd.read_sql_query("""
                    SELECT query, answer, feedback, comment 
                    FROM cache 
                    WHERE feedback != 0
                """, conn)

            if not feedback_df.empty:
                # Map numeric feedback to readable status
                feedback_df['Status'] = feedback_df['feedback'].apply(lambda x: "✅ Helpful" if x == 1 else "❌ Issue Reported")

                # Display metrics
                col1, col2 = st.columns(2)
                col1.metric("Total Thumbs Up", len(feedback_df[feedback_df['feedback'] == 1]))
                col2.metric("Total Thumbs Down", len(feedback_df[feedback_df['feedback'] == -1]))

                st.divider()
                st.write("**Detailed Logs:**")
                st.dataframe(feedback_df[['Status', 'query', 'answer', 'comment']], use_container_width=True)

                if st.button("Clear Feedback Logs (DANGER)"):
                    with sqlite3.connect(CACHE_DB_PATH) as conn:
                        conn.execute("UPDATE cache SET feedback = 0, comment = NULL")
                    st.success("Logs cleared.")
                    st.rerun()
            else:
                st.info("No feedback has been submitted by students yet.")
        except Exception as e:
            st.error(f"Error accessing feedback: {e}")
    else:
        st.warning("Semantic Cache DB not found. Ensure students have used the chat.")

# --- TAB 3: SYSTEM OVERVIEW ---
with tabs[2]:
    st.header("Database Overview")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            users_df = pd.read_sql_query("SELECT id, username, role, full_name FROM users", conn)
        st.write("**Registered Users:**")
        st.dataframe(users_df, use_container_width=True)
    except Exception as e:
        st.error(f"Could not load users: {e}")

    st.divider()
    if st.button("Logout Admin Session", use_container_width=True):
        logout("login.py")
        st.switch_page("login.py")

# Sidebar Status
with st.sidebar:
    st.success(f"Mode: Admin Access")
    st.write(f"Connected to: `{DB_PATH}`")
