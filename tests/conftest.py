
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from src.core.workdays import WorkCalendar
from src.db.repository import Repository, connect
from src.db.seed import seed

# მოწოდებული მონაცემების „დღევანდელი“ თარიღი (data_dictionary.pdf)
TODAY = date(2026, 10, 19)


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory) -> Path:
    """ერთხელ შევსებული ბაზა, რომელიც შემდეგ თითოეულ ტესტს ეასლება."""
    path = tmp_path_factory.mktemp("db") / "template.db"
    seed(path)
    return path


@pytest.fixture
def repo(seeded_template, tmp_path) -> Repository:
    """ყოველი ტესტისთვის ბაზის ახალი ასლი — ჩაწერა სხვებს არ შეეხება."""
    path = tmp_path / "test.db"
    shutil.copy(seeded_template, path)
    conn = connect(path)
    try:
        yield Repository(conn)
    finally:
        conn.close()


@pytest.fixture
def plain_calendar() -> WorkCalendar:
    """უქმე დღეების გარეშე — სუფთა ორშაბათი–პარასკევი."""
    return WorkCalendar([])


@pytest.fixture(scope="session")
def retriever_for_cli():
    """რეალური ინდექსი CLI-ის ნაკადების ტესტებისთვის."""
    from src.rag.index import build_index
    from src.rag.retriever import Retriever

    import tempfile

    index_dir = Path(tempfile.mkdtemp(prefix="cli-index-"))
    build_index(index_dir=index_dir)
    return Retriever(index_dir=index_dir)
