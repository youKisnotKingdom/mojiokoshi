from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

_is_postgres = str(settings.database_url).startswith("postgresql")
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **( {"pool_size": 10, "max_overflow": 20} if _is_postgres else {} ),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
