"""MCP ხელსაწყოების ტესტები — როლები, იდემპოტენტურობა, პოლიტიკის დაცვა."""

from __future__ import annotations

import pytest

from src.mcp_server import tools
from src.mcp_server.auth import PermissionDenied, Principal, Role

EMPLOYEE = Principal(role=Role.EMPLOYEE, employee_id="E1013")
OTHER_EMPLOYEE = Principal(role=Role.EMPLOYEE, employee_id="E1001")
HR = Principal(role=Role.HR, employee_id="E1007")


def _count_requests(repo, employee_id: str) -> int:
    return repo.conn.execute(
        "SELECT COUNT(*) FROM leave_requests WHERE employee_id = ?", (employee_id,)
    ).fetchone()[0]


# ტიპების სია


def test_list_leave_types_exposes_assistant_scope(repo):
    payload = tools.list_leave_types(repo, EMPLOYEE)
    by_code = {t["code"]: t for t in payload["leave_types"]}

    assert len(by_code) == 6
    for code in ("ANNUAL", "SICK", "UNPAID"):
        assert by_code[code]["assistant_can_create"] is True
    for code in ("BEREAVEMENT", "STUDY", "PARENTAL"):
        assert by_code[code]["assistant_can_create"] is False
    assert by_code["UNPAID"]["day_unit"] == "calendar"
    assert by_code["PARENTAL"]["day_unit"] is None


# კონფიდენციალურობა (მუხლები 5.2, 12.3)


def test_employee_sees_only_own_balance(repo):
    own = tools.get_leave_balance(repo, EMPLOYEE, leave_type="ANNUAL")
    assert own["employee_id"] == "E1013"
    assert own["available_days"] == 20

    with pytest.raises(PermissionDenied):
        tools.get_leave_balance(
            repo, EMPLOYEE, leave_type="ANNUAL", employee_id="E1001"
        )


def test_employee_cannot_list_another_persons_requests(repo):
    with pytest.raises(PermissionDenied):
        tools.list_leave_requests(repo, EMPLOYEE, employee_id="E1001")


def test_hr_can_read_any_employee(repo):
    payload = tools.get_leave_balance(
        repo, HR, leave_type="ANNUAL", employee_id="E1002"
    )
    assert payload["available_days"] == 4


def test_balance_defaults_to_current_leave_year(repo):
    payload = tools.get_leave_balance(repo, EMPLOYEE, leave_type="ANNUAL")
    assert payload["year"] == 2026


# მოთხოვნების სია


def test_list_requests_filters(repo):
    all_requests = tools.list_leave_requests(repo, OTHER_EMPLOYEE)
    assert all_requests["count"] == 5

    pending = tools.list_leave_requests(repo, OTHER_EMPLOYEE, status="pending")
    assert [r["request_id"] for r in pending["requests"]] == [5]

    windowed = tools.list_leave_requests(
        repo, OTHER_EMPLOYEE, date_from="2026-07-01", date_to="2026-07-31"
    )
    assert [r["request_id"] for r in windowed["requests"]] == [4]


#შემოწმება და შექმნა 


def test_preview_does_not_write_a_request(repo):
    before = _count_requests(repo, "E1013")
    preview = tools.preview_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
    )

    assert preview["can_create"] is True
    assert preview["days"] == 5
    assert preview["proposal_id"]
    assert preview["confirmation_required"] is True
    assert _count_requests(repo, "E1013") == before


def test_preview_explains_refusal_with_policy_reference(repo):
    preview = tools.preview_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-10-20", end_date="2026-10-21",
    )
    assert preview["can_create"] is False
    assert preview["proposal_id"] is None

    violation = preview["violations"][0]
    assert violation["code"] == "NOTICE_PERIOD"
    assert "4.4" in violation["policy_reference"]
    assert violation["redirect_to"] == "manager"


def test_created_request_is_pending_and_from_assistant(repo):
    result = tools.create_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
    )

    assert result["created"] is True
    assert result["request"]["status"] == "pending"
    assert result["request"]["created_via"] == "assistant"
    assert result["request"]["days"] == 5


def test_new_pending_request_reduces_available_balance(repo):
    tools.create_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
    )
    balance = tools.get_leave_balance(repo, EMPLOYEE, leave_type="ANNUAL")
    assert balance["pending_days"] == 5
    assert balance["available_days"] == 15


