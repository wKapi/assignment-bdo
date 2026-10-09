"""პროექტის კონფიგურაცია — გზები და გარემოს ცვლადები ერთ ადგილას.

ყველა მოდული გზებს მხოლოდ აქედან იღებს. აბსოლუტური გზები რეპოზიტორიის
ფესვზეა მიბმული და არა მიმდინარე საქაღალდეზე, რადგან MCP სერვერს კლიენტი
სხვა cwd-დან უშვებს.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


def _resolve(value: str) -> Path:
    """ფარდობით გზას რეპოზიტორიის ფესვთან აბამს."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


# --- გზები -----------------------------------------------------------------

DATA_DIR = ROOT / "data"
DOCUMENTS_DIR = ROOT / "documents"
SCHEMA_PATH = ROOT / "src" / "db" / "schema.sql"

DATABASE_PATH = _resolve(os.getenv("DATABASE_PATH", "./northstar.db"))
INDEX_DIR = _resolve(os.getenv("INDEX_DIR", "./.index"))

# --- „დღევანდელი“ თარიღი ---------------------------------------------------
# მოწოდებული მონაცემები 2026 წლის 19 ოქტომბრის მდგომარეობას ასახავს
# (data_dictionary.pdf). ყველა წესი ამ თარიღზე უნდა დაიანგარიშდეს, თორემ
# ტესტები ყოველ დღე სხვა შედეგს მოგვცემს.
APP_TODAY = date.fromisoformat(os.getenv("APP_TODAY", "2026-10-19"))

# --- სესია -----------------------------------------------------------------

CURRENT_EMPLOYEE_ID = os.getenv("CURRENT_EMPLOYEE_ID", "E1001")
CURRENT_ROLE = os.getenv("CURRENT_ROLE", "employee")

# --- LLM -------------------------------------------------------------------

# პროვაიდერი: mock (გასაღების გარეშე) ან anthropic
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
