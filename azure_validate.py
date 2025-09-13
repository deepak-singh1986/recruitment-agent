
# Hardcoded Azure OpenAI API details as per user request
import requests
import asyncio

AZURE_OPENAI_URL = "https://brobotchatgpt.openai.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2024-02-15-preview"
AZURE_OPENAI_KEY = "d696ac8bd83a4679b9580b86ef104809"

async def validate_precheck(answer: str) -> bool:
    """
    Use Azure OpenAI to check if the candidate is ready for the interview (affirmative response).
    Returns True if ready, False otherwise.
    """
    prompt = (
        "You are an AI assistant for phone interviews. "
        "Given the following candidate response, determine if the candidate is ready to start the interview (i.e., they are in a calm and silent location and willing to proceed). "
        "Respond only with 'YES' or 'NO'.\n"
        f"Candidate: {answer}\n"
        "Ready?"
    )
    headers = {
        'api-key': AZURE_OPENAI_KEY,
        'Content-Type': 'application/json',
    }
    data = {
        "messages": [
            {"role": "system", "content": "You are an AI assistant for phone interviews."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "top_p": 0.95,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "max_tokens": 10,
        "stop": None
    }
    loop = asyncio.get_event_loop()
    def do_request():
        r = requests.post(AZURE_OPENAI_URL, headers=headers, json=data, timeout=30)
        r.raise_for_status()
        print(f"[validate_precheck] Azure OpenAI raw response: { r.raise_for_status()}")
        return r.json()
    try:
        response = await loop.run_in_executor(None, do_request)
        print(f"[validate_precheck] Azure OpenAI raw response: {response}")
        content = response['choices'][0]['message']['content'].strip().lower()
        return content.startswith('y')
    except Exception as e:
        print(f"[validate_precheck] Azure OpenAI error: {e}")
        return False
