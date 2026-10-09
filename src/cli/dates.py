"""ქართული თარიღების ამოცნობა ტექსტში.

ფორმები:
* „15 ივნისიდან 19-მდე“, „15 ივნისიდან 19 ივნისამდე“
* „15 ივნისს“, „15 ივნისი“ (ერთი დღე)
* „2026-06-15 2026-06-19“, „15.06.2026“
* „დღეს“, „ხვალ“, „ზეგ“, „ორშაბათიდან“
"""

from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS: dict[str, int] = {
    "იანვ": 1, "თებერვ": 2, "მარტ": 3, "აპრილ": 4, "მაის": 5, "ივნის": 6,
    "ივლის": 7, "აგვისტ": 8, "სექტემბ": 9, "ოქტომბ": 10, "ნოემბ": 11,
    "დეკემბ": 12,
}

WEEKDAYS: dict[str, int] = {
    "ორშაბათ": 0, "სამშაბათ": 1, "ოთხშაბათ": 2, "ხუთშაბათ": 3,
    "პარასკევ": 4, "შაბათ": 5, "კვირა": 6,
}

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DOTTED_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
DAY_MONTH = re.compile(r"\b(\d{1,2})\s*([ა-ჰ]{3,})")
BARE_DAY = re.compile(r"\b(\d{1,2})\s*-?\s*მდე\b")


def _month_from(word: str) -> int | None:
    for prefix, number in MONTHS.items():
        if word.startswith(prefix):
            return number
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _relative(text: str, today: date) -> date | None:
    if "ზეგ" in text:
        return today + timedelta(days=2)
    if "ხვალ" in text:
        return today + timedelta(days=1)
    if "დღეს" in text or "დღესვე" in text:
        return today
    for name, weekday in WEEKDAYS.items():
        if name in text:
            ahead = (weekday - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def parse_dates(text: str, today: date) -> tuple[date, date] | None:
    """ტექსტიდან თარიღების დიაპაზონი. ვერ ამოცნობისას — None.

    ერთი თარიღის შემთხვევაში ბრუნდება ერთდღიანი დიაპაზონი.
    """
    if not text:
        return None

    lowered = text.lower()

    # 1. ზუსტი ფორმატები
    explicit: list[date] = []
    for year, month, day in ISO_DATE.findall(lowered):
        found = _safe_date(int(year), int(month), int(day))
        if found:
            explicit.append(found)
    for day, month, year in DOTTED_DATE.findall(lowered):
        found = _safe_date(int(year), int(month), int(day))
        if found:
            explicit.append(found)
    if explicit:
        explicit.sort()
        return explicit[0], explicit[-1]

    # 2. „15 ივნისიდან 19 ივნისამდე“ / „15 ივნისს“
    named: list[tuple[int, int]] = []  # (დღე, თვე)
    for day_text, month_word in DAY_MONTH.findall(lowered):
        month = _month_from(month_word)
        if month:
            named.append((int(day_text), month))

    if named:
        year = today.year
        dates = [d for d in (_safe_date(year, m, dd) for dd, m in named) if d]
        if not dates:
            return None

        # 3. „15 ივნისიდან 19-მდე“ — მეორე რიცხვი თვის გარეშე
        if len(dates) == 1:
            tail = BARE_DAY.search(lowered)
            if tail:
                end_day = int(tail.group(1))
                first = dates[0]
                if end_day != first.day:
                    end = _safe_date(year, first.month, end_day)
                    if end and end >= first:
                        return first, end
            return dates[0], dates[0]

        dates.sort()
        return dates[0], dates[-1]

    # 4. relative sityvebi
    relative = _relative(lowered, today)
    if relative:
        return relative, relative

    return None
