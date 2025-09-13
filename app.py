import os
import time
import json
import glob
import threading
import asyncio


from fastapi import FastAPI, Request, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# Repo modules
from db import SessionLocal, init_db, Candidate, Job
from pdf_utils import read_pdf
from resume_parser import parse_resume
from embedding_store import build_index_from_resumes, search_jd
from call_control import start_call_for_candidate
from interview_orchestrator import InterviewSession  # updated version (candidate, jd_file)





# Use global config for question generation mode
from config import get_use_model_questions

from streaming_stt import StreamingSTT
from tts_stream import synthesize_and_stream

# (NEW) Twilio status callback router
from twilio_status_router import router as twilio_status_router


init_db()

app = FastAPI(title="AI Recruitment Agent")


# Add root route to redirect to dashboard
from fastapi.responses import RedirectResponse
@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

# ---------------------------
# List available JD files
# ---------------------------
@app.get('/api/jd_files')
async def list_jd_files():
    files = [f for f in os.listdir('jd') if f.lower().endswith('.pdf')]
    return {'files': files}
# app.py — Unified app with uploads/shortlist/reports + Twilio streaming interview (10Q) + DB updates + Status router

# Attach status router
app.include_router(twilio_status_router)

# Required folders
os.makedirs('jd', exist_ok=True)
os.makedirs('candidates', exist_ok=True)
os.makedirs('results/interview_reports', exist_ok=True)

# Serve report files
app.mount('/reports/files', StaticFiles(directory='results/interview_reports'), name='reports_files')

# Dashboard live updates manager
class ConnectionManager:
    def __init__(self):
        self.active = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
    async def broadcast(self, msg: dict):
        for c in list(self.active):
            try:
                await c.send_json(msg)
            except Exception:
                pass

manager = ConnectionManager()

# Twilio stream sessions: CallSid -> { session, stt, streamSid, candidate_id, q_index }
SESSIONS: dict[str, dict] = {}


# ---------------------------
# Upload endpoints
# ---------------------------
@app.post('/upload/jd')
async def upload_jd(file: UploadFile = File(...)):
    path = os.path.join('jd', file.filename)
    with open(path, 'wb') as f:
        f.write(await file.read())
    db = SessionLocal()
    db.add(Job(title=file.filename, jd_path=path))
    db.commit()
    db.close()
    return {'status': 'ok', 'path': path}

@app.post('/upload/resume')
async def upload_resume(file: UploadFile = File(...)):
    path = os.path.join('candidates', file.filename)
    with open(path, 'wb') as f:
        f.write(await file.read())
    txt = read_pdf(path)
    profile = parse_resume(txt)
    db = SessionLocal()
    cand = Candidate(
        name=profile.get('name'),
        resume_path=path,
        phone=profile.get('phone'),
        skills=profile.get('skills'),
        experience_years=profile.get('total_experience_years'),
        shortlist_decision='PENDING',
        call_status='PENDING'
    )
    db.add(cand)
    db.commit()
    db.close()
    return {'status': 'ok', 'profile': profile}


# ---------------------------
# Shortlisting (FAISS)
# ---------------------------

@app.post('/shortlist')
async def do_shortlist(jd_filename: str = Form(...), top_k: int = Form(5)):
    jd_path = os.path.join('jd', jd_filename)
    if not os.path.exists(jd_path):
        return {'status': 'error', 'message': 'JD not found'}
    try:
        build_index_from_resumes('candidates')
        results = search_jd(jd_path, top_k=top_k)
    except RuntimeError as e:
        return {'status': 'error', 'message': str(e)}
    db = SessionLocal()
    allc = db.query(Candidate).all()
    for c in allc:
        c.shortlist_decision = 'REJECT'
    db.commit()
    for r in results:
        fp = r['file']
        cand = db.query(Candidate).filter(Candidate.resume_path == fp).first()
        if cand:
            cand.shortlist_decision = 'SELECT'
            cand.call_status = 'PENDING'
    db.commit()
    db.close()
    await manager.broadcast({'type': 'shortlist_update'})
    return {'status': 'ok', 'shortlisted': [r['file'] for r in results]}


