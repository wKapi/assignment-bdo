"""„დღევანდელი“ თარიღის ერთადერთი წყარო.

`date.today()`-ს პირდაპირ არსად ვიძახებთ: მოწოდებული მონაცემები 2026 წლის
19 ოქტომბერია და ტესტებიც ამ თარიღზეა.
"""

from __future__ import annotations
from datetime import date, datetime
from src.config import APP_TODAY


def today() -> date:
    """აბრუნებს აპლიკაციის მიმდინარე თარიღს (APP_TODAY)."""
    return APP_TODAY


def now() -> datetime:
    """დროის ნიშნული `created_at`-ისთვის: APP_TODAY + რეალური საათი."""
    wall_clock = datetime.now().time().replace(microsecond=0)
    return datetime.combine(today(), wall_clock)


def current_leave_year() -> int:
    """მიმდინარე შვებულების წელი — კალენდარული წელი (მუხლი 2.1)."""
    return today().year