def test_refused_request_is_not_written(repo):
    before = _count_requests(repo, "E1002")
    hr_view = Principal(role=Role.EMPLOYEE, employee_id="E1002")

    result = tools.create_leave_request(
        repo, hr_view, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
    )

    assert result["created"] is False
    assert result["request_id"] is None
    assert "INSUFFICIENT_BALANCE" in [v["code"] for v in result["violations"]]
    assert _count_requests(repo, "E1002") == before



def test_confirming_the_same_proposal_twice_creates_one_request(repo):
    preview = tools.preview_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
        conversation_id="conv-1",
    )
    proposal_id = preview["proposal_id"]

    first = tools.create_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
        proposal_id=proposal_id, conversation_id="conv-1",
    )
    second = tools.create_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
        proposal_id=proposal_id, conversation_id="conv-1",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["already_confirmed"] is True
    assert second["request_id"] == first["request_id"]
    assert _count_requests(repo, "E1013") == 2  # ერთი seed-იდან + ერთი ახალი


def test_proposal_of_another_employee_is_rejected(repo):
    preview = tools.preview_leave_request(
        repo, EMPLOYEE, leave_type="ANNUAL",
        start_date="2026-11-16", end_date="2026-11-20",
    )
    with pytest.raises(ValueError, match="სხვა თანამშრომელს"):
        tools.create_leave_request(
            repo, HR, leave_type="ANNUAL",
            start_date="2026-11-16", end_date="2026-11-20",
            employee_id="E1002", proposal_id=preview["proposal_id"],
        )


# UNPAID და sick leave


def test_unpaid_reason_is_stored_in_comment(repo):
    result = tools.create_leave_request(
        repo, EMPLOYEE, leave_type="UNPAID",
        start_date="2026-12-01", end_date="2026-12-05",
        reason="ოჯახური გარემოება",
    )
    assert result["created"] is True
    assert result["request"]["comment"] == "ოჯახური გარემოება"


def test_sick_request_never_stores_a_comment(repo):
    """მუხლი 12.4: ჯანმრთელობის დეტალები არ გროვდება."""
    result = tools.create_leave_request(
        repo, OTHER_EMPLOYEE, leave_type="SICK",
        start_date="2026-10-19", end_date="2026-10-19",
        reason="აქ მედიცინური დეტალი არ უნდა შევიდეს",
    )
    assert result["created"] is True
    assert result["request"]["comment"] is None


# გადაწყვეტილებები


def test_assistant_cannot_decide_or_cancel(repo):
    with pytest.raises(PermissionDenied):
        tools.decide_leave_request(repo, EMPLOYEE, request_id=5, decision="approve")
    with pytest.raises(PermissionDenied):
        tools.cancel_leave_request(repo, EMPLOYEE, request_id=5)


def test_hr_approves_a_pending_request(repo):
    result = tools.decide_leave_request(
        repo, HR, request_id=5, decision="approve", decided_by="E1010"
    )
    assert result["updated"] is True
    assert result["request"]["status"] == "approved"
    assert result["request"]["decided_by"] == "E1010"


def test_hr_cannot_decide_an_already_closed_request(repo):
    """#8 უკვე უარყოფილია — მეორედ გადაწყვეტილება არ მიიღება."""
    result = tools.decide_leave_request(repo, HR, request_id=8, decision="approve")
    assert result["updated"] is False


def test_hr_cancels_a_pending_request(repo):
    result = tools.cancel_leave_request(repo, HR, request_id=5)
    assert result["updated"] is True
    assert result["status"] == "cancelled"


def test_invalid_decision_value(repo):
    with pytest.raises(ValueError, match="approve"):
        tools.decide_leave_request(repo, HR, request_id=5, decision="maybe")


# აუდიტი


def test_tool_calls_are_logged(repo):
    tools.get_leave_balance(repo, EMPLOYEE, leave_type="ANNUAL")
    row = repo.conn.execute(
        "SELECT tool, actor_role, args_json FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert row["tool"] == "get_leave_balance"
    assert row["actor_role"] == "employee"
    assert "E1013" in row["args_json"]


def test_audit_log_never_stores_the_reason_text(repo):
    tools.create_leave_request(
        repo, EMPLOYEE, leave_type="UNPAID",
        start_date="2026-12-01", end_date="2026-12-05",
        reason="პირადი დეტალი",
    )
    logged = repo.conn.execute("SELECT args_json FROM audit_log").fetchall()
    assert all("პირადი დეტალი" not in (r["args_json"] or "") for r in logged)