# ---------------------------
# Bulk start calls (uses call_control.start_call_for_candidate)
# ---------------------------
@app.post('/start-calls')
async def start_calls():
    db = SessionLocal()
    selected = db.query(Candidate).filter(Candidate.shortlist_decision == 'SELECT').all()
    db.close()


    def worker():
        from interview_orchestrator import InterviewSession
        for cand in selected:
            if not cand.phone:
                continue
            # Generate and cache questions before call
            try:
                job = None
                db = SessionLocal()
                try:
                    from db import Job
                    job = db.query(Job).order_by(Job.id.desc()).first()
                finally:
                    db.close()
                jd_file = job.jd_path if job else None
                # Pass the mode to InterviewSession if needed
                session = InterviewSession(cand, jd_file=jd_file, use_model_questions=get_use_model_questions())
                questions = session.generate_questions()
                print(f"[QUESTIONS] Candidate {cand.id} ({cand.name}):")
                for idx, q in enumerate(questions, 1):
                    print(f"  Q{idx}: {q}")
            except Exception as e:
                print(f"[ERROR] Failed to generate questions for candidate {cand.id}: {e}")
                continue
            # mark IN_CALL
            db = SessionLocal()
            c_local = db.query(Candidate).get(cand.id)
            c_local.call_status = 'IN_CALL'
            db.commit()
            db.close()
            asyncio.run(manager.broadcast({'type': 'call_update', 'id': cand.id, 'status': 'IN_CALL'}))
            try:
                # call URL points to /voice?candidate_id=...
                print(f"[Twilio] Attempting to start call for candidate {cand.id} ({cand.phone})")
                _sid = start_call_for_candidate(cand.phone, cand.id)
                print(f"[Twilio] Call started, SID: {_sid}")
                # Store generated questions in SESSIONS for this call_sid
                if _sid:
                    SESSIONS[_sid] = {
                        "answers": [],
                        "questions": questions,
                        "candidate_id": cand.id,
                        "jd_file": jd_file,
                        "precheck_done": False
                    }
            except Exception as e:
                print(f"[Twilio] Call failed for candidate {cand.id}: {e}")
                db2 = SessionLocal()
                c2 = db2.query(Candidate).get(cand.id)
                c2.call_status = 'FAILED'
                db2.commit()
                db2.close()
                asyncio.run(manager.broadcast({'type': 'call_update', 'id': cand.id, 'status': 'FAILED'}))
                continue

    threading.Thread(target=worker, daemon=True).start()
    return {'status': 'started'}


# ---------------------------
# Single start interview (per-candidate)
# ---------------------------
@app.post('/start-interview')
def start_interview(candidate_id: int):
    db = SessionLocal()
    cand = db.query(Candidate).get(candidate_id)
    db.close()
    if not cand:
        return {'status': 'error', 'message': 'candidate not found'}
    if not cand.phone:
        return {'status': 'error', 'message': 'candidate has no phone'}
    print(f"[Twilio] Attempting to start single interview call for candidate {cand.id} ({cand.phone})")
    sid = start_call_for_candidate(cand.phone, cand.id)
    print(f"[Twilio] Single interview call started, SID: {sid}")
    return {'status': 'ok', 'call_sid': sid}


