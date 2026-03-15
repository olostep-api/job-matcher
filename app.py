from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from models.job import Job
from settings import RESUME_PATH
from src.job_matcher.constants import JOBS_PATH, UPLOADS_DIR
from src.job_matcher.service import run_job_matcher


def _save_uploaded_resume(uploaded_file, uploads_dir: Path) -> Path:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target = uploads_dir / uploaded_file.name
    target.write_bytes(uploaded_file.getbuffer())
    return target


def _job_to_output(job: Job) -> dict:
    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description,
        "hiring_probability": round(job.hiring_probability or 0.0, 4),
        "job_url": job.job_url,
        "match_reason": job.match_reason,
    }


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Job Matcher", page_icon=":briefcase:", layout="wide")
    st.markdown(
        """
        <style>
          :root {
            --bg: #f7f9fc;
            --surface: #ffffff;
            --primary: #0f4c81;
            --primary-soft: #e9f1f8;
            --text: #1f2937;
            --muted: #6b7280;
            --border: #dbe4ef;
          }
          .stApp {
            background: var(--bg);
            color: var(--text);
          }
          [data-testid="stSidebar"] {
            background: var(--surface);
            border-right: 1px solid var(--border);
          }
          h1, h2, h3 {
            color: var(--primary);
          }
          .stAlert {
            border-radius: 10px;
          }
          .stDataFrame, [data-testid="stExpander"] {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
          }
          .stButton button {
            background: var(--primary);
            color: #ffffff;
            border: 1px solid var(--primary);
            border-radius: 8px;
          }
          .stButton button:hover {
            background: #0b3a62;
            border-color: #0b3a62;
          }
          .stDownloadButton button {
            background: var(--primary-soft);
            color: var(--primary);
            border: 1px solid var(--border);
            border-radius: 8px;
          }
          .stCaption, .stMarkdown p {
            color: var(--muted);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Job Matcher")
    st.caption("Read resume, search jobs, scrape descriptions, and rank matches.")

    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    olostep_api_key = os.getenv("OLOSTEP_API_KEY", "").strip()
    if not olostep_api_key:
        st.error("Missing OLOSTEP_API_KEY in .env")
        st.stop()

    st.sidebar.header("Inputs")
    uploaded = st.sidebar.file_uploader("Upload resume (.pdf, .md)", type=["pdf", "md"])
    resume_path_input = st.sidebar.text_input(
        "Resume path (fallback)",
        value=str(RESUME_PATH),
        help="Used only when no file is uploaded.",
    )
    run_clicked = st.sidebar.button("Run Job Matcher", type="primary", use_container_width=True)

    if not run_clicked:
        st.info("Upload a resume or confirm the resume path in the sidebar, then run the matcher.")
        return

    try:
        if uploaded is not None:
            resume_path = _save_uploaded_resume(uploaded, uploads_dir=UPLOADS_DIR)
        else:
            resume_path = Path(resume_path_input).expanduser().resolve()
            if not resume_path.exists():
                st.error(f"Resume file not found: {resume_path}")
                return

        with st.spinner("Running job matcher..."):
            jobs = run_job_matcher(
                resume_path=resume_path,
                jobs_path=JOBS_PATH,
                olostep_api_key=olostep_api_key,
            )
    except Exception as exc:  # noqa: BLE001
        st.exception(exc)
        return

    output = [_job_to_output(job) for job in jobs]
    if not output:
        st.warning("No jobs found.")
        return

    st.success(f"Found {len(output)} jobs.")
    metric_col_1, metric_col_2 = st.columns(2)
    metric_col_1.metric("Total Jobs", len(output))
    metric_col_2.metric("Top Score", f"{max(row['hiring_probability'] for row in output):.2f}")

    summary_rows = [
        {
            "title": row["title"],
            "company": row["company"],
            "location": row["location"],
            "hiring_probability": row["hiring_probability"],
            "job_url": row["job_url"],
        }
        for row in output
    ]
    st.subheader("Top Matches")
    st.dataframe(summary_rows, use_container_width=True)

    st.subheader("Job Details")
    for idx, row in enumerate(output, start=1):
        with st.expander(f"{idx}. {row['title']} - {row['company']} ({row['hiring_probability']:.2f})"):
            st.write(f"Location: {row['location']}")
            st.write(f"URL: {row['job_url']}")
            st.write("Description:")
            st.code(row["description"] or "", language="markdown")
            if row["match_reason"]:
                st.write("Match reasons:")
                for reason in row["match_reason"]:
                    st.write(f"- {reason}")

    st.download_button(
        label="Download Results JSON",
        data=json.dumps(output, indent=2),
        file_name="top_jobs.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
