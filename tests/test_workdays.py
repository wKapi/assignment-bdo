"""დღეების დათვლის ტესტები — პოლიტიკის მუხლები 2.2, 4.4, 4.5."""

from __future__ import annotations

from datetime import date

import pytest

from src.core.workdays import (
    UnknownDayUnit,
    WorkCalendar,
    periods_overlap,
    spans_multiple_years,
)

# 2026 წლის ივნისი: 1 რიცხვი ორშაბათია დამაგალითებისთვის მოსახერხებელი
MON_JUN_1 = date(2026, 6, 1)
TUE_JUN_2 = date(2026, 6, 2)
FRI_JUN_5 = date(2026, 6, 5)
MON_JUN_8 = date(2026, 6, 8)
TUE_JUN_9 = date(2026, 6, 9)


def test_article_2_2_example_skips_weekend_and_holiday():
    """მუხლი 2.2-ის მაგალითი: ორშაბათიდან მომდევნო ორშაბათამდე = 5 დღე."""
    calendar = WorkCalendar([TUE_JUN_2])  # სამშაბათი უქმეა
    assert calendar.count_working_days(MON_JUN_1, MON_JUN_8) == 5


def test_calendar_days_count_every_day():
    """მუხლი 7.1: უხელფასო შვებულებაში შაბათ-კვირაც ითვლება."""
    calendar = WorkCalendar([TUE_JUN_2])
    assert calendar.count_calendar_days(MON_JUN_1, MON_JUN_8) == 8


def test_count_days_dispatches_on_day_unit(plain_calendar):
    assert plain_calendar.count_days(MON_JUN_1, MON_JUN_8, "working") == 6
    assert plain_calendar.count_days(MON_JUN_1, MON_JUN_8, "calendar") == 8


def test_missing_day_unit_is_an_error(plain_calendar):
    """PARENTAL-ს `day_unit` არ აქვს — ჩუმად 0 არ უნდა დაბრუნდეს."""
    with pytest.raises(UnknownDayUnit):
        plain_calendar.count_days(MON_JUN_1, MON_JUN_8, None)


def test_weekend_holiday_gives_no_substitute_day():
    """მუხლი 2.3: შაბათ-კვირას დამთხვეული უქმე დღე არაფერს ცვლის."""
    saturday = date(2026, 6, 6)
    calendar = WorkCalendar([saturday])
    assert calendar.count_working_days(MON_JUN_1, MON_JUN_8) == 6


def test_notice_excludes_both_endpoints(plain_calendar):
    """მუხლი 4.4: არც წარდგენის, არც პირველი დღე არ ითვლება."""
    assert plain_calendar.notice_working_days(MON_JUN_1, MON_JUN_8) == 4
    assert plain_calendar.notice_working_days(MON_JUN_1, MON_JUN_1) == 0


def test_article_4_4_example_earliest_start(plain_calendar):
    """მუხლი 4.4-ის მაგალითი: ორშაბათს წარდგენილი 3-დღიანი შვებულება
    ყველაზე ადრე მომდევნო კვირის სამშაბათს იწყება."""
    assert plain_calendar.earliest_start_date(MON_JUN_1, 5) == TUE_JUN_9


def test_contiguous_over_weekend(plain_calendar):
    """მუხლი 4.5: პარასკევი→ორშაბათი ერთ უწყვეტ შვებულებად ითვლება."""
    assert plain_calendar.is_contiguous(FRI_JUN_5, MON_JUN_8) is True


def test_not_contiguous_when_a_working_day_sits_between(plain_calendar):
    assert plain_calendar.is_contiguous(FRI_JUN_5, TUE_JUN_9) is False


def test_contiguous_when_only_a_holiday_sits_between():
    calendar = WorkCalendar([MON_JUN_8])
    assert calendar.is_contiguous(FRI_JUN_5, TUE_JUN_9) is True


def test_cross_year_detection():
    assert spans_multiple_years(date(2026, 12, 28), date(2027, 1, 8)) is True
    assert spans_multiple_years(date(2026, 12, 28), date(2026, 12, 31)) is False


def test_overlap_detection():
    assert periods_overlap(MON_JUN_1, FRI_JUN_5, FRI_JUN_5, MON_JUN_8) is True
    assert periods_overlap(MON_JUN_1, FRI_JUN_5, MON_JUN_8, TUE_JUN_9) is False


def test_seeded_requests_match_recomputed_days(repo):
    """`leave_requests.csv`-ის ყველა `days` პოლიტიკის დათვლას უნდა ემთხვეოდეს.

    ეს მოწოდებული მონაცემების regression ტესტია: თუ `workdays.py`
    გაფუჭდა, 27-დან რომელიმე მოთხოვნა აუცილებლად აცდება.
    """
    calendar = repo.work_calendar()
    units = {t.code: t.day_unit for t in repo.list_leave_types()}

    mismatches = []
    for request in repo.list_requests():
        unit = units[request.leave_type]
        expected = calendar.count_days(request.start_date, request.end_date, unit)
        if expected != request.days:
            mismatches.append((request.request_id, request.days, expected))

    assert mismatches == []