# ---------------------------
# Twilio voice webhook -> return TwiML to open Media Stream (WebSocket /media)
# ---------------------------
@app.post('/voice')
async def voice(request: Request):
    # Default hardcoded questions
    default_questions = [
        "Tell me about yourself.",
        "What are your key strengths?",
        "What is your biggest weakness?",
        "Describe a challenging project you worked on.",
        "Why are you interested in this role?",
        "How do you handle tight deadlines?",
        "Give an example of teamwork.",
        "Where do you see yourself in 5 years?",
        "How do you keep your skills updated?",
        "Do you have any questions for us?"
    ]
    q_index = int(request.query_params.get("q_index", 0))
    precheck = request.query_params.get("precheck", "1")
    params = await request.form()
    call_sid = params.get("CallSid", "") or request.query_params.get("CallSid", "")
    candidate_id = params.get("candidate_id") or request.query_params.get("candidate_id")
    answer = params.get("SpeechResult")

    # Use generated questions from SESSIONS if available, else fallback
    questions = None
    if call_sid in SESSIONS and SESSIONS[call_sid].get("questions"):
        questions = SESSIONS[call_sid]["questions"]
    else:
        questions = default_questions
    # Log full Twilio request for debugging
    try:
        body = await request.body()
        print(f"[DEBUG] Full Twilio request body: {body}")
    except Exception as e:
        print(f"[DEBUG] Could not log full Twilio request body: {e}")
    print("[DEBUG] Incoming Twilio params:", dict(params))
    print(f"[DEBUG] q_index={q_index}, SpeechResult={answer}")
    # Track Q&A in session
    if call_sid not in SESSIONS:
        # Fetch candidate and JD file for this call
        db = SessionLocal()
        cand = db.query(Candidate).get(int(candidate_id)) if candidate_id else None
        job = db.query(Job).order_by(Job.id.desc()).first()  # latest JD
        jd_file = job.jd_path if job else None
        db.close()
        SESSIONS[call_sid] = {
            "answers": [],
            "questions": questions,
            "candidate_id": candidate_id,
            "jd_file": jd_file,
            "precheck_done": False
        }
    session = SESSIONS[call_sid]
    # Pre-screening step
    if not session["precheck_done"]:
        if not session["precheck_done"]:
            if answer is None:
                print("[DEBUG] Waiting for candidate's speech input for precheck consent...")
                # First call: greet and ask precheck
                twiml = """
<Response>
    <Say voice='Polly.Aditi'>HI! I am Aditi here from "RGi HR team", i connected to conduct short initial round of interview with you</Say>
        <Gather input='speech' action='/voice?precheck=1' method='POST' timeout='12' speechTimeout='auto' hints='yes,ok,ready,sure,start,haan,ha,hoo,thik hai,thik,thikhe,chalega,ji,go ahead,proceed'>
        <Say voice='Polly.Aditi'>Shall we start with the screening process and are you in a silent and calm location to start with the interview?</Say>
    </Gather>
</Response>
"""
                return PlainTextResponse(twiml, media_type="text/xml")
            else:
                print(f"[DEBUG] Received candidate speech for precheck: {answer}")
                # Only validate with LLM (Azure AI)
                from llama_api import validate_precheck
                is_ready = False
                answer_for_llm = answer + "\nCommon Hindi consent words: haan, hoo, thik hai, chalega, theek hai, ha, thikhe, ji, ok, yes, ready, start, proceed, sure, go ahead. Treat these as positive consent."
                try:
                        is_ready = await validate_precheck(answer_for_llm)
                except Exception as e:
                    print(f"[Precheck] LLM validation failed: {e}")
                    # Expand the answer with Hindi consent words for LLM prompt
                if is_ready:
                    session["precheck_done"] = True
                    # Proceed to first question
                    twiml = """
<Response>
    <Say voice='Polly.Aditi'>Great! Let's begin the interview.</Say>
    <Gather input='speech' action='/voice?q_index=1' method='POST' timeout='6' speechTimeout='auto'>
        <Say voice='Polly.Aditi'>Question 1: {}</Say>
    </Gather>
</Response>
""".format(questions[0])
                    return PlainTextResponse(twiml, media_type="text/xml")
                else:
                    print(f"[DEBUG] Precheck failed or ambiguous. Candidate not ready. Answer: {answer}")
                    # Not ready, say goodbye and hang up
                    # Update candidate final_decision in DB
                    try:
                        db = SessionLocal()
                        cand = db.query(Candidate).get(int(session["candidate_id"])) if session["candidate_id"] else None
                        if cand:
                            cand.final_decision = "Asked for Re-scheculing"
                            db.commit()
                        db.close()
                    except Exception as e:
                        print(f"[DB] Failed to update final_decision for reschedule: {e}")

                    twiml = """
                    <Response>
                        <Say voice='Polly.Aditi'>No Problem! Please get in touch with "HR" to get this rescheduled. Thank you for your time!</Say>
                        <Hangup/>
                    </Response>
                    """
                    return PlainTextResponse(twiml, media_type="text/xml")
        else:
            print(f"[DEBUG] Received candidate speech for precheck: {answer}")
            # Accept DTMF '1' as affirmative for debugging
            if answer and answer.strip() == '1':
                print("[DEBUG] DTMF '1' received, treating as affirmative consent.")
                session["precheck_done"] = True
                twiml = """
<Response>
    <Say voice='Polly.Aditi'>Great! Let's begin the interview.</Say>
    <Gather input='speech' action='/voice?q_index=1' method='POST' timeout='6' speechTimeout='auto'>
        <Say voice='Polly.Aditi'>Question 1: {}</Say>
    </Gather>
</Response>
""".format(questions[0])
                return PlainTextResponse(twiml, media_type="text/xml")
            # Validate answer with LLM (Azure AI)
            from llama_api import validate_precheck
            is_ready = False
            try:
                is_ready = await validate_precheck(answer)
            except Exception as e:
                print(f"[Precheck] LLM validation failed: {e}")
            if is_ready:
                session["precheck_done"] = True
                # Proceed to first question
                twiml = """
<Response>
    <Say voice='Polly.Aditi'>Great! Let's begin the interview.</Say>
    <Gather input='speech' action='/voice?q_index=1' method='POST' timeout='6' speechTimeout='auto'>
        <Say voice='Polly.Aditi'>Question 1: {}</Say>
    </Gather>
</Response>
""".format(questions[0])
                return PlainTextResponse(twiml, media_type="text/xml")
            else:
                print(f"[DEBUG] Precheck failed or ambiguous. Candidate not ready. Answer: {answer}")
                # Not ready, say goodbye and hang up
                twiml = """
<Response>
    <Say voice='Polly.Aditi'>Koi baat nahi. Aap jab taiyaar ho tab interview shuru kar sakte hain. Dhanyavaad! Goodbye!</Say>
    <Hangup/>
</Response>
"""
                return PlainTextResponse(twiml, media_type="text/xml")
    # Main interview flow
    if answer:
        session["answers"].append(answer)
    if q_index >= len(questions):
        # Generate report on last question
        try:
            db = SessionLocal()
            cand = db.query(Candidate).get(int(session["candidate_id"])) if session["candidate_id"] else None
            db.close()
            jd_file = session.get("jd_file")
            interview_session = InterviewSession(cand, jd_file=jd_file, use_model_questions=False, hardcoded_questions=questions)
            interview_session.answers = session["answers"]
            interview_session.questions = questions
            interview_session.scores = []
            decision, report_path = interview_session.finalize()
            print(f"[Phone Interview] Report saved: {report_path}")
        except Exception as e:
            print(f"[Phone Interview] Report generation failed: {e}")
        twiml = """
<Response>
    <Say voice=\"Polly.Aditi\">Dhanyavaad! Interview completed. Thanks for your time.Goodbye!</Say>
    <Hangup/>
</Response>
"""
        return PlainTextResponse(twiml, media_type="text/xml")
    next_q_index = q_index + 1
    twiml = "<Response>"
    twiml += f"""
    <Gather input=\"speech\" action=\"/voice?q_index={next_q_index}\" method=\"POST\" timeout=\"12\" speechTimeout=\"auto\">
            <Say voice=\"Polly.Aditi\">Question {q_index+1}: {questions[q_index]}</Say>
  </Gather>
"""
    twiml += "</Response>"
    return PlainTextResponse(twiml, media_type="text/xml")


