# db.py — SQLAlchemy setup for AI Recruitment Agent

import os
from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Connection URL from .env
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:test1234@localhost:5432/ai_recruitment")

# SQLAlchemy engine & session
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models
Base = declarative_base()


# -----------------------------
# Job Descriptions
# -----------------------------
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    jd_path = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# -----------------------------
# Candidates
# -----------------------------
class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    resume_path = Column(Text, nullable=False)

    # Parsed data
    skills = Column(JSON, nullable=True)
    experience_years = Column(Integer, nullable=True)

    # Flow state
    shortlist_decision = Column(String, default="PENDING")  # PENDING / SELECT / REJECT
    shortlist_reason = Column(Text, nullable=True)           # LLM explanation for shortlist decision
    call_status = Column(String, default="PENDING")         # PENDING / IN_CALL / DONE / FAILED / etc
    final_decision = Column(String, nullable=True)           # SELECT / REJECT
    report_json = Column(Text, nullable=True)                # filename of JSON report

    # Audit fields
    last_call_sid = Column(String, nullable=True)
    last_call_status = Column(String, nullable=True)
    last_call_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# -----------------------------
# Init function
# -----------------------------
def init_db():
    """Create all tables if they don't exist"""
    Base.metadata.create_all(bind=engine)
