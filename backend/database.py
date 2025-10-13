# app/database.py
# SQLAlchemy session/engine setup for FastAPI.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

#   sqlite:///./newsfaces.db
#   postgresql+psycopg://user:pass@localhost:5432/newsfaces
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./newsfaces.db")


engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# get a DB session per request and close it afterwards.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