# ---------------------------
# Twilio Media Stream WebSocket (real-time STT/TTS + 10-question orchestration)
# ---------------------------
@app.websocket('/media')
async def media_stream(ws: WebSocket):
    await ws.accept()
    print("[/media] accepted")

    bundle = None
    call_sid = None
    stream_sid = None
    stt = None
    session = None
    q_index = 0

    # endpointing state
    last_partial = ""
    idle_frames = 0
    FRAMES_SILENCE_TO_END = 50  # ~1s @ 20ms frames

    # For silence timeout
    last_media_time = time.time()
    SILENCE_TIMEOUT = 30  # seconds

    async def speak(text: str):
        if not stream_sid:
            print("[/media] speak() called before start; skipping. Text:", text)
            return
        print(f"[/media] TTS: Speaking: {text}")
        try:
            print(f"[/media] TTS: Calling synthesize_and_stream(ws, {stream_sid}, text)")
            await synthesize_and_stream(ws, stream_sid, text)
            print(f"[/media] TTS: synthesize_and_stream completed for: {text}")
        except Exception as e:
            print(f"[/media] TTS ERROR during synthesize_and_stream for text: {text}\nException: {e}")

    try:
        while True:
            raw = await ws.receive_text()
            # print("[/media] recv:", raw[:200])  # uncomment to inspect
            try:
                msg = json.loads(raw)
            except Exception as e:
                print("[/media] bad json:", e)
                continue

            ev = msg.get("event")

            if ev == "start":
                start = msg.get("start", {}) or {}
                call_sid = start.get("callSid")
                stream_sid = start.get("streamSid")
                print(f"[/media] start: callSid={call_sid} streamSid={stream_sid}")

                # look up the session created in /voice using CallSid
                bundle = SESSIONS.get(call_sid)
                if not bundle:
                    print("[/media] no bundle for callSid — closing")
                    break

                session = bundle["session"]
                stt = bundle["stt"]
                q_index = bundle.get("q_index", 0)

                # generate questions early; say intro + Q1
                try:
                    session.generate_questions()
                except Exception as e:
                    print("[/media] generate_questions error:", e)

                await speak("Namaste! Main AI HR interviewer hoon. Chaliye shuru karte hain.")
                if session.questions:
                    await speak(f"Question 1: {session.questions[0]}")

            elif ev == "media":
                if not stt:
                    continue
                payload = msg.get("media", {}).get("payload")
                if not payload:
                    continue
                try:
                    stt.accept_twilio_media(payload)
                except Exception as e:
                    print("[/media] STT accept error:", e)
                    continue

                partial = stt.partial() or ""
                if partial and partial != last_partial:
                    last_partial = partial
                    idle_frames = 0
                else:
                    idle_frames += 1

                # end of turn on ~1s silence
                if idle_frames >= FRAMES_SILENCE_TO_END and last_partial:
                    try:
                        final_text = stt.final() or last_partial
                    except Exception:
                        final_text = last_partial
                    last_partial = ""
                    idle_frames = 0

                    try:
                        call_sid = ws.query_params.get('CallSid', '')
                        print(f"[/media] accepted. CallSid from query: '{call_sid}'")
                        print(f"[/media] Current SESSIONS keys: {list(SESSIONS.keys())}")

                        if not call_sid or call_sid not in SESSIONS:
                            print("[/media] unknown CallSid; closing")
                            await ws.close()
                            return

                        bundle = SESSIONS[call_sid]
                        session = bundle["session"]
                        stt = bundle["stt"]
                        q_index = bundle.get("q_index", 0)

                        # generate questions early; say intro + Q1
                        try:
                            session.generate_questions()
                        except Exception as e:
                            print("[/media] generate_questions error:", e)

                        await speak("Namaste! Main AI HR interviewer hoon. Chaliye shuru karte hain.")
                        if session.questions:
                            await speak(f"Question 1: {session.questions[0]}")

                        while True:
                            raw = await ws.receive_text()   # keep reading frames
                            try:
                                msg = json.loads(raw)
                            except Exception as e:
                                print("[/media] bad json:", e)
                                continue

                            ev = msg.get("event")
                            if ev == "media":
                                if not stt:
                                    continue
                                payload = msg.get("media", {}).get("payload")
                                if not payload:
                                    continue
                                try:
                                    stt.accept_twilio_media(payload)
                                except Exception as e:
                                    print("[/media] STT accept error:", e)
                                    continue

                                partial = stt.partial() or ""
                                if partial and partial != last_partial:
                                    last_partial = partial
                                    idle_frames = 0
                                else:
                                    idle_frames += 1

                                # end of turn on ~1s silence
                                if idle_frames >= FRAMES_SILENCE_TO_END and last_partial:
                                    try:
                                        final_text = stt.final() or last_partial
                                    except Exception:
                                        final_text = last_partial
                                    last_partial = ""
                                    idle_frames = 0

                                    # Check session still exists before accessing
                                    if call_sid in SESSIONS:
                                        bundle = SESSIONS[call_sid]
                                        session = bundle["session"]
                                        if q_index < len(session.questions):
                                            question = session.questions[q_index]
                                            try:
                                                session.add_answer(question, final_text)
                                            except Exception as e:
                                                print("[/media] add_answer error:", e)
                                            q_index += 1
                                            bundle["q_index"] = q_index

                                        if q_index < len(session.questions):
                                            await speak(f"Question {q_index+1}: {session.questions[q_index]}")
                                        else:
                                            try:
                                                decision, report_path = session.finalize()
                                                await speak(f"Interview complete. Decision: {decision}. Dhanyavaad!")
                                                # (update DB + dashboard same as your existing code)
                                            except Exception as e:
                                                print("[/media] finalize error:", e)
                            elif ev == "start":
                                print("[/media] stream started")
                            elif ev in ("stop","close"):
                                print("[/media] stop/close received")
                                break
                            else:
                                pass

                    except WebSocketDisconnect:
                        print("[/media] ws disconnect")
                    except Exception as e:
                        print("[/media] error:", e)
                    finally:
                        # Only pop if still present
                        if call_sid and call_sid in SESSIONS:
                            SESSIONS.pop(call_sid, None)
                        try:
                            await ws.close()
                        except:
                            pass
                    last_partial = partial
                    idle_frames = 0
                else:
                    idle_frames += 1

                # Turn end
                if idle_frames >= FRAMES_SILENCE_TO_END and last_partial:
                    final_text = stt.final() or last_partial
                    last_partial = ""
                    idle_frames = 0

                    # Add answer & score
                    if q_index < len(session.questions):
                        question = session.questions[q_index]
                        print(f"[Interview] Received answer for Q{q_index+1}: {final_text}")
                        session.add_answer(question, final_text)
                        q_index += 1
                        bundle["q_index"] = q_index

                    # Ask next or finalize
                    if q_index < len(session.questions):
                        print(f"[Interview] Asking Question {q_index+1}: {session.questions[q_index]}")
                        await speak(f"Question {q_index+1}: {session.questions[q_index]}")
                    else:
                        print("[Interview] Finalizing interview and scoring.")
                        decision, report_path = session.finalize()
                        print(f"[Interview] Interview complete. Decision: {decision}. Report: {report_path}")
                        # short spoken summary
                        await speak(f"Interview complete. Decision: {decision}. Dhanyavaad!")
                        # Update DB
                        db = SessionLocal()
                        cid = bundle.get("candidate_id")
                        if cid:
                            cand = db.query(Candidate).get(cid)

            # Silence timeout fallback
            if time.time() - last_media_time > SILENCE_TIMEOUT:
                print(f"[WebSocket] No media received for {SILENCE_TIMEOUT} seconds. Ending call.")
                await speak("We did not receive any response. Ending the interview. Goodbye!")
                break

            if ev in ("stop", "close"):
                break

    except WebSocketDisconnect:
        print("WS disconnect for call:", call_sid)
    except Exception as e:
        print("Media stream exception:", e)
    finally:
        SESSIONS.pop(call_sid, None)
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------
# Dashboard WS (for table auto-refresh)
# ---------------------------
@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ---------------------------
# Candidates API (dashboard table)
# ---------------------------
@app.get('/api/candidates')
async def api_candidates():
    db = SessionLocal()
    rows = db.query(Candidate).all()
    out = []
    for r in rows:
        out.append({
            'id': r.id,
            'name': r.name,
            'phone': r.phone,
            'resume_path': r.resume_path,
            'shortlist': r.shortlist_decision,
            'shortlist_reason': getattr(r, 'shortlist_reason', None),
            'call_status': r.call_status,
            'final_decision': r.final_decision
        })
    db.close()
    return out


