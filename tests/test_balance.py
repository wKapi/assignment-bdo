"""ბალანსის ტესტები — პოლიტიკის მუხლები 4.7, 5.1, 5.3, 6.4."""

from __future__ import annotations

import pytest

from src.core.balance import compute_balance


def _balance(**kwargs):
    defaults = dict(
        employee_id="E1001",
        year=2026,
        leave_type="ANNUAL",
        entitled_days=25,
        carried_over_days=0,
        approved_days=0,
        pending_days=0,
    )
    return compute_balance(**{**defaults, **kwargs})


def test_formula_from_article_5_1():
    result = _balance(carried_over_days=3, approved_days=15, pending_days=3)
    assert result.available_days == 10
    assert result.approved_days == 15
    assert result.pending_days == 3


def test_carried_over_is_the_initial_amount_not_a_remainder():
    """მუხლი 4.7: უკვე გამოყენებული გადმოტანილი დღეები ველში რჩება და
    დამტკიცებულ მოთხოვნებში ცალკე იქვითება — ორმაგად არ უნდა ჩამოიწეროს."""
    result = _balance(entitled_days=25, carried_over_days=3, approved_days=3)
    assert result.available_days == 25


def test_sick_negative_result_is_clamped_to_zero():
    """მუხლი 5.1 + 6.4: უარყოფითი ბალანსი 0-ია, მაგრამ აღრიცხვა არ იკრძალება."""
    result = _balance(leave_type="SICK", entitled_days=10, approved_days=12)
    assert result.available_days == 0
    assert result.clamped is True
    assert "6.4" in (result.note or "")


def test_types_without_annual_balance():
    """მუხლი 5.1: გლოვისა და მშობლის შვებულებას წლიური ბალანსი არ აქვს."""
    for code in ("BEREAVEMENT", "PARENTAL"):
        result = _balance(leave_type=code, entitled_days=None)
        assert result.tracked is False
        assert result.available_days is None


def test_missing_entitlement_is_unknown_not_zero():
    """მუხლი 5.3: ჩანაწერის არარსებობა ნულოვან ბალანსს არ ნიშნავს."""
    result = _balance(year=2027, entitled_days=None)
    assert result.known is False
    assert result.available_days is None
    assert "HR" in (result.note or "") or "ადამიანური" in (result.note or "")



@pytest.mark.parametrize(
    ("employee_id", "leave_type", "expected"),
    [
        ("E1001", "ANNUAL", 10),  # 25+3 − 15 დამტკიცებული − 3 განხილვაში
        ("E1001", "SICK", 8),  # 10 − 2
        ("E1002", "ANNUAL", 4),  # 24 − 20; უარყოფილი 5 არ ითვლება
        ("E1003", "ANNUAL", 15),
        ("E1009", "STUDY", 4),
        ("E1013", "ANNUAL", 20),
        ("E1004", "ANNUAL", 8),  # მუხლი 4.2 — სექტემბრიდან დაწყებული
    ],
)
def test_balances_from_seeded_data(repo, employee_id, leave_type, expected):
    balance = repo.get_balance(employee_id, 2026, leave_type)
    assert balance.available_days == expected


def test_cancelled_and_rejected_requests_are_ignored(repo):
    """E1001-ის გაუქმებული 2 დღე და E1002-ის უარყოფილი 5 დღე არ ითვლება."""
    assert repo.get_balance("E1001", 2026, "ANNUAL").approved_days == 15
    assert repo.get_balance("E1002", 2026, "ANNUAL").approved_days == 20


def test_balance_for_year_without_entitlements(repo):
    assert repo.get_balance("E1001", 2027, "ANNUAL").known is False
