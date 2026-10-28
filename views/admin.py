"""Admin: register students from a class list, set up each cohort's subjects, and share
course notes with a cohort (every student in it sees them on sign-in)."""

from html import escape

import pandas as pd
import streamlit as st

from core import auth, db, ingest
from core.documents import SUPPORTED_TYPES, DocumentError
from ui.shell import cohort_label, load_models, require_admin
from ui.styles import badge, callout, card, html, icon, page_header, row, section

admin_id = require_admin()

page_header("Admin", "Register students, set up each department's subjects, and share course notes with them.")

CLASS_LIST_COLUMNS = ["hall_ticket", "name", "department", "year"]
SAMPLE_CSV = (
    "hall_ticket,name,department,year\n"
    "22B81A0501,Ananya Rao,CSE,3\n"
    "22B81A0502,Rahul Varma,CSE,3\n"
    "22B81A0401,Sneha Reddy,ECE,3\n"
)
# Numbered units, plus supporting material that belongs to no single unit.
UNITS = [f"Unit {i}" for i in range(1, 7)] + ["Lab programs", "Viva questions", "Supplementary"]

cohorts = db.list_cohorts()
labels = {c["id"]: cohort_label(c["id"]) for c in cohorts}


def read_class_list(file) -> pd.DataFrame:
    """The uploaded CSV with normalised column names ("Hall Ticket" -> hall_ticket)."""
    frame = pd.read_csv(file, dtype=str).fillna("")
    frame.columns = [c.strip().lower().replace(" ", "_") for c in frame.columns]
    return frame


students_tab, notes_tab = st.tabs(["Students & cohorts", "Course notes"])

# ---------------------------------------------------------------- students
with students_tab:
    left, right = st.columns([1.3, 1], gap="large")
    with left, card("class_list"):
        section("Import a class list", "A CSV with the columns hall_ticket, name, department and year. "
                "Re-importing updates names and cohorts; passwords and history are kept.")
        st.download_button("Download a sample CSV", SAMPLE_CSV, "class_list_sample.csv", "text/csv",
                           icon=":material/download:")
        # A new key after each import empties the uploader, so the same file isn't imported twice.
        file = st.file_uploader("Class list (CSV)", type=["csv"],
                                key=f"class_list_file_{st.session_state.get('imports', 0)}")
        if file is not None:
            try:
                frame = read_class_list(file)
            except Exception as exc:
                st.error(f"Couldn't read the CSV: {exc}")
                frame = None
            if frame is not None:
                missing = [c for c in CLASS_LIST_COLUMNS if c not in frame.columns]
                blank = frame[(frame.get("hall_ticket", "") == "") | (frame.get("department", "") == "")
                              | (frame.get("year", "") == "")] if not missing else []
                if missing:
                    st.error(f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(CLASS_LIST_COLUMNS)}.")
                elif len(blank):
                    st.error(f"{len(blank)} row(s) have no hall ticket, department or year. Fix them and upload again.")
                else:
                    st.dataframe(frame[CLASS_LIST_COLUMNS].head(8), hide_index=True, use_container_width=True)
                    st.caption(f"{len(frame)} students in this file.")
                    if st.button(f"Import {len(frame)} students", type="primary", icon=":material/group_add:"):
                        try:
                            added, updated = db.import_students(frame[CLASS_LIST_COLUMNS].to_dict("records"))
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state.admin_message = f"Imported: {added} new, {updated} updated."
                            st.session_state.imports = st.session_state.get("imports", 0) + 1
                            st.rerun()
        if message := st.session_state.pop("admin_message", None):
            st.success(message)

    with right, card("cohorts"):
        section("Cohorts", "A department and year. Students see their cohort's course notes.")
        if not cohorts:
            html('<div class="pa-empty">No cohorts yet. Import a class list to create them.</div>')
        html("".join(row(f"{icon('users')} {escape(labels[c['id']])}", badge(f"{c['students']} student{'s' if c['students'] != 1 else ''}", "blue"))
                     for c in cohorts))

    if cohorts:
        with card("students"):
            section("Students")
            cohort_id = st.selectbox("Cohort", list(labels), format_func=labels.get, key="students_cohort")
            students = db.list_students(cohort_id)
            st.dataframe(
                pd.DataFrame({
                    "Hall ticket": [s["username"] for s in students],
                    "Name": [s["full_name"] or "" for s in students],
                    "Status": ["Signed up" if s["has_password"] else "Code issued" if s["has_code"]
                               else "Needs a sign-up code" for s in students],
                }),
                hide_index=True, use_container_width=True,
            )
            # New codes are shown once (only their hashes are stored), until the admin dismisses them.
            issued = st.session_state.get("issued_codes")
            if issued:
                callout("Hand each student their code now: codes can't be shown again. "
                        "Each one works once, to set that student's first password.", "warning", "key",
                        bold="Sign-up codes.")
                table = pd.DataFrame(issued, columns=["Hall ticket", "Name", "Sign-up code"])
                st.dataframe(table, hide_index=True, use_container_width=True)
                c1, c2 = st.columns(2)
                c1.download_button("Download codes (CSV)", table.to_csv(index=False), "signup_codes.csv",
                                   "text/csv", icon=":material/download:", use_container_width=True)
                if c2.button("I've handed them out", icon=":material/check:", use_container_width=True):
                    del st.session_state.issued_codes
                    st.rerun()
            elif any(not s["has_password"] for s in students):
                if st.button("Create sign-up codes for students without a password", type="primary",
                             icon=":material/key:"):
                    st.session_state.issued_codes = auth.issue_codes_for_cohort(cohort_id)
                    st.rerun()
            with_password = {s["id"]: s for s in students if s["has_password"]}
            if with_password and not issued:
                c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
                who = c1.selectbox("Forgot their password?", list(with_password),
                                   format_func=lambda i: with_password[i]["username"])
                if c2.button("Reset password", icon=":material/lock_reset:", use_container_width=True):
                    s = with_password[who]
                    st.session_state.issued_codes = [(s["username"], s["full_name"] or "", auth.reset_password(who))]
                    st.rerun()

