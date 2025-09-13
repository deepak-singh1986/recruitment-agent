import os, json, datetime
from dotenv import load_dotenv
load_dotenv()
import ollama
from pdf_utils import read_pdf
from resume_parser import parse_resume

class InterviewSession:
    def __init__(self, candidate, jd_file, out_dir="results/interview_reports", use_model_questions=True, hardcoded_questions=None):
        self.candidate = candidate
        self.jd_file = jd_file
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

        # Configurable flag: use model or hardcoded questions
        self.use_model_questions = use_model_questions
        self.hardcoded_questions = hardcoded_questions or [
            "Tell me about yourself.",
            "What are your key strengths?",
            "What is your biggest weakness?",
            "Describe a challenging project you worked on.",
            "Why are you interested in this role?",
            "How do you handle tight deadlines?",
            "Give an example of teamwork.",
            "Where do you see yourself in 5 years?",
            "How do you keep your skills updated?",
            "Do you have any questions for us?"
        ]

        # Extract JD text
        self.jd_text = read_pdf(jd_file)
        # Extract resume text + structured info
        self.resume_text = read_pdf(candidate.resume_path)
        self.resume_profile = parse_resume(self.resume_text)

        # Store results
        self.questions = []
        self.answers = []
        self.scores = []

    def _ask_llama(self, prompt):
        """Helper to query LLaMA"""
        resp = ollama.chat(model="llama3.1", messages=[{"role": "user", "content": prompt}])
        return resp["message"]["content"]

    def generate_questions(self):
        """Generate or use hardcoded/model/Azure questions based on config flag"""
        # USE_MODEL_QUESTIONS: 0=hardcoded, 1=Ollama, 2=Azure
        flag = os.getenv('USE_MODEL_QUESTIONS', '0')
        print(f"[DEBUG] USE_MODEL_QUESTIONS flag at runtime: {flag}")
        if flag == '0':
            self.questions = self.hardcoded_questions[:10]
            print(f"[QUESTIONS] (Hardcoded) Candidate {getattr(self.candidate, 'id', '?')} ({getattr(self.candidate, 'name', '?')}):")
            for idx, q in enumerate(self.questions, 1):
                print(f"  Q{idx}: {q}")
            return self.questions
        elif flag == '1':
            # Ollama (LLaMA)
            q_jd = self._ask_llama(f"Read this JD:\n{self.jd_text}\nGenerate 3 interview questions.").split("\n")
            q_resume = self._ask_llama(f"Read this candidate resume:\n{self.resume_text}\nGenerate 3 interview questions.").split("\n")
            q_strength = self._ask_llama(f"From this candidate profile:\n{self.resume_profile}\nGenerate 2 interview questions about strengths.").split("\n")
            q_weakness = self._ask_llama(f"From this candidate profile:\n{self.resume_profile}\nGenerate 2 interview questions about weaknesses.").split("\n")
            self.questions = [q for q in (q_jd + q_resume + q_strength + q_weakness) if q.strip()][:10]
            print(f"[QUESTIONS] (Ollama) Candidate {getattr(self.candidate, 'id', '?')} ({getattr(self.candidate, 'name', '?')}):")
            for idx, q in enumerate(self.questions, 1):
                print(f"  Q{idx}: {q}")
            return self.questions
        elif flag == '2':
            # Azure OpenAI
            from azure_questions import generate_azure_questions
            self.questions = generate_azure_questions(self.jd_text, self.resume_text, self.resume_profile)
            print(f"[QUESTIONS] (Azure) Candidate {getattr(self.candidate, 'id', '?')} ({getattr(self.candidate, 'name', '?')}):")
            for idx, q in enumerate(self.questions, 1):
                print(f"  Q{idx}: {q}")
            return self.questions
        else:
            # fallback to hardcoded
            self.questions = self.hardcoded_questions[:10]
            print(f"[QUESTIONS] (Fallback-Hardcoded) Candidate {getattr(self.candidate, 'id', '?')} ({getattr(self.candidate, 'name', '?')}):")
            for idx, q in enumerate(self.questions, 1):
                print(f"  Q{idx}: {q}")
            return self.questions

    def evaluate_answer(self, question, answer):
        """Ask LLaMA to score the candidate’s answer"""
        eval_prompt = f"""
        You are an interviewer. Evaluate the candidate’s answer.
        Question: {question}
        Answer: {answer}
        Respond in JSON with fields: score (1-10), reason.
        """
        try:
            raw = self._ask_llama(eval_prompt)
            result = json.loads(raw) if raw.strip().startswith("{") else {"score": 5, "reason": raw}
        except Exception as e:
            result = {"score": 5, "reason": f"Parsing error: {str(e)}"}
        self.scores.append(result)
        return result

    def add_answer(self, question, answer):
        self.answers.append(answer)
        score = self.evaluate_answer(question, answer)
        return score

    def finalize(self):
        """Compute final decision + save JSON report"""
        avg_score = sum([s.get("score", 5) for s in self.scores]) / len(self.scores) if self.scores else 0
        decision = "SELECT" if avg_score >= 6 else "REJECT"
        reason = f"Average score = {avg_score:.1f}, threshold=6."

        report = {
            "candidate": {
                "id": self.candidate.id,
                "name": self.candidate.name,
                "phone": self.candidate.phone,
            },
            "job": os.path.basename(self.jd_file),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "questions": self.questions,
            "answers": self.answers,
            "scores": self.scores,
            "overall": {"decision": decision, "reason": reason}
        }

        filename = f"report_{self.candidate.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path = os.path.join(self.out_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        return decision, out_path
