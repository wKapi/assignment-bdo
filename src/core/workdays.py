"""სამუშაო და კალენდარული დღეების დათვლა — შვებულების პოლიტიკის მუხლი 2.

მუხლი 2.2: ყოველწლიური, ავადმყოფობის, გლოვისა და სასწავლო შვებულება
სამუშაო დღეებით ითვლება; შაბათი, კვირა და უქმე დღე არ ითვლება.
უხელფასო შვებულება — კალენდარული დღეებით (მუხლი 7.1).

მუხლი 2.3: უქმე დღეების ერთადერთი წყარო HR სისტემის სიაა
(`public_holidays` ცხრილი). თუ უქმე დღე შაბათ-კვირას ემთხვევა,
სანაცვლო დასვენების დღე არ გაიცემა — ამიტომ უბრალო „weekday < 5 და არა
უქმე“ შემოწმება საკმარისია.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

WORKING = "working"
CALENDAR = "calendar"

_DAY = timedelta(days=1)


class UnknownDayUnit(ValueError):
    """`day_unit` არ არის მითითებული (მაგ. PARENTAL) ან უცნობია."""


class WorkCalendar:
    """სამუშაო კალენდარი უქმე დღეების კონკრეტულ სიაზე დაყრდნობით."""

    def __init__(self, holidays: Iterable[date]) -> None:
        self._holidays: frozenset[date] = frozenset(holidays)

    @property
    def holidays(self) -> frozenset[date]:
        return self._holidays

    def is_holiday(self, day: date) -> bool:
        return day in self._holidays

    def is_weekend(self, day: date) -> bool:
        return day.weekday() >= 5  # 5 = შაბათი, 6 = კვირა

    def is_working_day(self, day: date) -> bool:
        """ორშაბათი–პარასკევი, რომელიც უქმე დღე არ არის (მუხლი 1.3)."""
        return not self.is_weekend(day) and not self.is_holiday(day)

    #დათვლა 

    def count_working_days(self, start: date, end: date) -> int:
        """სამუშაო დღეები [start; end] შუალედში, ორივე ბოლო ჩათვლით."""
        if end < start:
            return 0
        total = 0
        day = start
        while day <= end:
            if self.is_working_day(day):
                total += 1
            day += _DAY
        return total

    @staticmethod
    def count_calendar_days(start: date, end: date) -> int:
        """კალენდარული დღეები [start; end] შუალედში (მუხლი 7.1)."""
        if end < start:
            return 0
        return (end - start).days + 1

    def count_days(self, start: date, end: date, day_unit: str | None) -> int:
        """დღეების დათვლა შვებულების სახის `day_unit`-ის მიხედვით."""
        if day_unit == WORKING:
            return self.count_working_days(start, end)
        if day_unit == CALENDAR:
            return self.count_calendar_days(start, end)
        raise UnknownDayUnit(
            f"day_unit='{day_unit}' — დღეების დათვლის ერთეული განსაზღვრული არ არის"
        )

    # წინასწარი შეტყობინება (მუხლი 4.4

    def notice_working_days(self, submitted_on: date, first_leave_day: date) -> int:
        """სრული სამუშაო დღეები წარდგენასა და შვებულების პირველ დღეს შორის.

        მუხლი 4.4: „წარდგენისა და შვებულების დაწყების დღეები არ ითვლება“ 
        """
        if first_leave_day <= submitted_on:
            return 0
        return self.count_working_days(submitted_on + _DAY, first_leave_day - _DAY)

    def earliest_start_date(self, submitted_on: date, required_notice: int) -> date:
        """ყველაზე ადრეული დასაშვები პირველი დღე მოცემული ვადისთვის.

        აბრუნებს პირველ სამუშაო დღეს, რომლისთვისაც `notice_working_days`
        საჭირო რაოდენობას აღწევს.
        """
        day = submitted_on + _DAY
        while True:
            if self.is_working_day(day) and (
                self.notice_working_days(submitted_on, day) >= required_notice
            ):
                return day
            day += _DAY

    # უწყვეტობა (მუხლი 4.5)

    def is_contiguous(self, earlier_end: date, later_start: date) -> bool:
        """ორი პერიოდი ერთ უწყვეტ შვებულებად ითვლება თუ არა.

        მუხლი 4.5: „ორი მოთხოვნა ერთ უწყვეტ შვებულებად ითვლება, თუ მათ
        შორის მხოლოდ შაბათ-კვირა ან უქმე დღეებია“ — ანუ შუალედში არც ერთი
        სამუშაო დღე არ არის.
        """
        if later_start <= earlier_end:
            return True  # გადაფარვა
        return self.count_working_days(earlier_end + _DAY, later_start - _DAY) == 0



def spans_multiple_years(start: date, end: date) -> bool:
    """მოთხოვნა ორ შვებულების წელს ხომ არ მოიცავს (მუხლი 2.1)."""
    return start.year != end.year


def leave_year_of(start: date) -> int:
    """მოთხოვნა იმ წელს მიეკუთვნება, რომელშიც მისი პირველი დღეა (მუხლი 2.1)."""
    return start.year


def periods_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """ორი პერიოდი ერთმანეთს ემთხვევა თუ არა (მუხლი 12.3)."""
    return a_start <= b_end and b_start <= a_end