# ---------------------------------------------------------------- course notes
with notes_tab:
    if not cohorts:
        callout("Import a class list first: it creates the cohorts that notes are shared with.", "blue", "arrow")
        st.stop()
    cohort_id = st.selectbox("Cohort", list(labels), format_func=labels.get, key="notes_cohort")
    subjects = {s["id"]: s["name"] for s in db.list_subjects(cohort_id)}

    left, right = st.columns([1, 1.3], gap="large")
    with left, card("subjects"):
        section("Subjects", f"The subjects {labels[cohort_id]} studies this semester.")
        html("".join(badge(name, "violet") for name in subjects.values())
             or '<div class="pa-empty">No subjects yet.</div>')
        with st.form("add_subject", clear_on_submit=True, border=False):
            name = st.text_input("New subject", placeholder="e.g. Database Management Systems")
            if st.form_submit_button("Add subject", icon=":material/add:"):
                try:
                    db.add_subject(cohort_id, name)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()

    with right, card("share_notes"):
        section("Share notes", "PDF, Word or PowerPoint. Pages that are only images are read too. "
                "Uploading a file with the same name again updates it.")
        if not subjects:
            callout("Add a subject first.", "blue", "info")
        else:
            with st.form("share", clear_on_submit=True, border=False):
                c1, c2 = st.columns(2)
                subject_id = c1.selectbox("Subject", list(subjects), format_func=subjects.get)
                unit = c2.selectbox("Unit", UNITS)
                files = st.file_uploader("Course notes", type=list(SUPPORTED_TYPES), accept_multiple_files=True)
                submitted = st.form_submit_button("Share with cohort", type="primary", icon=":material/upload:",
                                                  use_container_width=True)
            if submitted:
                if not files:
                    st.error("Choose at least one file first.")
                else:
                    load_models()
                    messages = []
                    progress = st.progress(0.0)
                    for i, f in enumerate(files):
                        progress.progress(i / len(files), text=f"Processing {f.name}...")
                        try:
                            result = ingest.ingest(admin_id, f.name, f.getvalue(), cohort_id=cohort_id,
                                                   subject_id=subject_id, unit=unit)
                        except DocumentError as exc:
                            messages.append(("error", str(exc)))
                            continue
                        except Exception as exc:
                            messages.append(("error", f"{f.name}: processing failed ({exc})"))
                            continue
                        read = f", {result.image_pages_read} image pages read" if result.image_pages_read else ""
                        messages.append(("success", f"{f.name}: {result.chunks} chunks, {len(result.topics)} topics{read}"))
                        if result.warning:
                            messages.append(("warning", f"{f.name}: {result.warning}"))
                    progress.empty()
                    st.session_state.share_messages = messages
                    st.rerun()
        for level, message in st.session_state.pop("share_messages", []):
            getattr(st, level)(message)

    with card("cohort_docs"):
        documents = db.list_cohort_documents(cohort_id)
        section(f"Shared with {labels[cohort_id]} ({len(documents)})")
        if not documents:
            html('<div class="pa-empty">Nothing shared yet.</div>')
        for doc in documents:
            topics = db.list_topics(admin_id, doc["id"])
            html(
                f'<div class="pa-doc"><div class="pa-doc-icon">{icon("file", 18)}</div><div style="min-width:0">'
                f'<div class="pa-doc-name" title="{escape(doc["filename"])}">{escape(doc["filename"])}</div>'
                f'<div class="pa-doc-meta">{len(topics)} topics'
                + (f" · {doc['page_count']} pages" if doc["page_count"] else "") + "</div>"
                + (badge(doc["subject_name"], "violet") if doc["subject_name"] else "")
                + (badge(doc["unit"], "blue") if doc["unit"] else "") + "</div></div>"
            )
            with st.expander("Edit topics", icon=":material/edit:"):
                edited = st.text_area("Topics (one per line)", "\n".join(t["name"] for t in topics),
                                      height=180, key=f"admin_topics_{doc['id']}")
                c1, c2 = st.columns(2)
                if c1.button("Save topics", key=f"admin_save_{doc['id']}", use_container_width=True):
                    db.set_topics(admin_id, doc["id"], edited.splitlines())
                    st.toast("Topics saved.")
                    st.rerun()
                with c2.popover("Delete", icon=":material/delete:", use_container_width=True):
                    st.caption(f"Remove **{doc['filename']}** for every student in {labels[cohort_id]}? "
                               "Their quiz history on its topics loses its link.")
                    if st.button("Yes, delete", key=f"admin_del_{doc['id']}", type="primary"):
                        ingest.remove(admin_id, doc["id"])
                        st.toast(f"Deleted {doc['filename']}.")
                        st.rerun()
