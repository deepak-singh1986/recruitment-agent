# Twilio Status Callback + Call Logs

This router adds:
- `POST /twilio-status` endpoint for Twilio **StatusCallback** webhooks.
- A PostgreSQL `call_logs` table to persist every status event (raw payload).

## Files
- `twilio_status_router.py`

## How to install
1. Place `twilio_status_router.py` next to your `app.py` (or within an `api/` package).
2. In `app.py` add:
   ```python
   from twilio_status_router import router as twilio_status_router
   app.include_router(twilio_status_router)
   ```
3. In `call_control.py`, enable **status callbacks**:
   ```python
   from urllib.parse import urlencode
   base = _https_base(PUBLIC_SERVER_URL)
   voice_url  = f"{base}/voice?{urlencode({'candidate_id': candidate_id})}"
   status_url = f"{base}/twilio-status?{urlencode({'candidate_id': candidate_id})}"

   call = client.calls.create(
       to=to_e164,
       from_=TWILIO_PHONE,
       url=voice_url,
       method="POST",
       status_callback=status_url,
       status_callback_method="POST",
       status_callback_event=["initiated", "ringing", "answered", "completed"]
   )
   ```

## Database
When the router module loads, it executes:
```sql
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
```
> Requires PostgreSQL and that your `db.SessionLocal` is configured properly.

Each webhook inserts a row into `call_logs` and (if `candidate_id` present) updates `Candidate.call_status` using the following mapping:
```
queued -> QUEUED
initiated -> INITIATED
ringing -> RINGING
answered/in-progress -> IN_CALL
completed -> DONE
busy/no-answer/failed/canceled -> same label uppercased
```

## Notes
- The payload JSON is created from the form fields Twilio posts. If you need strict JSON, you can swap the naive stringify with `json.dumps(dict(form))` using Starlette form parsing; adjust to your needs.
- This module is defensive: it won't crash your app if the log insert fails; it prints an error and continues.
