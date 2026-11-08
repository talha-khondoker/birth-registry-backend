from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# DATABASE_URL = "sqlite:///./birth_registry.db"
DATABASE_URL = "postgresql://postgres.azwdoipecpnwrooktkuf:TalhaBirth2026@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
