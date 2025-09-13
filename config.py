# config.py

# Global config for question generation mode
# 0 = hardcoded, 1 = Ollama, 2 = Azure OpenAI
USE_MODEL_QUESTIONS = 2

def get_use_model_questions():
    return USE_MODEL_QUESTIONS
