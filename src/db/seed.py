"""CSV-ებიდან SQLite ბაზის შევსება.

გაშვება რეპოზიტორიის ფესვიდან:

    python -m src.db.seed

ბაზა ყოველ ჯერზე თავიდან იქმნება — `data/` საქაღალდის ფაილები
ერთადერთი წყაროა და მათ არ ვცვლით.

თარიღების ფორმატზე: `data_dictionary.pdf` ამბობს, რომ თარიღები ISO
ფორმატშია, თუმცა რეალურად CSV-ებში `M/D/YYYY`-ია და მხოლოდ
`leave_requests.created_at` არის ISO 8601. ამიტომ პარსერი ორივეს იღებს.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime
from pathlib import Path

from src.config import DATA_DIR, DATABASE_PATH
from src.core.workdays import WorkCalendar
from src.db.repository import bulk_insert, connect, create_schema


def parse_date(value: str) -> str:
    """`M/D/YYYY` ან `YYYY-MM-DD` → ISO ტექსტი."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("ცარიელი თარიღი")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    month, day, year = (int(part) for part in raw.split("/"))
    return date(year, month, day).isoformat()


def parse_timestamp(value: str) -> str:
    """`created_at` უკვე ISO 8601-ია; ვამოწმებთ და ვაბრუნებთ."""
    return datetime.fromisoformat(value.strip()).isoformat(timespec="seconds")


def _optional(value: str) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _optional_int(value: str) -> int | None:
    cleaned = (value or "").strip()
    return int(cleaned) if cleaned else None


def _rows(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_employees(conn: sqlite3.Connection) -> int:
    rows = [
        (
            r["employee_id"],
            r["full_name"],
            r["email"],
            r["department_code"],
            r["department_name"],
            r["job_title"],
            r["employment_type"],
            parse_date(r["start_date"]),
            parse_date(r["probation_end_date"]) if _optional(r["probation_end_date"]) else None,
            _optional(r["manager_id"]),
            r["status"],
        )
        for r in _rows("employees.csv")
    ]
    return bulk_insert(
        conn,
        "employees",
        (
            "employee_id", "full_name", "email", "department_code",
            "department_name", "job_title", "employment_type", "start_date",
            "probation_end_date", "manager_id", "status",
        ),
        rows,
    )


def load_leave_types(conn: sqlite3.Connection) -> int:
    rows = [
        (
            r["code"],
            r["name"],
            _optional(r["day_unit"]),
            _optional_int(r["annual_limit_days"]),
            int(r["self_service"]),
            int(r["assistant_supported"]),
            _optional(r["policy_reference"]),
        )
        for r in _rows("leave_types.csv")
    ]
    return bulk_insert(
        conn,
        "leave_types",
        (
            "code", "name", "day_unit", "annual_limit_days",
            "self_service", "assistant_supported", "policy_reference",
        ),
        rows,
    )


def load_entitlements(conn: sqlite3.Connection) -> int:
    rows = [
        (
            r["employee_id"],
            int(r["year"]),
            r["leave_type"],
            int(r["entitled_days"]),
            int(r["carried_over_days"] or 0),
        )
        for r in _rows("leave_entitlements.csv")
    ]
    return bulk_insert(
        conn,
        "leave_entitlements",
        ("employee_id", "year", "leave_type", "entitled_days", "carried_over_days"),
        rows,
    )


def load_requests(conn: sqlite3.Connection) -> int:
    rows = [
        (
            int(r["request_id"]),
            r["employee_id"],
            r["leave_type"],
            parse_date(r["start_date"]),
            parse_date(r["end_date"]),
            int(r["days"]),
            r["status"],
            parse_timestamp(r["created_at"]),
            r["created_via"],
            _optional(r["comment"]),
        )
        for r in _rows("leave_requests.csv")
    ]
    return bulk_insert(
        conn,
        "leave_requests",
        (
            "request_id", "employee_id", "leave_type", "start_date", "end_date",
            "days", "status", "created_at", "created_via", "comment",
        ),
        rows,
    )


def load_holidays(conn: sqlite3.Connection) -> int:
    rows = [(parse_date(r["date"]), r["name"]) for r in _rows("public_holidays.csv")]
    return bulk_insert(conn, "public_holidays", ("date", "name"), rows)


# --- შემოწმებები


def verify(conn: sqlite3.Connection) -> list[str]:
    """ჩატვირთვის შემდგომი კონტროლი: FK-ები და დღეების გადათვლა."""
    problems: list[str] = []

    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    for row in broken:
        problems.append(f"უცხო გასაღების დარღვევა: {tuple(row)}")

    holidays = [
        date.fromisoformat(r["date"])
        for r in conn.execute("SELECT date FROM public_holidays")
    ]
    calendar = WorkCalendar(holidays)

    units = {
        r["code"]: r["day_unit"]
        for r in conn.execute("SELECT code, day_unit FROM leave_types")
    }

    rows = conn.execute(
        "SELECT request_id, leave_type, start_date, end_date, days FROM leave_requests"
    ).fetchall()
    for row in rows:
        unit = units.get(row["leave_type"])
        if unit is None:
            continue
        expected = calendar.count_days(
            date.fromisoformat(row["start_date"]),
            date.fromisoformat(row["end_date"]),
            unit,
        )
        if expected != row["days"]:
            problems.append(
                f"მოთხოვნა #{row['request_id']}: CSV-ში days={row['days']}, "
                f"გადათვლით {expected} ({unit})"
            )

    return problems


def seed(database_path: Path | None = None) -> None:
    target = Path(database_path or DATABASE_PATH)
    conn = connect(target)
    try:
        # თანამშრომლების manager_id თავად employees-ზე მიუთითებს და
        # ხელმძღვანელები ფაილში გვიან ჩნდებიან, ამიტომ ჩატვირთვისას
        # შემოწმებას ვთიშავთ და ბოლოს მთლიანად ვამოწმებთ.
        create_schema(conn)
        conn.execute("PRAGMA foreign_keys = OFF")

        counts = {
            "employees": load_employees(conn),
            "leave_types": load_leave_types(conn),
            "public_holidays": load_holidays(conn),
            "leave_entitlements": load_entitlements(conn),
            "leave_requests": load_requests(conn),
        }
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

        print(f"ბაზა: {target}")
        for table, count in counts.items():
            print(f"  {table:<20} {count:>4} ჩანაწერი")

        problems = verify(conn)
        if problems:
            print("\n⚠ შეუსაბამობები:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print("\n✓ შემოწმება გავლილია: FK-ები წესრიგშია, "
                  "დღეების რაოდენობა პოლიტიკის დათვლას ემთხვევა.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
