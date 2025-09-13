import asyncio, json, base64, wave
import websockets
def pcm16_to_mulaw(pcm16_bytes):
    import numpy as np
    pcm = np.frombuffer(pcm16_bytes, dtype=np.int16)
    pcm = np.clip(pcm, -32635, 32635)
    mu = 255.0
    magnitude = np.log1p(mu * np.abs(pcm) / 32768.0) / np.log1p(mu)
    signal = np.sign(pcm) * magnitude
    encoded = ((signal + 1)/2 * mu + 0.5).astype(np.uint8)
    return encoded.tobytes()

async def simulate(file_path='sample_audio.wav'):
    uri = 'ws://localhost:8000/media?CallSid=SIMTEST123'
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({'event':'start','start':{'streamSid':'SIMSTREAM1'}}))
        wf = wave.open(file_path,'rb')
        assert wf.getframerate()==8000 and wf.getnchannels()==1
        frame_size = 160
        pcm = wf.readframes(frame_size)
        while pcm:
            mu = pcm16_to_mulaw(pcm)
            b64 = base64.b64encode(mu).decode('utf-8')
            await ws.send(json.dumps({'event':'media','media':{'payload':b64}}))
            await asyncio.sleep(0.02)
            pcm = wf.readframes(frame_size)
        await ws.send(json.dumps({'event':'stop'}))
if __name__=='__main__': asyncio.run(simulate('sample_audio.wav'))
