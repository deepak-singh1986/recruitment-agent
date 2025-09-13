# twilio_status_router.py
# APIRouter for Twilio status callbacks: updates Candidate.call_status and appends rows to call_logs.
# Works with PostgreSQL via your existing db.SessionLocal.

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from datetime import datetime
from db import SessionLocal, Candidate

router = APIRouter()

# Create call_logs table if it doesn't exist
DDL = """
CREATE TABLE IF NOT EXISTS call_logs (
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NULL,
    call_sid TEXT,
    status TEXT,
    to_number TEXT,
    from_number TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

def _ensure_table():
    try:
        db = SessionLocal()
        db.execute(text(DDL))
        db.commit()
    except Exception as e:
        print("call_logs DDL error:", e)
    finally:
        try:
            db.close()
        except:
            pass

_ensure_table()

# Map Twilio call statuses to our internal labels
STATUS_MAP = {
    "queued": "QUEUED",
    "initiated": "INITIATED",
    "ringing": "RINGING",
    "answered": "IN_CALL",
    "in-progress": "IN_CALL",
    "completed": "DONE",
    "busy": "BUSY",
    "no-answer": "NO_ANSWER",
    "failed": "FAILED",
    "canceled": "CANCELED",
}

@router.post("/twilio-status")
async def twilio_status(request: Request):
    form = await request.form()
    # Common Twilio fields
    call_sid = form.get("CallSid")
    call_status = (form.get("CallStatus") or "").lower()
    to_number = form.get("To")
    from_number = form.get("From")
    # Preserve candidate_id via querystring pass-through
    candidate_id = form.get("candidate_id") or request.query_params.get("candidate_id")

    # Insert raw log row
    try:
        db = SessionLocal()
        payload = {k: v for k, v in form.items()}
        db.execute(
            text("""
                INSERT INTO call_logs (candidate_id, call_sid, status, to_number, from_number, payload)
                VALUES (:candidate_id, :call_sid, :status, :to_number, :from_number, CAST(:payload AS JSONB))
            """),
            {
                "candidate_id": int(candidate_id) if candidate_id else None,
                "call_sid": call_sid,
                "status": call_status,
                "to_number": to_number,
                "from_number": from_number,
                "payload": str(payload).replace("'", '"'),  # naive stringify to JSON-ish; adjust if needed
            }
        )
        db.commit()
    except Exception as e:
        print("twilio_status insert log error:", e)
    finally:
        try:
            db.close()
        except:
            pass

    # Update Candidate.call_status if candidate_id present
    if candidate_id:
        try:
            db = SessionLocal()
            cand = db.query(Candidate).get(int(candidate_id))
            if cand:
                new_status = STATUS_MAP.get(call_status, call_status.upper() if call_status else None)
                if new_status:
                    cand.call_status = new_status
                # Optional audit fields if your model has them
                if hasattr(cand, "last_call_sid"):
                    cand.last_call_sid = call_sid
                if hasattr(cand, "last_call_status"):
                    cand.last_call_status = call_status
                if hasattr(cand, "last_call_at"):
                    cand.last_call_at = datetime.utcnow()
                db.commit()
            db.close()
        except Exception as e:
            print("twilio_status candidate update error:", e)

    # Acknowledge to Twilio
    return PlainTextResponse("OK")
