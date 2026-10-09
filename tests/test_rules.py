"""ასისტენტის უფლებამოსილების ტესტები — მუხლები 4.3–4.6, 6.2, 6.4, 7.1, 12.3."""

from __future__ import annotations

from datetime import date

from src.core.policy_rules import evaluate_assistant_request
from tests.conftest import TODAY


def evaluate(repo, employee_id: str, code: str, start: date, end: date, **kwargs):
    return evaluate_assistant_request(
        employee=repo.get_employee(employee_id),
        leave_type=repo.get_leave_type(code),
        start=start,
        end=end,
        today=TODAY,
        calendar=repo.work_calendar(),
        balance=repo.get_balance(employee_id, start.year, code),
        existing=repo.active_requests(employee_id),
        **kwargs,
    )


def codes(result) -> list[str]:
    return [violation.code for violation in result.violations]


# დადებითი სცენარი 


def test_valid_annual_request_is_allowed(repo):
    """E1013 (TEC, 20 დღე ხელმისაწვდომი), ვადიანი და შეზღუდვების გარეშე."""
    result = evaluate(repo, "E1013", "ANNUAL", date(2026, 11, 16), date(2026, 11, 20))
    assert result.allowed is True, codes(result)
    assert result.days == 5
    assert result.leave_year == 2026


# მუხლი 4.4 წინასწარი შეტყობინება 


def test_short_notice_is_rejected(repo):
    result = evaluate(repo, "E1013", "ANNUAL", date(2026, 10, 20), date(2026, 10, 21))
    assert "NOTICE_PERIOD" in codes(result)


#მუხლი 4.3 გამოსაცდელი ვადა


def test_probation_blocks_annual_leave(repo):
    """E1004-ის გამოსაცდელი ვადა 30.11.2026-ს სრულდება."""
    result = evaluate(repo, "E1004", "ANNUAL", date(2026, 11, 16), date(2026, 11, 20))
    assert "PROBATION" in codes(result)


def test_probation_does_not_block_sick_leave(repo):
    """მუხლი 4.3: შეზღუდვა ავადმყოფობაზე არ ვრცელდება."""
    result = evaluate(repo, "E1004", "SICK", TODAY, TODAY)
    assert "PROBATION" not in codes(result)
    assert result.allowed is True, codes(result)


# მუხლი 4.5 უწყვეტი შვებულების მაქსიმუმი


def test_more_than_fifteen_working_days_in_one_request(repo):
    result = evaluate(repo, "E1013", "ANNUAL", date(2026, 11, 2), date(2026, 11, 27))
    assert "MAX_CONTINUOUS" in codes(result)


def test_chaining_requests_across_a_weekend_is_detected(repo):
    """E1003-ს 15.06–19.06 დამტკიცებული აქვს; 22.06-დან გაგრძელება
    ერთ უწყვეტ შვებულებად ითვლება."""
    result = evaluate(repo, "E1003", "ANNUAL", date(2026, 6, 22), date(2026, 7, 10))
    assert "CONTINUOUS_BLOCK" in codes(result) or "MAX_CONTINUOUS" in codes(result)


# მუხლი 4.6 შეზღუდული პერიოდები


def test_restricted_period_applies_to_audit_department(repo):
    """E1001 — AUD, 1–20 დეკემბერი შეზღუდულია."""
    result = evaluate(repo, "E1001", "ANNUAL", date(2026, 12, 7), date(2026, 12, 11))
    assert "RESTRICTED_PERIOD" in codes(result)


def test_restricted_period_does_not_apply_to_other_departments(repo):
    """E1009 — TEC, იგივე თარიღები დასაშვებია."""
    result = evaluate(repo, "E1009", "ANNUAL", date(2026, 12, 7), date(2026, 12, 11))
    assert "RESTRICTED_PERIOD" not in codes(result)
    assert result.allowed is True, codes(result)


#  მუხლი 5.1 ბალანსი


def test_insufficient_balance(repo):
    """E1002-ს 4 დღე აქვს დარჩენილი."""
    result = evaluate(repo, "E1002", "ANNUAL", date(2026, 11, 16), date(2026, 11, 20))
    assert "INSUFFICIENT_BALANCE" in codes(result)


# მუხლი 12.3 გადაფარვა, წლები, სახეები


def test_overlapping_dates_are_rejected(repo):
    """E1001-ს 09–11 ნოემბერი განხილვაში აქვს."""
    result = evaluate(repo, "E1001", "ANNUAL", date(2026, 11, 10), date(2026, 11, 12))
    assert "OVERLAP" in codes(result)


def test_next_year_dates_are_rejected(repo):
    result = evaluate(repo, "E1013", "ANNUAL", date(2027, 2, 1), date(2027, 2, 5))
    assert "NEXT_YEAR" in codes(result)


def test_request_spanning_two_years_must_be_split(repo):
    result = evaluate(repo, "E1013", "ANNUAL", date(2026, 12, 28), date(2027, 1, 8))
    assert codes(result) == ["CROSS_YEAR"]


def test_assistant_does_not_create_study_bereavement_or_parental(repo):
    for code in ("STUDY", "BEREAVEMENT", "PARENTAL"):
        result = evaluate(repo, "E1009", code, date(2026, 12, 7), date(2026, 12, 8))
        assert codes(result) == ["TYPE_NOT_SUPPORTED"], code
        assert result.violations[0].redirect in {"portal", "hr"}


#მუხლები 6.2 და 6.4 ავადმყოფობა


def test_sick_leave_registered_today_is_allowed(repo):
    result = evaluate(repo, "E1001", "SICK", TODAY, TODAY)
    assert result.allowed is True, codes(result)


def test_sick_leave_registered_too_late(repo):
    result = evaluate(repo, "E1001", "SICK", date(2026, 10, 12), date(2026, 10, 13))
    assert "SICK_LATE" in codes(result)


def test_future_sick_leave_needs_a_known_period(repo):
    result = evaluate(repo, "E1001", "SICK", date(2026, 11, 2), date(2026, 11, 3))
    assert "SICK_FUTURE_UNCONFIRMED" in codes(result)

    confirmed = evaluate(
        repo, "E1001", "SICK", date(2026, 11, 2), date(2026, 11, 3),
        sick_period_known=True,
    )
    assert confirmed.allowed is True, codes(confirmed)


def test_sick_request_over_the_paid_limit_goes_to_hr(repo):
    """E1001-ს 8 ანაზღაურებადი დღე აქვს; 10 დღეს ასისტენტი არ ქმნის."""
    result = evaluate(repo, "E1001", "SICK", date(2026, 10, 19), date(2026, 10, 30))
    violation = next(v for v in result.violations if v.code == "SICK_PAID_LIMIT")
    assert violation.redirect == "hr"
    assert "აკრძალული არ არის" in violation.message


# მუხლები 7.1 და 7.2უხელფასო შვებულება


def test_unpaid_requires_a_reason(repo):
    result = evaluate(repo, "E1013", "UNPAID", date(2026, 12, 1), date(2026, 12, 5))
    assert "REASON_REQUIRED" in codes(result)

    with_reason = evaluate(
        repo, "E1013", "UNPAID", date(2026, 12, 1), date(2026, 12, 5),
        reason="ოჯახური გარემოება",
    )
    assert with_reason.allowed is True, codes(with_reason)
    assert with_reason.days == 5


def test_unpaid_over_thirty_calendar_days(repo):
    result = evaluate(
        repo, "E1013", "UNPAID", date(2026, 11, 2), date(2026, 12, 15),
        reason="პირადი",
    )
    assert "UNPAID_LIMIT" in codes(result)
