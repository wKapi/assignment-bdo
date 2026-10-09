"""ასისტენტის უფლებამოსილების წესები — შვებულებისა და გაცდენის პოლიტიკა.

მოდული წმინდა ფუნქციებისგან შედგება: ბაზას არ ეხება, მხოლოდ მზა
მონაცემებზე მსჯელობს. ეს ტესტირებას ამარტივებს და MCP ხელსაწყოებსა და
CLI-ს ერთსა და იმავე ლოგიკას ატარებინებს.

მთავარი ჩამონათვალი მუხლი 12.3-შია: ასისტენტი მოთხოვნას არ ქმნის, თუ ის
არღვევს წინასწარი შეტყობინების ვადას, ბალანსს, უწყვეტი შვებულების
მაქსიმუმს, შეზღუდულ პერიოდებს ან გამოსაცდელი ვადის წესს (მუხლები 4.3,
4.4, 4.5, 4.6, 5, 6.4, 7.2), ასევე თარიღების გადაფარვისა და მომდევნო
წლის თარიღების შემთხვევაში.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from src.core.balance import LeaveBalance
from src.core.workdays import (
    UnknownDayUnit,
    WorkCalendar,
    periods_overlap,
    spans_multiple_years,
)

# ასისტენტი მოთხოვნას მხოლოდ ამ სამ სახეზე ქმნის (მუხლი 12.2)
ASSISTANT_CREATABLE = frozenset({"ANNUAL", "SICK", "UNPAID"})

# სტატუსები, რომლებიც ბალანსსა და გადაფარვაში მონაწილეობს (მუხლი 5.1)
ACTIVE_STATUSES = frozenset({"approved", "pending"})

# მუხლი 4.5 — ერთი მოთხოვნით მაქსიმუმი
MAX_CONTINUOUS_ANNUAL_DAYS = 15

# მუხლი 7.1 — უხელფასო შვებულების წლიური მაქსიმუმი (კალენდარული დღეები)
MAX_UNPAID_CALENDAR_DAYS = 30

# მუხლი 6.2 — ავადმყოფობის აღრიცხვის დაგვიანების ზღვარი
MAX_SICK_LATE_WORKING_DAYS = 2

# მუხლი 4.6 — შეზღუდული პერიოდები მხოლოდ აუდიტის დეპარტამენტისთვის
RESTRICTED_DEPARTMENTS = frozenset({"AUD"})
RESTRICTED_PERIODS: tuple[tuple[tuple[int, int], tuple[int, int], str], ...] = (
    ((12, 1), (12, 20), "წლიური აუდიტის დაგეგმვის პერიოდი"),
    ((1, 15), (3, 15), "წლიური ანგარიშგების აუდიტის აქტიური პერიოდი"),
)


#შემავალი მონაცემები


@dataclass(frozen=True)
class EmployeeInfo:
    employee_id: str
    department_code: str
    start_date: date
    probation_end_date: date | None
    status: str = "active"


@dataclass(frozen=True)
class LeaveTypeInfo:
    code: str
    name: str
    day_unit: str | None
    annual_limit_days: int | None
    self_service: bool
    assistant_supported: bool
    policy_reference: str | None = None


@dataclass(frozen=True)
class ExistingRequest:
    request_id: int
    leave_type: str
    start_date: date
    end_date: date
    days: int
    status: str


# შედეგი


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    policy_ref: str
    redirect: str | None = None
    """სად გადავამისამართოთ: 'hr', 'portal', 'manager' ან None."""


@dataclass
class Evaluation:
    allowed: bool
    days: int | None
    leave_year: int | None
    violations: list[Violation] = field(default_factory=list)

    @property
    def first_reason(self) -> Violation | None:
        return self.violations[0] if self.violations else None


def required_notice_days(leave_type: str, days: int) -> int | None:
    """წინასწარი შეტყობინების მინიმალური ვადა სამუშაო დღეებში.

    მუხლი 4.4 (ANNUAL): 1–5 დღე → 5; 6–15 დღე → 15; 15-ზე მეტი → მუხლი 4.5.
    მუხლი 7.2 (UNPAID): 10 სამუშაო დღე.
    მუხლი 6.2 (SICK): წინასწარი შეტყობინების წესი არ ვრცელდება.
    """
    if leave_type == "ANNUAL":
        return 5 if days <= 5 else 15
    if leave_type == "UNPAID":
        return 10
    if leave_type == "STUDY":
        return 10  # მუხლი 9.3 — ასისტენტი ასეთ მოთხოვნას მაინც არ ქმნის
    return None


def restricted_period_hits(
    start: date, end: date, department_code: str
) -> list[str]:
    """შეზღუდულ პერიოდებთან გადაკვეთის აღწერები (მუხლი 4.6)."""
    if department_code not in RESTRICTED_DEPARTMENTS:
        return []

    hits: list[str] = []
    for year in range(start.year, end.year + 1):
        for (from_m, from_d), (to_m, to_d), label in RESTRICTED_PERIODS:
            period_start = date(year, from_m, from_d)
            period_end = date(year, to_m, to_d)
            if periods_overlap(start, end, period_start, period_end):
                hits.append(f"{label} ({period_start:%d.%m}–{period_end:%d.%m})")
    return hits


def continuous_block_days(
    calendar: WorkCalendar,
    start: date,
    end: date,
    days: int,
    existing: list[ExistingRequest],
) -> int:
    """ახალი პერიოდის უწყვეტი ბლოკის ჯამური დღეები (მუხლი 4.5).

    ორი მოთხოვნა ერთ შვებულებად ითვლება, თუ მათ შორის მხოლოდ შაბათ-კვირა
    ან უქმე დღეებია. ბლოკს იტერაციულად ვზრდით, სანამ ახალი მეზობელი
    იძებნება.
    """
    candidates = [
        r
        for r in existing
        if r.leave_type == "ANNUAL" and r.status in ACTIVE_STATUSES
    ]
    block_start, block_end, total = start, end, days

    def touches(r: ExistingRequest) -> bool:
        """მოთხოვნა ბლოკს ემიჯნება თუ არა — მიმართულების გათვალისწინებით."""
        if periods_overlap(block_start, block_end, r.start_date, r.end_date):
            return True
        if r.start_date > block_end:
            return calendar.is_contiguous(block_end, r.start_date)
        return calendar.is_contiguous(r.end_date, block_start)

    merged = True
    while merged:
        merged = False
        for request in list(candidates):
            if touches(request):
                block_start = min(block_start, request.start_date)
                block_end = max(block_end, request.end_date)
                total += request.days
                candidates.remove(request)
                merged = True
    return total


def evaluate_assistant_request(
    *,
    employee: EmployeeInfo,
    leave_type: LeaveTypeInfo,
    start: date,
    end: date,
    today: date,
    calendar: WorkCalendar,
    balance: LeaveBalance | None,
    existing: list[ExistingRequest],
    reason: str | None = None,
    sick_period_known: bool = False,
) -> Evaluation:
    """ამოწმებს, შეუძლია თუ არა ასისტენტს ამ მოთხოვნის შექმნა.

    აბრუნებს ყველა აღმოჩენილ დარღვევას და არა მხოლოდ პირველს: მუხლი
    12.3 ითხოვს, რომ ასისტენტმა მიზეზი ახსნას და, სადაც შესაძლებელია,
    ალტერნატივა შესთავაზოს.
    """
    violations: list[Violation] = []

    def fail(code: str, message: str, ref: str, redirect: str | None = None) -> None:
        violations.append(Violation(code, message, ref, redirect))

    #თარიღების ვალიდურობა 

    if end < start:
        fail(
            "INVALID_RANGE",
            "დასრულების თარიღი დაწყების თარიღზე ადრეა.",
            "მუხლი 2.4",
        )
        return Evaluation(allowed=False, days=None, leave_year=None, violations=violations)

    if spans_multiple_years(start, end):
        fail(
            "CROSS_YEAR",
            "შვებულება ორ კალენდარულ წელს მოიცავს. თითოეული წლისთვის "
            "ცალკე მოთხოვნა უნდა წარადგინოთ.",
            "მუხლი 2.1",
            redirect="portal",
        )
        return Evaluation(allowed=False, days=None, leave_year=None, violations=violations)

    leave_year = start.year

    #სახე და უფლებამოსილება

    if leave_type.code not in ASSISTANT_CREATABLE or not leave_type.assistant_supported:
        channel = "portal" if leave_type.self_service else "hr"
        fail(
            "TYPE_NOT_SUPPORTED",
            f"„{leave_type.name}“ მოთხოვნას ასისტენტი არ ქმნის. წესებს "
            "განვმარტავ, მოთხოვნა კი HR პორტალით ან ადამიანური რესურსების "
            "სამსახურის მეშვეობით უნდა წარადგინოთ.",
            leave_type.policy_reference or "მუხლი 12.3",
            redirect=channel,
        )
        return Evaluation(allowed=False, days=None, leave_year=leave_year, violations=violations)

    if employee.status != "active":
        fail(
            "EMPLOYEE_INACTIVE",
            "თანამშრომლის სტატუსი აქტიური არ არის.",
            "მუხლი 1.2",
            redirect="hr",
        )

    # დღეების დათვლა

    try:
        days = calendar.count_days(start, end, leave_type.day_unit)
    except UnknownDayUnit:
        fail(
            "UNKNOWN_DAY_UNIT",
            "ამ სახისთვის დღეების დათვლის ერთეული განსაზღვრული არ არის.",
            "მუხლი 2.2",
            redirect="hr",
        )
        return Evaluation(allowed=False, days=None, leave_year=leave_year, violations=violations)

    if days == 0:
        fail(
            "NO_WORKING_DAYS",
            "მითითებულ პერიოდში სამუშაო დღე არ არის — შვებულების დღეები "
            "არ ჩამოიწერება.",
            "მუხლი 2.2",
        )
        return Evaluation(allowed=False, days=0, leave_year=leave_year, violations=violations)

    # წელი (მუხლი 12.3)

    if leave_year > today.year:
        fail(
            "NEXT_YEAR",
            "მომდევნო წლის თარიღებზე მოთხოვნას ასისტენტი არ ქმნის. "
            "HR პორტალით წარდგენა მიმდინარე წლის 1 დეკემბრიდან შეიძლება.",
            "მუხლი 12.3",
            redirect="portal",
        )
    elif leave_year < today.year:
        fail(
            "PAST_YEAR",
            "წინა შვებულების წლის თარიღებზე მოთხოვნას ასისტენტი არ ქმნის.",
            "მუხლი 12.3",
            redirect="hr",
        )

    # გადაფარვა (მუხლი 12.3)

    for request in existing:
        if request.status not in ACTIVE_STATUSES:
            continue
        if periods_overlap(start, end, request.start_date, request.end_date):
            fail(
                "OVERLAP",
                f"თარიღები ემთხვევა თქვენს სხვა მოთხოვნას "
                f"#{request.request_id} ({request.start_date:%d.%m.%Y}–"
                f"{request.end_date:%d.%m.%Y}, {request.status}).",
                "მუხლი 12.3",
            )
            break

    #სახეების სპეციფიკური წესები

    if leave_type.code == "ANNUAL":
        _check_annual(
            fail=fail,
            employee=employee,
            start=start,
            end=end,
            days=days,
            today=today,
            calendar=calendar,
            existing=existing,
        )
    elif leave_type.code == "SICK":
        _check_sick(
            fail=fail,
            start=start,
            days=days,
            today=today,
            calendar=calendar,
            balance=balance,
            period_known=sick_period_known,
        )
    elif leave_type.code == "UNPAID":
        _check_unpaid(
            fail=fail,
            start=start,
            days=days,
            today=today,
            calendar=calendar,
            existing=existing,
            leave_year=leave_year,
            reason=reason,
        )

    # ბალანსი (მუხლი 5.1)
    # SICK-ს ცალკე წესი აქვს (6.4), ამიტომ აქ აღარ ვიმეორებ.

    if leave_type.code != "SICK":
        _check_balance(fail=fail, balance=balance, days=days)

    return Evaluation(
        allowed=not violations,
        days=days,
        leave_year=leave_year,
        violations=violations,
    )




def _check_annual(*, fail, employee, start, end, days, today, calendar, existing) -> None:
    # მუხლი 4.3 — გამოსაცდელი ვადა (ბოლო დღე ჩათვლით)
    if employee.probation_end_date and start <= employee.probation_end_date:
        fail(
            "PROBATION",
            "გამოსაცდელი ვადის განმავლობაში ყოველწლიური შვებულების "
            f"გამოყენება არ შეიძლება (ვადა სრულდება "
            f"{employee.probation_end_date:%d.%m.%Y}). კუთვნილი დღეები "
            "გერიცხებათ და ვადის დასრულების შემდეგ გამოიყენებთ.",
            "მუხლი 4.3",
            redirect="hr",
        )

    # მუხლი 4.5 — ერთი მოთხოვნით მაქსიმუმ 15 სამუშაო დღე
    if days > MAX_CONTINUOUS_ANNUAL_DAYS:
        fail(
            "MAX_CONTINUOUS",
            f"ერთი მოთხოვნით მაქსიმუმ {MAX_CONTINUOUS_ANNUAL_DAYS} სამუშაო "
            f"დღეა შესაძლებელი, მოთხოვნილია {days}. უფრო ხანგრძლივი "
            "შვებულებისთვის საჭიროა პარტნიორის ან დირექტორის წერილობითი "
            "თანხმობა უშუალო ხელმძღვანელის მეშვეობით.",
            "მუხლი 4.5",
            redirect="manager",
        )
    else:
        block = continuous_block_days(calendar, start, end, days, existing)
        if block > MAX_CONTINUOUS_ANNUAL_DAYS:
            fail(
                "CONTINUOUS_BLOCK",
                f"ეს მოთხოვნა თქვენს სხვა შვებულებას ებმის (შუალედში მხოლოდ "
                f"დასვენების დღეებია) და ჯამში {block} სამუშაო დღე გამოდის. "
                "ასეთი უწყვეტი შვებულება ხელმძღვანელის მეშვეობით ფორმდება.",
                "მუხლი 4.5",
                redirect="manager",
            )

    # მუხლი 4.6 — შეზღუდული პერიოდები
    hits = restricted_period_hits(start, end, employee.department_code)
    if hits:
        fail(
            "RESTRICTED_PERIOD",
            "მოთხოვნილი დღეები შეზღუდულ პერიოდში ხვდება: "
            + "; ".join(hits)
            + ". საჭიროა პროექტის პარტნიორის წინასწარი წერილობითი თანხმობა — "
            "მიმართეთ უშუალო ხელმძღვანელს.",
            "მუხლი 4.6",
            redirect="manager",
        )

    _check_notice(fail=fail, leave_type="ANNUAL", start=start, days=days,
                  today=today, calendar=calendar, ref="მუხლი 4.4")


def _check_sick(*, fail, start, days, today, calendar, balance, period_known) -> None:
    # მუხლი 6.2 — აღრიცხვა პირველ დღეს, ან არაუგვიანეს 2 სამუშაო დღისა
    if start < today:
        late = calendar.count_working_days(start + timedelta(days=1), today)
        if late > MAX_SICK_LATE_WORKING_DAYS:
            fail(
                "SICK_LATE",
                f"ავადმყოფობის აღრიცხვა პირველი დღიდან არაუგვიანეს "
                f"{MAX_SICK_LATE_WORKING_DAYS} სამუშაო დღისაა შესაძლებელი; "
                f"გასულია {late}. მიმართეთ ადამიანური რესურსების სამსახურს.",
                "მუხლი 6.2",
                redirect="hr",
            )
    elif start > today and not period_known:
        fail(
            "SICK_FUTURE_UNCONFIRMED",
            "მომავალი თარიღით ავადმყოფობის შვებულება აღირიცხება მხოლოდ "
            "მაშინ, როცა გაცდენის პერიოდი უკვე ცნობილია — მაგალითად ექიმის "
            "დოკუმენტით ან დაგეგმილი ოპერაციის შემთხვევაში. დაადასტურეთ, "
            "რომ პერიოდი წინასწარ ცნობილია.",
            "მუხლი 6.2",
        )

    # მუხლი 6.4 — ანაზღაურებადი დღეების ლიმიტი
    if balance is not None and balance.known and balance.available_days is not None:
        if days > balance.available_days:
            fail(
                "SICK_PAID_LIMIT",
                f"დარჩენილია {balance.available_days} ანაზღაურებადი დღე, "
                f"მოთხოვნილია {days}. ასეთ მოთხოვნას ასისტენტი არ ქმნის — "
                "აღრიცხვისა და ანაზღაურების პირობებს ადამიანური რესურსების "
                "სამსახური განსაზღვრავს. ავადმყოფობის აღრიცხვა აკრძალული "
                "არ არის.",
                "მუხლი 6.4",
                redirect="hr",
            )


def _check_unpaid(
    *, fail, start, days, today, calendar, existing, leave_year, reason
) -> None:
    # მუხლი 7.2 — მოკლე მიზეზი სავალდებულოა
    if not (reason or "").strip():
        fail(
            "REASON_REQUIRED",
            "უხელფასო შვებულების მოთხოვნაში მოკლედ უნდა მიუთითოთ მიზეზი.",
            "მუხლი 7.2",
        )

    # მუხლი 7.1 — წელიწადში ჯამურად არაუმეტეს 30 კალენდარული დღე
    used = sum(
        r.days
        for r in existing
        if r.leave_type == "UNPAID"
        and r.status in ACTIVE_STATUSES
        and r.start_date.year == leave_year
    )
    if used + days > MAX_UNPAID_CALENDAR_DAYS:
        fail(
            "UNPAID_LIMIT",
            f"წელიწადში ჯამურად {MAX_UNPAID_CALENDAR_DAYS} კალენდარულ დღემდეა "
            f"შესაძლებელი; უკვე გამოყენებულია {used}, მოთხოვნილია {days}. "
            "მეტისთვის საჭიროა მმართველი პარტნიორის თანხმობა ადამიანური "
            "რესურსების სამსახურის მეშვეობით.",
            "მუხლი 7.1",
            redirect="hr",
        )

    _check_notice(fail=fail, leave_type="UNPAID", start=start, days=days,
                  today=today, calendar=calendar, ref="მუხლი 7.2")


def _check_notice(*, fail, leave_type, start, days, today, calendar, ref) -> None:
    """წინასწარი შეტყობინების ვადა — დათვლა მუხლი 4.4-ის წესით."""
    required = required_notice_days(leave_type, days)
    if required is None:
        return

    actual = calendar.notice_working_days(today, start)
    if actual < required:
        earliest = calendar.earliest_start_date(today, required)
        fail(
            "NOTICE_PERIOD",
            f"საჭიროა მინიმუმ {required} სამუშაო დღით ადრე წარდგენა, "
            f"ამ თარიღამდე კი {actual} სამუშაო დღეა. ამ ვადით შვებულება "
            f"ყველაზე ადრე {earliest:%d.%m.%Y}-დან შეიძლება დაიწყოს. "
            "გადაუდებელი პირადი მიზეზის შემთხვევაში მოთხოვნა პირდაპირ "
            "უშუალო ხელმძღვანელს წარუდგინეთ.",
            ref,
            redirect="manager",
        )


def _check_balance(*, fail, balance, days) -> None:
    if balance is None or not balance.tracked:
        return
    if not balance.known:
        fail(
            "BALANCE_UNKNOWN",
            balance.note or "ბალანსი უცნობია.",
            "მუხლი 5.3",
            redirect="hr",
        )
        return
    if balance.available_days is not None and days > balance.available_days:
        fail(
            "INSUFFICIENT_BALANCE",
            f"ხელმისაწვდომია {balance.available_days} დღე "
            f"({balance.entitled_days} კუთვნილი + "
            f"{balance.carried_over_days} გადმოტანილი − "
            f"{balance.approved_days} დამტკიცებული − "
            f"{balance.pending_days} განხილვაში), მოთხოვნილია {days}.",
            "მუხლი 5.1",
        )
