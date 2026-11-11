from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def database_session_options(statement_timeout_ms: int, idle_in_transaction_timeout_ms: int) -> str:
    options = []
    if statement_timeout_ms:
        options.append(f"-c statement_timeout={statement_timeout_ms}")
    if idle_in_transaction_timeout_ms:
        options.append(f"-c idle_in_transaction_session_timeout={idle_in_transaction_timeout_ms}")
    return " ".join(options)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    options = database_session_options(settings.db_statement_timeout_ms, settings.db_idle_in_transaction_timeout_ms)
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={"options": options} if options else {},
    )


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
