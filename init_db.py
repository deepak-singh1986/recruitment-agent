import os
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy_utils import database_exists, create_database
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Create engine
engine = create_engine(DATABASE_URL, echo=True)
if not database_exists(engine.url):
    create_database(engine.url)

metadata = MetaData()

# === Tables ===

# Job Descriptions
job_descriptions = Table(
    "job_descriptions", metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String(255), nullable=False),
    Column("file_path", String(500), nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow)
)

# Candidates
candidates = Table(
    "candidates", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("phone", String(20), nullable=False),
    Column("file_path", String(500), nullable=False),
    Column("shortlisted", Boolean, default=False),
    Column("created_at", DateTime, default=datetime.utcnow)
)

# Interviews
interviews = Table(
    "interviews", metadata,
    Column("id", Integer, primary_key=True),
    Column("candidate_id", Integer, ForeignKey("candidates.id")),
    Column("job_id", Integer, ForeignKey("job_descriptions.id")),
    Column("status", String(50), default="pending"),  # pending, calling, completed
    Column("result", String(50)),  # selected, rejected
    Column("report_path", String(500)),  # link to PDF/HTML
    Column("created_at", DateTime, default=datetime.utcnow)
)

# Interview QA logs
interview_logs = Table(
    "interview_logs", metadata,
    Column("id", Integer, primary_key=True),
    Column("interview_id", Integer, ForeignKey("interviews.id")),
    Column("question", Text, nullable=False),
    Column("answer", Text),
    Column("evaluation", Text),
    Column("created_at", DateTime, default=datetime.utcnow)
)

# Create tables
metadata.create_all(engine)

print("✅ Database tables created successfully.")

# to run this script
# python init_db.py
