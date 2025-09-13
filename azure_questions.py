import os
import requests
import asyncio

AZURE_OPENAI_URL = "https://brobotchatgpt.openai.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2024-02-15-preview"
AZURE_OPENAI_KEY = "d696ac8bd83a4679b9580b86ef104809"

def generate_azure_questions(jd_text, resume_text, resume_profile):
    """
    Use Azure OpenAI to generate 10 interview questions: 3 from JD, 3 from profile, 2 from strengths, 2 from weaknesses.
    """
    prompt = f"""
You are an expert HR interviewer. Generate 10 unique interview questions for a candidate based on the following:
- 3 questions from the Job Description (JD)
- 3 questions from the candidate's profile
- 2 questions about strengths
- 2 questions about weaknesses

Job Description:
{jd_text}

Candidate Profile:
{resume_profile}

Candidate Resume:
{resume_text}

Return the questions as a numbered list, one per line.
"""
    headers = {
        'api-key': AZURE_OPENAI_KEY,
        'Content-Type': 'application/json',
    }
    data = {
        "messages": [
            {"role": "system", "content": "You are an expert HR interviewer."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "top_p": 0.95,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "max_tokens": 512,
        "stop": None
    }
    r = requests.post(AZURE_OPENAI_URL, headers=headers, json=data, timeout=60)
    r.raise_for_status()
    response = r.json()
    content = response['choices'][0]['message']['content']
    questions = [q.strip().lstrip('0123456789. ') for q in content.split('\n') if q.strip()]
    return questions[:10]
