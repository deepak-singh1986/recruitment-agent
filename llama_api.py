from azure_validate import validate_precheck
import os, requests
OLLAMA_URL = os.getenv('OLLAMA_URL','http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL','llama-3.1-8b')
EMBED_MODEL = os.getenv('EMBED_MODEL','nomic-embed-text')

def llm(prompt: str, temperature: float = 0.2, max_tokens: int = 512) -> str:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "temperature": temperature, "max_tokens": max_tokens}
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        return data.get('response') or data.get('completion') or str(data)
    return str(data)

def embed_text(text: str):
    payload = {"model": EMBED_MODEL, "input": text}
    try:
        r = requests.post(f"{OLLAMA_URL}/api/embeddings", json=payload, timeout=60)
        r.raise_for_status()
        return r.json().get('embedding')
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Embedding API call failed: {e}")
        return None
