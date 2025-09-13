import os, json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
RESULTS_DIR = 'results/interview_reports'
os.makedirs(RESULTS_DIR, exist_ok=True)
def _timestamped(candidate_name, ext):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f"{candidate_name}_{ts}.{ext}".replace(' ','_')
    return os.path.join(RESULTS_DIR, fname)
def save_json(report,candidate_name):
    path = _timestamped(candidate_name,'json')
    with open(path,'w',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    return path
def save_pdf(report,candidate_name):
    path = _timestamped(candidate_name,'pdf')
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path,pagesize=A4)
    elems = []
    elems.append(Paragraph(f'Interview Report - {candidate_name}', styles['Title'])); elems.append(Spacer(1,12))
    overall = report.get('overall',{})
    elems.append(Paragraph('Overall Decision', styles['Heading2']))
    elems.append(Paragraph(str(overall.get('decision','UNKNOWN')), styles['Normal']))
    elems.append(Paragraph(str(overall.get('reason','')), styles['Normal'])); elems.append(Spacer(1,12))
    elems.append(Paragraph('Questions & Answers', styles['Heading2']))
    qs = report.get('questions',[]); ans = report.get('answers',[]); sc = report.get('scores',[])
    for i,q in enumerate(qs):
        a = ans[i] if i < len(ans) else ''
        s = sc[i] if i < len(sc) else {'score':'-','reason':''}
        elems.append(Paragraph(f'Q{i+1}: {q}', styles['Normal'])); elems.append(Paragraph(f'A: {a}', styles['Italic']))
        elems.append(Paragraph(f"Score: {s.get('score','-')} - {s.get('reason','')}", styles['Normal'])); elems.append(Spacer(1,8))
    doc.build(elems); return path
def save_html(report,candidate_name):
    path = _timestamped(candidate_name,'html')
    decision = report.get('overall',{}).get('decision','UNKNOWN'); reason = report.get('overall',{}).get('reason','')
    qs = report.get('questions',[]); ans = report.get('answers',[]); sc = report.get('scores',[])
    rows = ''
    for i,q in enumerate(qs):
        a = ans[i] if i < len(ans) else ''
        s = sc[i] if i < len(sc) else {'score':'-','reason':''}
        rows += f"<tr><td>{i+1}</td><td>{q}</td><td>{a}</td><td>{s.get('score','-')}</td><td>{s.get('reason','')}</td></tr>"
    html = f"""<html><head><meta charset='utf-8'><title>Report - {candidate_name}</title></head><body><h1>Interview Report - {candidate_name}</h1><p>Status: {decision}</p><p>Reason: {reason}</p><table border='1'><tr><th>#</th><th>Question</th><th>Answer</th><th>Score</th><th>Rationale</th></tr>{rows}</table></body></html>"""
    with open(path,'w',encoding='utf-8') as f: f.write(html)
    return path