# ---------------------------
# Reports listing + viewer
# ---------------------------
@app.get('/reports', response_class=HTMLResponse)
async def reports_page():
    path = os.path.join('static', 'reports.html')
    if not os.path.exists(path):
        return HTMLResponse('<h3>Reports page missing</h3>', status_code=404)
    return HTMLResponse(open(path, 'r', encoding='utf-8').read())

@app.get('/reports/api')
async def reports_api():
    files = sorted(glob.glob(os.path.join('results/interview_reports', '*')))
    base = '/reports/files'
    return {'reports': [{'file': os.path.basename(f), 'url': f'{base}/{os.path.basename(f)}'} for f in files]}


# ---------------------------
# Dashboard HTML
# ---------------------------
@app.get('/dashboard', response_class=HTMLResponse)
async def dashboard():
    path = os.path.join('static', 'dashboard.html')
    if not os.path.exists(path):
        return HTMLResponse('<h3>Dashboard missing</h3>', status_code=404)
    return HTMLResponse(open(path, 'r', encoding='utf-8').read())

@app.get('/reports/view/{json_filename}', response_class=HTMLResponse)
async def view_report(json_filename: str):
    path = os.path.join('results/interview_reports', json_filename)
    if not os.path.exists(path):
        return HTMLResponse('<h3>Not found</h3>', status_code=404)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    decision = data.get('overall', {}).get('decision', 'UNKNOWN')
    reason = data.get('overall', {}).get('reason', '')
    questions = data.get('questions', [])
    answers = data.get('answers', [])
    scores = data.get('scores', [])
    rows = ''
    for i in range(len(questions)):
        q = questions[i] if i < len(questions) else ''
        a = answers[i] if i < len(answers) else ''
        s = scores[i] if i < len(scores) else {'score': '-', 'reason': ''}
        rows += f"<tr><td>{i+1}</td><td>{q}</td><td>{a}</td><td>{s.get('score','-')}</td><td>{s.get('reason','')}</td></tr>"
    html = f"""
<!doctype html>
<html><head><meta charset='utf-8'><title>Report</title>
<style>
body {{ font-family: 'Roboto', Arial, sans-serif; background: #f4f6fa; margin: 0; padding: 0; }}
.header {{ background: linear-gradient(90deg, #4f8cff 0%, #2355d6 100%); color: #fff; padding: 24px 0 16px 0; text-align: center; box-shadow: 0 2px 8px rgba(44,62,80,0.08); }}
.header h1 {{ margin: 0; font-size: 2.2rem; font-weight: 700; letter-spacing: 1px; }}
.container {{ max-width: 900px; margin: 40px auto 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); padding: 32px 40px 40px 40px; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(44,62,80,0.04); margin-bottom: 32px; }}
th, td {{ padding: 12px 10px; text-align: left; }}
th {{ background: #f0f4fa; color: #2a3b4c; font-weight: 700; border-bottom: 2px solid #e3e8f0; }}
tr:nth-child(even) td {{ background: #f9fafb; }}
tr:hover td {{ background: #eaf1fb; }}
footer {{ background: #2a3b4c; color: #fff; text-align: center; padding: 18px 0 12px 0; margin-top: 40px; font-size: 1rem; letter-spacing: 1px; }}
</style>
</head><body>
<div class='header'><h1>Interview Report</h1></div>
<div class='container'>
<h2>Status: {decision}</h2>
<p><b>Reason:</b> {reason}</p>
<table><tr><th>#</th><th>Question</th><th>Answer</th><th>Score</th><th>Rationale</th></tr>{rows}</table>
<p><a href='/reports/files/{json_filename}' download>Download JSON</a></p>
</div>
<footer>&copy; 2025 AI Recruitment Platform &mdash; Powered by GenAI</footer>
</body></html>"""
    return HTMLResponse(html)

