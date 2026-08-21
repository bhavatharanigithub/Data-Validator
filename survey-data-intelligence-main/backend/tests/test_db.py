from sqlalchemy import inspect

from app.db import engine, init_db


def test_init_db_creates_sqlite_file() -> None:
    init_db()
    inspector = inspect(engine)
    assert inspector is not None
    assert "batches" in inspector.get_table_names()
    engine.connect().close()
