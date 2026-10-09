"""ბაზასთან მუშაობის ერთადერთი ფენა.

ზემოთ მდებარე ფენები (MCP ხელსაწყოები, CLI) SQL-ს არ წერენ — ისინი
`Repository`-ს ელაპარაკებიან და `src.core`-ის dataclass-ებს იღებენ.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from src.config import DATABASE_PATH, SCHEMA_PATH
from src.core.balance import LeaveBalance, compute_balance
from src.core.policy_rules import (
    ACTIVE_STATUSES,
    EmployeeInfo,
    ExistingRequest,
    LeaveTypeInfo,
)
from src.core.workdays import WorkCalendar


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """ხსნის კავშირს და რთავს უცხო გასაღებების შემოწმებას."""
    conn = sqlite3.connect(str(path or DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """ქმნის ცხრილებს `schema.sql`-ის მიხედვით (არსებულს შლის)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._calendar: WorkCalendar | None = None

    # უქმე დღეები

    def work_calendar(self) -> WorkCalendar:
        """სამუშაო კალენდარი HR სისტემის უქმე დღეებით (მუხლი 2.3)."""
        if self._calendar is None:
            rows = self.conn.execute("SELECT date FROM public_holidays").fetchall()
            self._calendar = WorkCalendar(date.fromisoformat(r["date"]) for r in rows)
        return self._calendar

    #თანამშრომლები

    def get_employee(self, employee_id: str) -> EmployeeInfo | None:
        row = self.conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        if row is None:
            return None
        return EmployeeInfo(
            employee_id=row["employee_id"],
            department_code=row["department_code"],
            start_date=date.fromisoformat(row["start_date"]),
            probation_end_date=_as_date(row["probation_end_date"]),
            status=row["status"],
        )

    def get_employee_row(self, employee_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()

    #შვებულების სახეები

    @staticmethod
    def _leave_type(row: sqlite3.Row) -> LeaveTypeInfo:
        return LeaveTypeInfo(
            code=row["code"],
            name=row["name"],
            day_unit=row["day_unit"],
            annual_limit_days=row["annual_limit_days"],
            self_service=bool(row["self_service"]),
            assistant_supported=bool(row["assistant_supported"]),
            policy_reference=row["policy_reference"],
        )

    def get_leave_type(self, code: str) -> LeaveTypeInfo | None:
        row = self.conn.execute(
            "SELECT * FROM leave_types WHERE code = ?", (code,)
        ).fetchone()
        return self._leave_type(row) if row else None

    def list_leave_types(self) -> list[LeaveTypeInfo]:
        rows = self.conn.execute("SELECT * FROM leave_types ORDER BY code").fetchall()
        return [self._leave_type(r) for r in rows]

    #მოთხოვნები

    @staticmethod
    def _request(row: sqlite3.Row) -> ExistingRequest:
        return ExistingRequest(
            request_id=row["request_id"],
            leave_type=row["leave_type"],
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            days=row["days"],
            status=row["status"],
        )

    def list_requests(
        self,
        *,
        employee_id: str | None = None,
        statuses: Sequence[str] | None = None,
        leave_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ExistingRequest]:
        """მოთხოვნების სია ფილტრებით. თარიღის ფილტრი გადაკვეთაზე მუშაობს."""
        sql = ["SELECT * FROM leave_requests WHERE 1 = 1"]
        params: list[object] = []

        if employee_id:
            sql.append("AND employee_id = ?")
            params.append(employee_id)
        if leave_type:
            sql.append("AND leave_type = ?")
            params.append(leave_type)
        if statuses:
            sql.append(f"AND status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if date_from:
            sql.append("AND end_date >= ?")
            params.append(date_from.isoformat())
        if date_to:
            sql.append("AND start_date <= ?")
            params.append(date_to.isoformat())

        sql.append("ORDER BY start_date, request_id")
        rows = self.conn.execute(" ".join(sql), params).fetchall()
        return [self._request(r) for r in rows]

    def active_requests(self, employee_id: str) -> list[ExistingRequest]:
        """დამტკიცებული და განხილვაში მყოფი მოთხოვნები (მუხლი 5.1)."""
        return self.list_requests(
            employee_id=employee_id, statuses=sorted(ACTIVE_STATUSES)
        )

    def create_request(
        self,
        *,
        employee_id: str,
        leave_type: str,
        start: date,
        end: date,
        days: int,
        created_at: datetime,
        created_via: str = "assistant",
        comment: str | None = None,
    ) -> int:
        """ქმნის მოთხოვნას. ასისტენტით შექმნილი ყოველთვის `pending`-ია."""
        cursor = self.conn.execute(
            """
            INSERT INTO leave_requests
                (employee_id, leave_type, start_date, end_date, days,
                 status, created_at, created_via, comment)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                employee_id,
                leave_type,
                start.isoformat(),
                end.isoformat(),
                days,
                created_at.isoformat(timespec="seconds"),
                created_via,
                comment,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def set_status(
        self,
        *,
        request_id: int,
        status: str,
        decided_by: str | None,
        decided_at: datetime,
    ) -> bool:
        """სტატუსის შეცვლა — მხოლოდ HR/ხელმძღვანელის არხისთვის (მუხლი 12.3)."""
        cursor = self.conn.execute(
            """
            UPDATE leave_requests
               SET status = ?, decided_by = ?, decided_at = ?
             WHERE request_id = ? AND status = 'pending'
            """,
            (status, decided_by, decided_at.isoformat(timespec="seconds"), request_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # ბალანსი

    def get_balance(
        self, employee_id: str, year: int, leave_type: str
    ) -> LeaveBalance:
        """მუხლი 5.1-ის ფორმულა ბაზის მონაცემებზე."""
        entitlement = self.conn.execute(
            """
            SELECT entitled_days, carried_over_days
              FROM leave_entitlements
             WHERE employee_id = ? AND year = ? AND leave_type = ?
            """,
            (employee_id, year, leave_type),
        ).fetchone()

        totals = self.conn.execute(
            """
            SELECT status, SUM(days) AS total
              FROM leave_requests
             WHERE employee_id = ?
               AND leave_type = ?
               AND CAST(strftime('%Y', start_date) AS INTEGER) = ?
               AND status IN ('approved', 'pending')
             GROUP BY status
            """,
            (employee_id, leave_type, year),
        ).fetchall()
        by_status = {r["status"]: r["total"] or 0 for r in totals}

        return compute_balance(
            employee_id=employee_id,
            year=year,
            leave_type=leave_type,
            entitled_days=entitlement["entitled_days"] if entitlement else None,
            carried_over_days=entitlement["carried_over_days"] if entitlement else None,
            approved_days=by_status.get("approved", 0),
            pending_days=by_status.get("pending", 0),
        )

    #შეთავაზებები

    def save_proposal(
        self,
        *,
        proposal_id: str,
        conversation_id: str,
        employee_id: str,
        leave_type: str,
        start: date,
        end: date,
        days: int,
        reason: str | None,
        created_at: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO leave_proposals
                (proposal_id, conversation_id, employee_id, leave_type,
                 start_date, end_date, days, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (proposal_id) DO UPDATE SET
                leave_type = excluded.leave_type,
                start_date = excluded.start_date,
                end_date   = excluded.end_date,
                days       = excluded.days,
                reason     = excluded.reason
            WHERE leave_proposals.confirmed_at IS NULL
            """,
            (
                proposal_id,
                conversation_id,
                employee_id,
                leave_type,
                start.isoformat(),
                end.isoformat(),
                days,
                reason,
                created_at.isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def get_proposal(self, proposal_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM leave_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()

    def confirm_proposal(
        self, *, proposal_id: str, request_id: int, confirmed_at: datetime
    ) -> None:
        self.conn.execute(
            """
            UPDATE leave_proposals
               SET request_id = ?, confirmed_at = ?
             WHERE proposal_id = ? AND confirmed_at IS NULL
            """,
            (request_id, confirmed_at.isoformat(timespec="seconds"), proposal_id),
        )
        self.conn.commit()

    #აუდიტი

    def log(
        self,
        *,
        ts: datetime,
        actor_role: str,
        actor_id: str | None,
        tool: str,
        args: dict | None = None,
        result: str | None = None,
    ) -> None:
        """ხელსაწყოს გამოძახების ჟურნალი.

        მუხლი 12.4: ჯანმრთელობის დეტალები არ იწერება — `args`-ში მხოლოდ
        სახე, თარიღები და იდენტიფიკატორები უნდა გადმოვიდეს.
        """
        self.conn.execute(
            """
            INSERT INTO audit_log (ts, actor_role, actor_id, tool, args_json, result)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ts.isoformat(timespec="seconds"),
                actor_role,
                actor_id,
                tool,
                json.dumps(args, ensure_ascii=False) if args is not None else None,
                result,
            ),
        )
        self.conn.commit()


def bulk_insert(
    conn: sqlite3.Connection, table: str, columns: Sequence[str], rows: Iterable[tuple]
) -> int:
    """seed-ისთვის: ერთი ტრანზაქციით ჩაწერა."""
    placeholders = ",".join("?" * len(columns))
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    cursor = conn.executemany(sql, rows)
    return cursor.rowcount
