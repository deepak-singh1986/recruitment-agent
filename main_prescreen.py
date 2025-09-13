# =========================
# main_prescreen.py
# =========================
import os
import pandas as pd
from pdf_utils import read_pdf
from llama_api import llm
from call_control import start_call

JD_FILE = "jd/ml_engineer.pdf"
CANDIDATE_CSV = "candidates.csv"  # columns: name,phone,resume_path

def prescreen_candidate(resume_text: str, jd_text: str) -> bool:
    prompt = f"""
JD:\n{jd_text}\n\nResume:\n{resume_text}\n\nAnswer strictly Yes or No: Should we shortlist this candidate based on JD fit? Add one short reason.
"""
    out = llm(prompt)
    return out.lower().startswith("yes")

def run():
    jd_text = read_pdf(JD_FILE) if os.path.exists(JD_FILE) else ""
    df = pd.read_csv(CANDIDATE_CSV)
    for _, row in df.iterrows():
        resume_text = read_pdf(row["resume_path"]) if os.path.exists(row["resume_path"]) else ""
        if prescreen_candidate(resume_text, jd_text):
            print(f"Shortlisted: {row['name']} → calling {row['phone']}")
            start_call(row["phone"])
        else:
            print(f"Not shortlisted: {row['name']}")

if __name__ == "__main__":
    run()
