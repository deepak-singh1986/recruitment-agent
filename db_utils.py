import os
from datetime import datetime
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import insert, select, update
from dotenv import load_dotenv

# Load env variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, echo=False)
Session = sessionmaker(bind=engine)
session = Session()

metadata = MetaData()
metadata.reflect(bind=engine)

# Reflect tables created in init_db.py
JobDescriptions = metadata.tables["job_descriptions"]
Candidates = metadata.tables["candidates"]
Interviews = metadata.tables["interviews"]
InterviewLogs = metadata.tables["interview_logs"]

# === CRUD HELPERS ===

def add_job_description(title: str, file_path: str):
    stmt = insert(JobDescriptions).values(
        title=title,
        file_path=file_path,
        created_at=datetime.utcnow()
    )
    session.execute(stmt)
    session.commit()

def add_candidate(name: str, phone: str, file_path: str):
    stmt = insert(Candidates).values(
        name=name,
        phone=phone,
        file_path=file_path,
        shortlisted=False,
        created_at=datetime.utcnow()
    )
    session.execute(stmt)
    session.commit()

def shortlist_candidate(candidate_id: int):
    stmt = update(Candidates).where(
        Candidates.c.id == candidate_id
    ).values(shortlisted=True)
    session.execute(stmt)
    session.commit()

def create_interview(candidate_id: int, job_id: int):
    stmt = insert(Interviews).values(
        candidate_id=candidate_id,
        job_id=job_id,
        status="pending",
        created_at=datetime.utcnow()
    ).returning(Interviews.c.id)
    result = session.execute(stmt)
    session.commit()
    return result.scalar()

def update_interview_status(interview_id: int, status: str, result: str = None, report_path: str = None):
    stmt = update(Interviews).where(
        Interviews.c.id == interview_id
    ).values(
        status=status,
        result=result,
        report_path=report_path
    )
    session.execute(stmt)
    session.commit()

def log_interview_qa(interview_id: int, question: str, answer: str, evaluation: str):
    stmt = insert(InterviewLogs).values(
        interview_id=interview_id,
        question=question,
        answer=answer,
        evaluation=evaluation,
        created_at=datetime.utcnow()
    )
    session.execute(stmt)
    session.commit()

# === QUERY HELPERS ===

def get_all_candidates():
    stmt = select(Candidates)
    result = session.execute(stmt)
    return result.fetchall()

def get_shortlisted_candidates():
    stmt = select(Candidates).where(Candidates.c.shortlisted == True)
    result = session.execute(stmt)
    return result.fetchall()

def get_interview_logs(interview_id: int):
    stmt = select(InterviewLogs).where(InterviewLogs.c.interview_id == interview_id)
    result = session.execute(stmt)
    return result.fetchall()
