"""MCP ხელსაწყოების ბიზნეს-ლოგიკა.

აქ MCP-ზე დამოკიდებულება არ არის: ფუნქციები `Repository`-სა და
`Principal`-ს იღებენ და JSON-თავსებად ლექსიკონებს აბრუნებენ. `server.py`
მხოლოდ გადაფუთავს, ტესტები კი პირდაპირ ამ ფუნქციებს იძახებენ.

დარღვევა შეცდომა არ არის: მუხლი 12.3 ითხოვს, რომ ასისტენტმა მიზეზი
ახსნას და მუხლი მიუთითოს, ამიტომ უარი სტრუქტურირებულ პასუხად ბრუნდება
(`created: false` + `violations`), და არა გამონაკლისად.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from src.core.balance import LeaveBalance
from src.core.clock import now, today
from src.core.policy_rules import Evaluation, evaluate_assistant_request
from src.db.repository import Repository
from src.mcp_server.auth import Principal, require_hr, resolve_employee_id

DECISIONS = {"approve": "approved", "reject": "rejected"}



def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"{field}: თარიღი YYYY-MM-DD ფორმატში უნდა იყოს, მიღებულია „{value}“."
        ) from exc


def _balance_payload(balance: LeaveBalance) -> dict[str, Any]:
    return {
        "employee_id": balance.employee_id,
        "year": balance.year,
        "leave_type": balance.leave_type,
        "tracked": balance.tracked,
        "known": balance.known,
        "entitled_days": balance.entitled_days,
        "carried_over_days": balance.carried_over_days,
        "approved_days": balance.approved_days,
        "pending_days": balance.pending_days,
        "available_days": balance.available_days,
        "note": balance.note,
    }


def _violations_payload(evaluation: Evaluation) -> list[dict[str, Any]]:
    return [
        {
            "code": v.code,
            "message": v.message,
            "policy_reference": v.policy_ref,
            "redirect_to": v.redirect,
        }
        for v in evaluation.violations
    ]


def _request_payload(repo: Repository, request_id: int) -> dict[str, Any]:
    row = repo.conn.execute(
        "SELECT * FROM leave_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    return dict(row) if row else {}


def _evaluate(
    repo: Repository,
    employee_id: str,
    leave_type_code: str,
    start: date,
    end: date,
    reason: str | None,
    sick_period_known: bool,
) -> tuple[Evaluation, LeaveBalance | None]:
    employee = repo.get_employee(employee_id)
    if employee is None:
        raise ValueError(f"თანამშრომელი {employee_id} ვერ მოიძებნა.")

    leave_type = repo.get_leave_type(leave_type_code)
    if leave_type is None:
        known = ", ".join(t.code for t in repo.list_leave_types())
        raise ValueError(
            f"შვებულების სახე „{leave_type_code}“ არ არსებობს. დასაშვებია: {known}."
        )

    balance = repo.get_balance(employee_id, start.year, leave_type_code)
    evaluation = evaluate_assistant_request(
        employee=employee,
        leave_type=leave_type,
        start=start,
        end=end,
        today=today(),
        calendar=repo.work_calendar(),
        balance=balance,
        existing=repo.active_requests(employee_id),
        reason=reason,
        sick_period_known=sick_period_known,
    )
    return evaluation, balance


#1. შვებულების სახეები 


def list_leave_types(repo: Repository, principal: Principal) -> dict[str, Any]:
    """ხელმისაწვდომი სახეები და თითოეულის არხი (მუხლები 3.1, 12.2)."""
    types = [
        {
            "code": t.code,
            "name": t.name,
            "day_unit": t.day_unit,
            "annual_limit_days": t.annual_limit_days,
            "self_service": t.self_service,
            "assistant_can_create": t.assistant_supported,
            "policy_reference": t.policy_reference,
        }
        for t in repo.list_leave_types()
    ]
    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="list_leave_types", args={}, result=f"{len(types)} სახე",
    )
    return {"leave_types": types}


#2. ბალანსი 


def get_leave_balance(
    repo: Repository,
    principal: Principal,
    *,
    leave_type: str,
    year: int | None = None,
    employee_id: str | None = None,
) -> dict[str, Any]:
    """დარჩენილი დღეები მოცემული წლისა და სახისთვის (მუხლები 5.1, 5.2)."""
    target = resolve_employee_id(principal, employee_id)
    if repo.get_employee(target) is None:
        raise ValueError(f"თანამშრომელი {target} ვერ მოიძებნა.")
    if repo.get_leave_type(leave_type) is None:
        raise ValueError(f"შვებულების სახე „{leave_type}“ არ არსებობს.")

    resolved_year = year or today().year
    balance = repo.get_balance(target, resolved_year, leave_type)

    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="get_leave_balance",
        args={"employee_id": target, "year": resolved_year, "leave_type": leave_type},
        result=str(balance.available_days),
    )
    return _balance_payload(balance)


def get_all_leave_balances(
    repo: Repository, principal: Principal, *, year: int | None = None,
    employee_id: str | None = None,
) -> dict[str, Any]:
    """ყველა სახის ბალანსი ერთად — CLI-ის „ჩემი შვებულებები“ ხედისთვის."""
    target = resolve_employee_id(principal, employee_id)
    resolved_year = year or today().year
    balances = [
        _balance_payload(repo.get_balance(target, resolved_year, t.code))
        for t in repo.list_leave_types()
    ]
    return {"employee_id": target, "year": resolved_year, "balances": balances}


#3. მოთხოვნების სია


def list_leave_requests(
    repo: Repository,
    principal: Principal,
    *,
    employee_id: str | None = None,
    status: str | None = None,
    leave_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """მოთხოვნების სია ფილტრებით. თარიღის ფილტრი გადაკვეთაზე მუშაობს."""
    target = resolve_employee_id(principal, employee_id)
    statuses = [status] if status else None

    requests = repo.list_requests(
        employee_id=target,
        statuses=statuses,
        leave_type=leave_type,
        date_from=_parse_date(date_from, "date_from") if date_from else None,
        date_to=_parse_date(date_to, "date_to") if date_to else None,
    )

    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="list_leave_requests",
        args={"employee_id": target, "status": status, "leave_type": leave_type},
        result=f"{len(requests)} მოთხოვნა",
    )
    return {
        "employee_id": target,
        "count": len(requests),
        "requests": [
            {
                "request_id": r.request_id,
                "leave_type": r.leave_type,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "days": r.days,
                "status": r.status,
            }
            for r in requests
        ],
    }


#4. შემოწმება შექმნამდე 

def preview_leave_request(
    repo: Repository,
    principal: Principal,
    *,
    leave_type: str,
    start_date: str,
    end_date: str,
    employee_id: str | None = None,
    reason: str | None = None,
    sick_period_known: bool = False,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """ამოწმებს მოთხოვნას ჩაწერის გარეშე და ამზადებს შეთავაზებას.

    მუხლი 12.2: მოთხოვნის შექმნამდე ასისტენტი თანამშრომელს სახეს,
    თარიღებსა და დღეების რაოდენობას აჩვენებს და დადასტურებას სთხოვს.
    """
    target = resolve_employee_id(principal, employee_id)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")

    evaluation, balance = _evaluate(
        repo, target, leave_type, start, end, reason, sick_period_known
    )

    proposal_id = None
    if evaluation.allowed:
        proposal_id = uuid.uuid4().hex
        repo.save_proposal(
            proposal_id=proposal_id,
            conversation_id=conversation_id or uuid.uuid4().hex,
            employee_id=target,
            leave_type=leave_type,
            start=start,
            end=end,
            days=evaluation.days or 0,
            reason=reason,
            created_at=now(),
        )

    return {
        "can_create": evaluation.allowed,
        "proposal_id": proposal_id,
        "employee_id": target,
        "leave_type": leave_type,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": evaluation.days,
        "leave_year": evaluation.leave_year,
        "balance": _balance_payload(balance) if balance else None,
        "violations": _violations_payload(evaluation),
        "confirmation_required": evaluation.allowed,
    }


# 5. მოთხოვნის შექმნა 


def create_leave_request(
    repo: Repository,
    principal: Principal,
    *,
    leave_type: str,
    start_date: str,
    end_date: str,
    employee_id: str | None = None,
    reason: str | None = None,
    sick_period_known: bool = False,
    proposal_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """ქმნის მოთხოვნას სტატუსით `pending` (მუხლი 12.2).

    `proposal_id`-ის გადაცემისას ოპერაცია იდემპოტენტურია: განმეორებითი
    დადასტურება იმავე `request_id`-ს აბრუნებს და მეორე ჩანაწერს არ ქმნის.
    """
    target = resolve_employee_id(principal, employee_id)

    if proposal_id:
        proposal = repo.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"შეთავაზება {proposal_id} ვერ მოიძებნა.")
        if proposal["employee_id"] != target:
            raise ValueError("შეთავაზება სხვა თანამშრომელს ეკუთვნის.")
        if proposal["request_id"] is not None:
            return {
                "created": False,
                "already_confirmed": True,
                "request_id": proposal["request_id"],
                "request": _request_payload(repo, proposal["request_id"]),
                "violations": [],
                "message": "ეს შეთავაზება უკვე დადასტურებულია; ახალი მოთხოვნა არ შექმნილა.",
            }

    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")

    evaluation, balance = _evaluate(
        repo, target, leave_type, start, end, reason, sick_period_known
    )

    if not evaluation.allowed:
        repo.log(
            ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
            tool="create_leave_request",
            args={
                "employee_id": target, "leave_type": leave_type,
                "start_date": start.isoformat(), "end_date": end.isoformat(),
            },
            result="უარი: " + ", ".join(v.code for v in evaluation.violations),
        )
        return {
            "created": False,
            "already_confirmed": False,
            "request_id": None,
            "days": evaluation.days,
            "balance": _balance_payload(balance) if balance else None,
            "violations": _violations_payload(evaluation),
        }

    # UNPAID-ის მიზეზი comment-ში ინახება (მუხლი 7.2). ჯანმრთელობის
    # დეტალებს არ ვაგროვებთ — SICK-ისთვის comment ცარიელი რჩება (მუხლი 12.4).
    comment = reason if leave_type == "UNPAID" else None

    request_id = repo.create_request(
        employee_id=target,
        leave_type=leave_type,
        start=start,
        end=end,
        days=evaluation.days or 0,
        created_at=now(),
        created_via=principal.created_via,
        comment=comment,
    )

    if not proposal_id:
        proposal_id = uuid.uuid4().hex
        repo.save_proposal(
            proposal_id=proposal_id,
            conversation_id=conversation_id or uuid.uuid4().hex,
            employee_id=target,
            leave_type=leave_type,
            start=start,
            end=end,
            days=evaluation.days or 0,
            reason=reason,
            created_at=now(),
        )
    repo.confirm_proposal(
        proposal_id=proposal_id, request_id=request_id, confirmed_at=now()
    )

    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="create_leave_request",
        args={
            "employee_id": target, "leave_type": leave_type,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "days": evaluation.days,
        },
        result=f"შეიქმნა #{request_id}",
    )

    return {
        "created": True,
        "already_confirmed": False,
        "request_id": request_id,
        "proposal_id": proposal_id,
        "request": _request_payload(repo, request_id),
        "violations": [],
        "message": (
            "მოთხოვნა დარეგისტრირდა სტატუსით „განხილვის პროცესში“. "
            "ეს შვებულების დამტკიცებას არ ნიშნავს გადაწყვეტილებას "
            "უშუალო ხელმძღვანელი იღებს (მუხლი 4.4)."
        ),
    }


# . დამტკიცება / უარყოფა


def decide_leave_request(
    repo: Repository,
    principal: Principal,
    *,
    request_id: int,
    decision: str,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """მოთხოვნის დამტკიცება ან უარყოფა მხოლოდ HR არხისთვის (მუხლი 12.3)."""
    require_hr(principal, "დამტკიცება ან უარყოფა")

    if decision not in DECISIONS:
        raise ValueError("decision უნდა იყოს 'approve' ან 'reject'.")

    changed = repo.set_status(
        request_id=request_id,
        status=DECISIONS[decision],
        decided_by=decided_by or principal.employee_id,
        decided_at=now(),
    )
    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="decide_leave_request",
        args={"request_id": request_id, "decision": decision},
        result="შესრულდა" if changed else "სტატუსი არ შეცვლილა",
    )

    if not changed:
        return {
            "updated": False,
            "request_id": request_id,
            "message": "მოთხოვნა ვერ მოიძებნა ან უკვე აღარ არის განხილვის პროცესში.",
        }
    return {
        "updated": True,
        "request_id": request_id,
        "status": DECISIONS[decision],
        "request": _request_payload(repo, request_id),
    }


# 7. გაუქმება 


def cancel_leave_request(
    repo: Repository, principal: Principal, *, request_id: int
) -> dict[str, Any]:
    """მოთხოვნის გაუქმება.

    მუხლი 4.8: „HR ასისტენტი მოთხოვნებს არ აუქმებს და არ ცვლის“ —
    ამიტომ ხელსაწყო HR პორტალის არხისთვისაა.
    """
    require_hr(principal, "გაუქმება")

    changed = repo.set_status(
        request_id=request_id,
        status="cancelled",
        decided_by=principal.employee_id,
        decided_at=now(),
    )
    repo.log(
        ts=now(), actor_role=principal.role.value, actor_id=principal.employee_id,
        tool="cancel_leave_request", args={"request_id": request_id},
        result="გაუქმდა" if changed else "სტატუსი არ შეცვლილა",
    )

    if not changed:
        return {
            "updated": False,
            "request_id": request_id,
            "message": (
                "განხილვის პროცესში მყოფი მოთხოვნა ამ ნომრით ვერ მოიძებნა. "
                "დამტკიცებული შვებულების გაუქმებაზე მოქმედებს მუხლი 4.8."
            ),
        }
    return {"updated": True, "request_id": request_id, "status": "cancelled"}
