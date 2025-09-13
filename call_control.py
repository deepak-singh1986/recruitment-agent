# call_control.py — places the Twilio call and wires it to /voice + /twilio-status

import os
from urllib.parse import urlencode
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE       = os.getenv("TWILIO_PHONE") or os.getenv("TWILIO_PHONE_NUMBER")
PUBLIC_SERVER_URL  = os.getenv("PUBLIC_SERVER_URL", "")

_client = None

def _get_client():
    global _client
    if _client is None:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            raise RuntimeError("Twilio credentials missing: set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env")
        _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _client

def _https_base(url: str) -> str:
    # Accept forms: example.ngrok-free.app OR http(s)://example.ngrok-free.app
    if not url:
        raise RuntimeError("PUBLIC_SERVER_URL is not set")
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    elif not url.startswith("https://"):
        url = "https://" + url.strip("/")
    return url.rstrip("/")

def _validate_e164(number: str) -> str:
    # Minimal E.164 sanity check (e.g., +917709861994)
    if not number or not number.startswith("+") or not number[1:].isdigit():
        raise ValueError(f"Phone number must be E.164, got: {number!r}")
    return number

def start_call_for_candidate(to_number: str, candidate_id: int) -> str:
    """
    Places an outbound call via Twilio and points Voice webhook to /voice,
    plus StatusCallback to /twilio-status (both carry candidate_id).
    Returns the Call SID.
    """
    print(f"[DEBUG] start_call_for_candidate called with to_number={to_number}, candidate_id={candidate_id}")
    print(f"[DEBUG] TWILIO_PHONE={TWILIO_PHONE}")
    print(f"[DEBUG] PUBLIC_SERVER_URL={PUBLIC_SERVER_URL}")
    client = _get_client()
    to_e164 = _validate_e164(to_number)
    print(f"[DEBUG] to_e164={to_e164}")
    if not TWILIO_PHONE:
        print("[ERROR] TWILIO_PHONE is not set (your Twilio caller ID/number)")
        raise RuntimeError("TWILIO_PHONE is not set (your Twilio caller ID/number)")

    base = _https_base(PUBLIC_SERVER_URL)
    print(f"[DEBUG] HTTPS base for webhook: {base}")
    voice_url  = f"{base}/voice?{urlencode({'candidate_id': candidate_id})}"
    status_url = f"{base}/twilio-status?{urlencode({'candidate_id': candidate_id})}"

    print(f"[Twilio] Placing call to {to_e164} for candidate {candidate_id}")
    print(f"[Twilio] Voice webhook: {voice_url}")
    print(f"[Twilio] Status callback: {status_url}")

    try:
        call = client.calls.create(
            to=to_e164,
            from_=TWILIO_PHONE,
            url=voice_url,
            method="POST",
            status_callback=status_url,
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        print(f"[Twilio] Call SID: {call.sid}")
        return call.sid
    except Exception as e:
        print(f"[Twilio ERROR] Failed to place call: {e}")
        raise
