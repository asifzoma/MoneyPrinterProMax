"""Simple local dashboard for the daily video pipeline.

Run it with:
    streamlit run ui.py

Opens in your browser at http://localhost:8501 -- everything happens on
your own machine, nothing is sent anywhere except the YouTube upload you
explicitly trigger.
"""

import subprocess
import sys
from pathlib import Path

import streamlit as st

import tracker
from config import LOGS_DIR, YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_TOKEN_FILE

st.set_page_config(page_title="Daily Video Pipeline", page_icon="🎬", layout="wide")
st.title("🎬 Daily Video Pipeline")

# --- Status row -------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    authorized = YOUTUBE_TOKEN_FILE.exists()
    st.metric("YouTube auth", "✅ Connected" if authorized else "❌ Not connected")
with col2:
    has_client_secret = YOUTUBE_CLIENT_SECRETS_FILE.exists()
    st.metric("Client secret file", "✅ Found" if has_client_secret else "❌ Missing")
with col3:
    rows = tracker.read_rows()
    pending_count = sum(1 for r in rows if r.get("Status") == "Pending")
    st.metric("Pending uploads", pending_count)

st.divider()

# --- Actions ------------------------------------------------------------
st.subheader("Actions")
a1, a2, a3 = st.columns(3)

with a1:
    if st.button("▶️ Generate today's video", use_container_width=True):
        with st.spinner("Generating video... this can take several minutes."):
            try:
                from generate_video import generate_daily_video
                result = generate_daily_video()
                st.success(f"Done: {result['title']}")
                st.write(result["video_path"])
            except Exception as err:
                st.error(f"Generation failed: {err}")

with a2:
    if st.button("⬆️ Upload next pending video", use_container_width=True, disabled=not authorized):
        with st.spinner("Uploading to YouTube..."):
            try:
                import upload_youtube
                result = upload_youtube.upload_next_pending()
                if result["status"] == "uploaded":
                    st.success(f"Uploaded: {result['youtube_url']}")
                else:
                    st.warning(f"Not uploaded: {result}")
            except Exception as err:
                st.error(f"Upload failed: {err}")

with a3:
    if st.button("🔑 Connect YouTube account", use_container_width=True, disabled=not has_client_secret):
        with st.spinner("Opening browser for Google sign-in..."):
            try:
                import upload_youtube
                upload_youtube.get_authenticated_service()
                st.success("Connected! Refresh this page.")
            except Exception as err:
                st.error(f"Authorization failed: {err}")

if not has_client_secret:
    st.info(
        f"To connect YouTube, put your downloaded OAuth client JSON at "
        f"`{YOUTUBE_CLIENT_SECRETS_FILE}` first (see upload_youtube.py's top comment "
        f"for how to create one in Google Cloud Console)."
    )

st.divider()

# --- Tracker table --------------------------------------------------------
st.subheader("Video history")
if rows:
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.write("No videos generated yet.")

st.divider()

# --- Recent log tail --------------------------------------------------------
st.subheader("Recent log output")
log_choice = st.selectbox("Log file", ["run_daily.log", "upload.log"])
log_path = LOGS_DIR / log_choice
if log_path.exists():
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    st.code("\n".join(lines[-40:]) or "(empty)", language="text")
else:
    st.write("No log file yet.")
