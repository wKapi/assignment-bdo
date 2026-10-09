"""როლები და წვდომის შემოწმება — შვებულების პოლიტიკის მუხლები 5.2 და 12.3.

MCP სერვერს ორი მომხმარებელი ჰყავს:

* `employee` — HR ასისტენტი, რომელიც კონკრეტული თანამშრომლის სახელით
  მოქმედებს. ხედავს მხოლოდ *საკუთარ* მონაცემებს და მოთხოვნებს ქმნის
  მუხლი 12.2-ის ფარგლებში.
* `hr` — HR პორტალის/სამსახურის არხი. ხედავს ყველას და იღებს
  გადაწყვეტილებებს.

მუხლი 12.3: ასისტენტს არ შეუძლია მოთხოვნის დამტკიცება, უარყოფა,
გაუქმება ან შეცვლა და სხვა თანამშრომლის მონაცემების ნახვა. მუხლი 5.2:
„HR ასისტენტი სხვა თანამშრომლის ბალანსს ხელმძღვანელსაც არ აჩვენებს“.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.config import CURRENT_EMPLOYEE_ID, CURRENT_ROLE


class Role(str, Enum):
    EMPLOYEE = "employee"
    HR = "hr"


class PermissionDenied(PermissionError):
    """წვდომა აკრძალულია — ყოველთვის პოლიტიკის მუხლის მითითებით."""

    def __init__(self, message: str, policy_ref: str) -> None:
        super().__init__(f"{message} ({policy_ref})")
        self.message = message
        self.policy_ref = policy_ref


@dataclass(frozen=True)
class Principal:
    role: Role
    employee_id: str | None

    @property
    def is_hr(self) -> bool:
        return self.role is Role.HR

    @property
    def created_via(self) -> str:
        """რომელი არხიდან იქმნება მოთხოვნა (`leave_requests.created_via`)."""
        return "portal" if self.is_hr else "assistant"


def current_principal() -> Principal:
    """სესიის მოქმედი პირი გარემოს ცვლადებიდან."""
    role = Role(CURRENT_ROLE) if CURRENT_ROLE in {r.value for r in Role} else Role.EMPLOYEE
    return Principal(role=role, employee_id=CURRENT_EMPLOYEE_ID)




def resolve_employee_id(principal: Principal, requested: str | None) -> str:
    """რომელი თანამშრომლის მონაცემები უნდა დავაბრუნოთ.

    თანამშრომლის არხისთვის `requested` ან ცარიელია, ან საკუთარ ID-ს
    უნდა ემთხვეოდეს — სხვისი მონაცემების ნახვა აკრძალულია (მუხლი 5.2).
    """
    if principal.is_hr:
        if not requested:
            raise ValueError("HR როლისთვის employee_id სავალდებულოა.")
        return requested

    if not principal.employee_id:
        raise PermissionDenied(
            "სესიაში თანამშრომელი იდენტიფიცირებული არ არის", "მუხლი 12.4"
        )
    if requested and requested != principal.employee_id:
        raise PermissionDenied(
            "სხვა თანამშრომლის მონაცემების ნახვა ასისტენტს არ შეუძლია",
            "მუხლები 5.2, 12.3",
        )
    return principal.employee_id


def require_hr(principal: Principal, action: str) -> None:
    """გადაწყვეტილების მიმღები მოქმედებები მხოლოდ HR არხისთვისაა."""
    if not principal.is_hr:
        raise PermissionDenied(
            f"ასისტენტს მოთხოვნის {action} არ შეუძლია — გამოიყენეთ HR პორტალი "
            "ან მიმართეთ ადამიანური რესურსების სამსახურს",
            "მუხლები 4.8, 12.3",
        )
