# ✅ Realtime Hinglish AI Recruitment Agent (Cleaned Full Repo)
# Repository: ai_recruitment_agent_realtime_hinglish

# =========================
# requirements.txt
# =========================
fastapi
uvicorn
python-dotenv
twilio
requests
PyPDF2
pandas
spacy
vosk
numpy

# After install: python -m spacy download en_core_web_sm


# =========================
# .env  (create in repo root)
# =========================
# TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# TWILIO_AUTH_TOKEN=your_auth_token
# TWILIO_PHONE=+1xxxxxxxxxx
# PUBLIC_SERVER_URL=https://your-public-hostname.example.com
# OLLAMA_URL=http://localhost:11434
# OLLAMA_MODEL=llama-3.1-8b
# VOSK_MODEL_PATH=models/vosk-model-small-en-in-0.4


# =========================
# pdf_utils.py
# =========================
import PyPDF2

def read_pdf(file_path: str) -> str:
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            t = page.extract_text() or ""
            text += t + "\n"
    return text.strip()


# =========================
# llama_api.py  (Ollama local model)
# =========================
import os
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama-3.1-8b")


def llm(prompt: str, temperature: float = 0.2, max_tokens: int = 512) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120, stream=False)
    r.raise_for_status()
    data = r.json()
    return data.get("response", "").strip()


# =========================
# resume_parser.py
# =========================
import spacy
import re

_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp

SKILL_HINTS = [
    "python","pandas","numpy","scikit","sklearn","pytorch","tensorflow","ml","machine learning",
    "java","spring","sql","spark","aws","gcp","azure","docker","kubernetes","nlp","llm"
]

def parse_resume(resume_text: str) -> dict:
    nlp = _get_nlp()
    doc = nlp(resume_text)
    skills = sorted({k for k in SKILL_HINTS if k in resume_text.lower()})
    years = [int(x) for x in re.findall(r"(\d+)\s+year", resume_text.lower())]
    total_exp = max(years) if years else None
    name = None
    for ent in doc.ents:
        if ent.label_ == "PERSON" and 2 <= len(ent.text.split()) <= 4:
            name = ent.text
            break
    return {"name": name, "skills": skills, "total_experience_years": total_exp}


# =========================
# streaming_stt.py
# =========================
import base64
import numpy as np
from vosk import Model, KaldiRecognizer
import json as _json
import os

VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "models/vosk-model-small-en-in-0.4")
_vosk_model = None


def _get_model():
    global _vosk_model
    if _vosk_model is None:
        _vosk_model = Model(VOSK_MODEL_PATH)
    return _vosk_model


def mulaw_to_pcm16(u: np.ndarray) -> np.ndarray:
    u = u.astype(np.int16)
    u = ~u
    sign = (u & 0x80)
    exponent = (u & 0x70) >> 4
    mantissa = u & 0x0F
    magnitude = ((mantissa << 4) + 0x08) << exponent
    sample = (magnitude - 0x84)
    sample = np.where(sign != 0, -sample, sample)
    return sample.astype(np.int16)


class StreamingSTT:
    def __init__(self, sample_rate=8000):
        self.model = _get_model()
        self.rec = KaldiRecognizer(self.model, sample_rate)

    def accept_twilio_media(self, media_payload_b64: str):
        raw = base64.b64decode(media_payload_b64)
        u = np.frombuffer(raw, dtype=np.uint8)
        pcm16 = mulaw_to_pcm16(u)
        self.rec.AcceptWaveform(pcm16.tobytes())

    def partial(self):
        try:
            res = _json.loads(self.rec.PartialResult())
            return res.get("partial")
        except Exception:
            return None

    def final(self):
        res = _json.loads(self.rec.Result())
        return res.get("text")


# =========================
# interview_orchestrator.py
# =========================
from typing import List, Optional
from llama_api import llm
from resume_parser import parse_resume

INTRO = (
    "Namaste! Main HR AI agent bol raha/rahi hoon. Ab hum ek short interview karenge. "
    "Please boliye clearly. Ready ho?"
)

