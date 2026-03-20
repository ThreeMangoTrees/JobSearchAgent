from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app.Model.base import Base
import app.Model.company_career_page  # noqa: F401
from app.config import DATABASE_ECHO, DATABASE_URL


def get_engine(database_url: str | None = None) -> Engine:
    resolved_database_url = (database_url or DATABASE_URL).strip()
    if not resolved_database_url:
        raise ValueError("DATABASE_URL is not configured.")

    return create_engine(
        resolved_database_url,
        echo=DATABASE_ECHO,
        future=True,
    )


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def create_tables(database_url: str | None = None) -> None:
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    create_tables()
