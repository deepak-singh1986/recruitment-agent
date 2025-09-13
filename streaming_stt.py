import base64, numpy as np, os, json as _json
from vosk import Model, KaldiRecognizer
VOSK_MODEL_PATH = os.getenv('VOSK_MODEL_PATH','models/vosk-model-en-in-0.5')
_vosk_model = None
def _get_model():
    global _vosk_model
    if _vosk_model is None:
        _vosk_model = Model(VOSK_MODEL_PATH)
    return _vosk_model

_mu_law_lut = None
def _build_mulaw_lut():
    import numpy as _np
    lut = _np.zeros(256, dtype=_np.int16)
    for i in range(256):
        u = ~i & 0xFF
        sign = u & 0x80
        exponent = (u & 0x70) >> 4
        mantissa = u & 0x0F
        magnitude = ((mantissa << 4) + 0x08) << exponent
        sample = magnitude - 0x84
        if sign != 0: sample = -sample
        lut[i] = sample
    return lut

def mulaw_bytes_to_pcm16_bytes(u_bytes: bytes) -> bytes:
    global _mu_law_lut
    if _mu_law_lut is None:
        _mu_law_lut = _build_mulaw_lut()
    arr = np.frombuffer(u_bytes, dtype=np.uint8)
    pcm = _mu_law_lut[arr]
    return pcm.tobytes()

class StreamingSTT:
    def __init__(self, sample_rate=8000):
        self.model = _get_model()
        self.rec = KaldiRecognizer(self.model, sample_rate)
    def accept_twilio_media(self, media_payload_b64: str):
        raw = base64.b64decode(media_payload_b64)
        pcm16 = mulaw_bytes_to_pcm16_bytes(raw)
        self.rec.AcceptWaveform(pcm16)
    def partial(self):
        try:
            res = _json.loads(self.rec.PartialResult())
            return res.get('partial')
        except Exception:
            return None
    def final(self):
        try:
            res = _json.loads(self.rec.Result())
            return res.get('text')
        except Exception:
            return None