# ---------------------------
# LLM-based Shortlisting (Azure OpenAI)
# ---------------------------
import requests

@app.post('/shortlist/llm')
async def shortlist_llm(jd_filename: str = Form(...)):
    jd_path = os.path.join('jd', jd_filename)
    if not os.path.exists(jd_path):
        return {'status': 'error', 'message': 'JD not found'}
    jd_text = read_pdf(jd_path)
    db = SessionLocal()
    candidates = db.query(Candidate).all()
    api_url = "https://brobotchatgpt.openai.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2024-02-15-preview"
    api_key = "d696ac8bd83a4679b9580b86ef104809"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    prompt_template = (
        "You are an expert recruiter. Given the following Job Description (JD) and Candidate Resume/Profile, decide if the candidate should be shortlisted for interview. "
        "Reply with 'SELECT' if suitable, otherwise 'REJECT'.\n\nJD:\n{jd}\n\nCandidate Profile:\n{profile}.\n\nProvide reason for selection/rejection."
    )
    results = []
    for cand in candidates:
        try:
            resume_text = read_pdf(cand.resume_path)
        except Exception:
            resume_text = cand.name or ''
        # Parse profile for structured info
        from resume_parser import parse_resume
        profile = parse_resume(resume_text)
        profile_str = f"Name: {profile.get('name','')}, Phone: {profile.get('phone','')}, Skills: {profile.get('skills','')}, Experience: {profile.get('total_experience_years','')} years\nResume Text: {resume_text}"
        prompt = prompt_template.format(jd=jd_text, profile=profile_str)
        body = {
            "messages": [
                {"role": "system", "content": prompt}
            ],
            "temperature": 0.7,
            "top_p": 0.95,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "max_tokens": 2800,
            "stop": None
        }
        print(f"[Azure LLM INPUT] Candidate ID: {cand.id}\nPrompt: {prompt}\nBody: {body}")
        try:
            resp = requests.post(api_url, headers=headers, json=body, timeout=60)
            print(f"[Azure LLM OUTPUT] Candidate ID: {cand.id}\nStatus: {resp.status_code}\nResponse: {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            reply_upper = reply.upper()
            if "SELECT" in reply_upper:
                cand.shortlist_decision = "SELECT"
            else:
                cand.shortlist_decision = "REJECT"
            cand.shortlist_reason = reply
            db.commit()
            shortlist_reasons[cand.id] = reply
            results.append({
                "id": cand.id,
                "name": cand.name,
                "shortlist": cand.shortlist_decision,
                "reason": reply,
                "reply": reply
            })
        except Exception as e:
            print(f"[Azure LLM ERROR] Candidate ID: {cand.id}\nError: {e}")
            results.append({"id": cand.id, "name": cand.name, "shortlist": "ERROR", "error": str(e)})
    db.close()
    await manager.broadcast({'type': 'shortlist_update'})
    return {"status": "ok", "results": results}

# Store LLM shortlist reasons in memory (for demo; use DB in production)
shortlist_reasons = {}

from fastapi import Path
@app.get('/shortlist/reason/{candidate_id}')
async def get_shortlist_reason(candidate_id: int = Path(...)):
    reason = shortlist_reasons.get(candidate_id, None)
    return {"reason": reason}