class InterviewSession:
    def __init__(self, jd_text: str, resume_text: str, num_questions: int = 5):
        self.jd_text = jd_text
        self.resume_text = resume_text
        self.profile = parse_resume(resume_text)
        self.num_questions = num_questions
        self.questions: List[str] = []
        self.answers: List[str] = []
        self.stage = "intro"
        self.q_index = 0
        self._generate_questions()

    def _generate_questions(self):
        prompt = f"""
You are a recruiter. Create {self.num_questions} short interview questions in Hinglish (mix Hindi+English),
focused on this JD and candidate profile.

JD:
{self.jd_text}

Candidate profile (parsed):
{self.profile}

Return numbered questions only, one per line.
"""
        out = llm(prompt)
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        qs = []
        for l in lines:
            if l[0].isdigit():
                l = l.split(".", 1)[-1].strip()
            qs.append(l)
        self.questions = qs[: self.num_questions]

    def next_agent_utterance(self) -> Optional[str]:
        if self.stage == "intro":
            self.stage = "ask"
            return INTRO
        if self.stage == "ask":
            if self.q_index < len(self.questions):
                return f"Question {self.q_index+1}: {self.questions[self.q_index]}"
            else:
                self.stage = "eval"
                return None
        if self.stage == "eval":
            eval_prompt = f"""
Evaluate the candidate based on their answers. Provide JSON with fields:
{{
  "scores": [{{"q": 1, "score": 1-5, "reason": "..."}}, ...],
  "overall": {{"decision": "SELECT" or "REJECT", "reason": "..."}}
}}
JD:\n{self.jd_text}\n\nQuestions:\n{self.questions}\n\nAnswers:\n{self.answers}
"""
            out = llm(eval_prompt, temperature=0.1, max_tokens=600)
            self.stage = "done"
            return out
        return None

    def on_user_speech(self, transcript: str) -> Optional[str]:
        if self.stage == "ask":
            self.answers.append(transcript)
            self.q_index += 1
            if self.q_index < len(self.questions):
                return self.next_agent_utterance()
            else:
                return self.next_agent_utterance()
        return None


# =========================
# app.py
# =========================
import os
import json
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from twilio.rest import Client
from pdf_utils import read_pdf
from interview_orchestrator import InterviewSession
from streaming_stt import StreamingSTT

load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")
PUBLIC_SERVER_URL = os.getenv("PUBLIC_SERVER_URL")

app = FastAPI()
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

SESSIONS = {}

@app.post("/voice")
async def voice(request: Request):
    params = await request.form()
    call_sid = params.get("CallSid", "")
    jd_path = params.get("jd_path", "jd/ml_engineer.pdf")
    resume_path = params.get("resume_path", "candidates/sample.pdf")

    jd_text = read_pdf(jd_path) if os.path.exists(jd_path) else ""
    resume_text = read_pdf(resume_path) if os.path.exists(resume_path) else ""

    SESSIONS[call_sid] = {
        "session": InterviewSession(jd_text, resume_text),
        "stt": StreamingSTT(sample_rate=8000)
    }

    twiml = f"""
<Response>
  <Connect>
    <Stream url="wss://{PUBLIC_SERVER_URL.replace('https://','').replace('http://','')}/media?CallSid={call_sid}"/>
  </Connect>
</Response>
""".strip()
    return PlainTextResponse(twiml, media_type="text/xml")

@app.websocket("/media")
async def media_stream(ws: WebSocket):
    await ws.accept()
    call_sid = ws.query_params.get("CallSid", "")
    sess = SESSIONS.get(call_sid)
    if not sess:
        await ws.close()
        return

    interview: InterviewSession = sess["session"]
    stt: StreamingSTT = sess["stt"]

    async def say(text: str):
        await ws.send_text(json.dumps({"event": "say", "text": text, "voice": "Polly.Aditi"}))

    intro = interview.next_agent_utterance()
    if intro:
        await say(intro)

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            ev = msg.get("event")

            if ev == "media":
                payload = msg.get("media", {}).get("payload")
                if payload:
                    stt.accept_twilio_media(payload)
                    final_txt = stt.final()
                    if final_txt:
                        nxt = interview.on_user_speech(final_txt)
                        if nxt:
                            await say(nxt)

            elif ev in ("stop", "close"):
                break

    except WebSocketDisconnect:
        pass
    finally:
        final_transcript = stt.final() or ""
        if final_transcript.strip():
            nxt = interview.on_user_speech(final_transcript)
            if nxt:
                try:
                    await say(nxt)
                except:
                    pass
        SESSIONS.pop(call_sid, None)


# =========================
# call_control.py
# =========================
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_PHONE")
PUBLIC_SERVER_URL = os.getenv("PUBLIC_SERVER_URL")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

def start_call(to_number: str):
    voice_url = f"https://{PUBLIC_SERVER_URL.replace('https://','').replace('http://','')}/voice"
    call = client.calls.create(
        to=to_number,
        from_=FROM_NUMBER,
        url=voice_url,
        method="POST",
    )
    print("Call SID:", call.sid)


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
