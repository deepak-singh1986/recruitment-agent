import spacy
import re
_nlp = None
def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load('en_core_web_sm')
    return _nlp

SKILL_HINTS = ["python","pandas","numpy","scikit","sklearn","pytorch","tensorflow","ml","machine learning",
    "java","spring","sql","spark","aws","gcp","azure","docker","kubernetes","nlp","llm"]

def parse_resume(resume_text: str) -> dict:
    nlp = _get_nlp()
    doc = nlp(resume_text)
    skills = sorted({k for k in SKILL_HINTS if k in resume_text.lower()})
    years = [int(x) for x in re.findall(r"(\\d+)\\s+year", resume_text.lower())]
    total_exp = max(years) if years else None
    name = None
    for ent in doc.ents:
        if ent.label_ == 'PERSON' and 1 <= len(ent.text.split()) <= 4:
            name = ent.text
            break
    phone_pattern = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
    phones = phone_pattern.findall(resume_text)
    phone = None
    if phones:
        phone = phones[0].replace(' ','').replace('-','')
    return {"name": name, "skills": skills, "total_experience_years": total_exp, "phone": phone}
