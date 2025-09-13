# tts_stream.py — FREE TTS for Hinglish (gTTS by default, optional Piper)
# Converts text -> speech -> μ-law (8 kHz) -> streams to Twilio Media Streams WS.
# Requirements:
#   - FFmpeg on PATH
#   - For gTTS: pip install gTTS (internet required)
#   - Optional Piper (offline): install 'piper' binary and download a Hindi/Indian-English voice
#
# Env options:
#   TTS_ENGINE=gtts | piper   (default: gtts)
#   GTTS_LANG=en              (default: en)
#   GTTS_TLD=co.in            (default: co.in for Indian English flavor)
#   PIPER_BIN=piper           (path to piper executable)
#   PIPER_VOICE=voices/hi-IN-voice.onnx
#   PIPER_CONF=voices/hi-IN-voice.onnx.json
#   FFMPEG_BIN=ffmpeg
#
# Usage from app.py:
#   from tts_stream import synthesize_and_stream
#   await synthesize_and_stream(ws, streamSid, "Namaste! Main AI HR interviewer hoon.")
#
import os
import base64
import tempfile
import subprocess

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
ENGINE = os.getenv("TTS_ENGINE", "gtts").lower()

def _ensure_ffmpeg():
    try:
        subprocess.run([FFMPEG_BIN, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as e:
        raise RuntimeError("ffmpeg not found on PATH. Please install FFmpeg and add to PATH.") from e

# ---------------- gTTS engine (FREE, cloud) ----------------
def _synthesize_gtts_to_mp3(text: str) -> str:
    from gtts import gTTS
    lang = os.getenv("GTTS_LANG", "en")
    tld = os.getenv("GTTS_TLD", "co.in")  # Indian English flavor
    tts = gTTS(text=text, lang=lang, tld=tld)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tts.save(tmp.name)
    return tmp.name

# ---------------- Piper engine (FREE, offline) -------------
def _synthesize_piper_to_wav(text: str) -> str:
    piper_bin = os.getenv("PIPER_BIN", "piper")
    voice = os.getenv("PIPER_VOICE")
    conf = os.getenv("PIPER_CONF")
    if not voice:
        raise RuntimeError("PIPER_VOICE env is required when TTS_ENGINE=piper (path to .onnx voice).")
    # Build command; Piper can read text from argument with --text, or stdin.
    cmd = [piper_bin, "--model", voice, "--output_file", "-"]
    if conf:
        cmd += ["--config", conf]
    # Write wav to temp file since we need to transcode with ffmpeg anyway
    tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    # We'll capture stdout (wav) and write to file
    try:
        proc = subprocess.run(cmd + ["--text", text], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=False)
        with open(tmp_wav.name, "wb") as f:
            f.write(proc.stdout)
    except Exception as e:
        raise RuntimeError(f"Piper synthesis failed: {e}")
    return tmp_wav.name

async def synthesize_and_stream(ws, streamSid: str, text: str, chunk_ms: int = 20):
    """Synthesize TTS using selected engine and stream μ-law @ 8kHz to Twilio WS."""
    if not streamSid or not text:
        print(f"[TTS] synthesize_and_stream: missing streamSid or text. streamSid={streamSid}, text={text}")
        return
    _ensure_ffmpeg()

    # 1) Synthesize
    audio_path = None
    kind = None
    try:
        if ENGINE == "piper":
            audio_path = _synthesize_piper_to_wav(text)
            kind = "wav"
        else:
            audio_path = _synthesize_gtts_to_mp3(text)
            kind = "mp3"

        # Optional: log audio file size
        if audio_path and os.path.exists(audio_path):
            size_kb = os.path.getsize(audio_path) / 1024
            print(f"[TTS] Synthesized {kind} file: {audio_path} ({size_kb:.1f} KB)")

        # 2) Transcode to μ-law mono 8 kHz and stream (explicit Twilio format)
        cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
            "-i", audio_path,
            "-ar", "8000", "-ac", "1",
            "-acodec", "pcm_mulaw",
            "-f", "mulaw", "pipe:1"
        ]
        # 8kHz * 0.02s = 160 bytes per 20ms frame
        chunk_bytes = int(8000 * (chunk_ms / 1000.0))

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        frame_count = 0
        while True:
            chunk = proc.stdout.read(chunk_bytes)
            if not chunk:
                break
            payload = base64.b64encode(chunk).decode("utf-8")
            msg = {"event": "media", "streamSid": streamSid, "media": {"payload": payload}}
            try:
                await ws.send_json(msg)
                frame_count += 1
            except Exception as e:
                print(f"[TTS] ERROR sending audio frame {frame_count}: {e}")
                break
        proc.wait()
        print(f"[TTS] Streamed {frame_count} audio frames for text: {text}")
        # 3) Send mark event to signal end of speech
        try:
            await send_mark(ws, streamSid)
            print(f"[TTS] Sent mark event for end of speech.")
        except Exception as e:
            print(f"[TTS] ERROR sending mark event: {e}")
    finally:
        # 4) Cleanup
        try:
            if audio_path and os.path.exists(audio_path):
                print(f"[TTS] Removing temp audio file: {audio_path}")
                os.remove(audio_path)
        except Exception as e:
            print(f"[TTS] Error removing temp audio file: {e}")

async def send_mark(ws, streamSid: str, name: str = "end_of_speech"):
    if not streamSid: return
    await ws.send_json({"event": "mark", "streamSid": streamSid, "mark": {"name": name}})
