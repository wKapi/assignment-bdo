"""ხელმისაწვდომი ბალანსის გამოთვლა — შვებულების პოლიტიკის მუხლი 5.1.

    ხელმისაწვდომი = კუთვნილი + გადმოტანილი − დამტკიცებული − განხილვაში

გამოთვლა ყოველთვის ერთი თანამშრომლის, ერთი სახისა და ერთი შვებულების
წლის ფარგლებშია. `rejected` და `cancelled` მოთხოვნები არ ითვლება.
"""

from __future__ import annotations

from dataclasses import dataclass

# მუხლი 5.1: „გლოვისა და მშობლის შვებულებას წლიური ბალანსი არ აქვს“
TYPES_WITHOUT_BALANCE = frozenset({"BEREAVEMENT", "PARENTAL"})


@dataclass(frozen=True)
class LeaveBalance:
    """ერთი სახისა და წლის ბალანსი, დაშლილი შემადგენლებად.

    მუხლი 5.2 ითხოვს, რომ ასისტენტმა ცალკე აჩვენოს რამდენი დღეა
    დამტკიცებული და რამდენი განხილვის პროცესში — ამიტომ `available_days`
    მარტო არ კმარა.
    """

    employee_id: str
    year: int
    leave_type: str
    tracked: bool
    """False — ამ სახეს წლიური ბალანსი არ აქვს (მუხლი 5.1)."""
    known: bool
    """False — ამ წელს კუთვნილი დღეების ჩანაწერი ბაზაში არ არის."""
    entitled_days: int | None
    carried_over_days: int | None
    approved_days: int
    pending_days: int
    available_days: int | None
    clamped: bool = False
    """True — ფორმულამ უარყოფითი შედეგი მოგვცა და 0-მდე დავიყვანეთ (SICK)."""
    note: str | None = None

    @property
    def is_paid_sick(self) -> bool:
        return self.leave_type == "SICK"


def compute_balance(
    *,
    employee_id: str,
    year: int,
    leave_type: str,
    entitled_days: int | None,
    carried_over_days: int | None,
    approved_days: int,
    pending_days: int,
) -> LeaveBalance:
    """მუხლი 5.1-ის ფორმულა, სამი გამონაკლისის გათვალისწინებით.

    1. BEREAVEMENT და PARENTAL — წლიური ბალანსი არ აქვთ (მუხლი 5.1).
    2. კუთვნილი დღეების ჩანაწერის არარსებობა ნულს არ ნიშნავს — ეს
       უცნობი მდგომარეობაა და ასეთად უნდა დაბრუნდეს (მუხლი 5.3: ციფრს
       მხოლოდ HR ასწორებს).
    3. SICK-ის უარყოფითი შედეგი 0-ია, მაგრამ ეს აღრიცხვის აკრძალვას
       არ ნიშნავს (მუხლები 5.1 და 6.4).
    """
    if leave_type in TYPES_WITHOUT_BALANCE:
        return LeaveBalance(
            employee_id=employee_id,
            year=year,
            leave_type=leave_type,
            tracked=False,
            known=True,
            entitled_days=None,
            carried_over_days=None,
            approved_days=approved_days,
            pending_days=pending_days,
            available_days=None,
            note="ამ სახის შვებულებას წლიური ბალანსი არ აქვს (მუხლი 5.1).",
        )

    if entitled_days is None:
        return LeaveBalance(
            employee_id=employee_id,
            year=year,
            leave_type=leave_type,
            tracked=True,
            known=False,
            entitled_days=None,
            carried_over_days=None,
            approved_days=approved_days,
            pending_days=pending_days,
            available_days=None,
            note=(
                f"{year} წლის კუთვნილი დღეები HR სისტემაში არ არის. "
                "დასაზუსტებლად მიმართეთ ადამიანური რესურსების სამსახურს "
                "(მუხლი 5.3)."
            ),
        )

    carried = carried_over_days or 0
    raw = entitled_days + carried - approved_days - pending_days
    available = max(raw, 0)
    clamped = raw < 0

    note = None
    if clamped:
        note = (
            "ანაზღაურებადი დღეები ამოწურულია. ეს ავადმყოფობის შემდგომი "
            "აღრიცხვის აკრძალვას არ ნიშნავს — პირობებს HR განსაზღვრავს "
            "(მუხლი 6.4)."
            if leave_type == "SICK"
            else "უარყოფითი შედეგია, მიმართეთ HR-ს (მუხლი 5.3)."
        )

    return LeaveBalance(
        employee_id=employee_id,
        year=year,
        leave_type=leave_type,
        tracked=True,
        known=True,
        entitled_days=entitled_days,
        carried_over_days=carried,
        approved_days=approved_days,
        pending_days=pending_days,
        available_days=available,
        clamped=clamped,
        note=note,
    )
