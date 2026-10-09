from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from src.cli.dates import parse_dates
from src.cli.mcp_client import LeaveMCPClient, ToolCallError
from src.llm.client import Intent, LLMClient, detect_leave_type
from src.rag.retriever import Retriever, build_context

Ask = Callable[[str], Awaitable[str]]
Say = Callable[[str], None]

AFFIRMATIVE = {"კი", "დიახ", "ჰო", "დადასტურება", "ვადასტურებ", "ok", "დიახ."}
NEGATIVE = {"არა", "ნუ", "გაუქმება", "არ", "no"}

REDIRECTS = {
    "hr": "მიმართეთ ადამიანური რესურსების სამსახურს.",
    "portal": "მოთხოვნა HR პორტალით წარადგინეთ.",
    "manager": "მიმართეთ უშუალო ხელმძღვანელს.",
}


def _is_yes(answer: str) -> bool:
    return answer.strip().lower().rstrip("!.") in AFFIRMATIVE


# სიტყვების რაოდენობა, საიდანაც კითხვა დამოუკიდებელ თემად ითვლება
TOPIC_MIN_WORDS = 3


@dataclass
class Session:
    """ერთი საუბრის მდგომარეობა.

    `topic` საჭიროა კითხვებისთვის: „გამოცდისთვის შვებულება
    მინდა“ → განმარტება, შემდეგ „რა წესებია?“ — მარტო ამ ფრაზით ვერაფერს ხვდება,
    თემასთან ერთად კი სწორ მუხლს პოულობს.
    """

    conversation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    topic: str | None = None


#1. პოლიტიკაზე კითხვა


def answer_policy_question(
    question: str,
    retriever: Retriever,
    llm: LLMClient,
    say: Say,
    session: Session | None = None,
) -> None:
    hits = retriever.search(question)

    # კითხვა — ვცდით წინა თემასთან ერთად
    if not hits and session and session.topic:
        hits = retriever.search(f"{session.topic} {question}")

    if not hits:
        say(
            "ამ საკითხზე მოწოდებულ დოკუმენტებში პასუხი ვერ ვიპოვე. "
            "გთხოვთ, მიმართოთ ადამიანური რესურსების სამსახურს."
        )
        return

    if session and len(question.split()) >= TOPIC_MIN_WORDS:
        session.topic = question

    say(llm.answer_policy_question(question, build_context(hits)))


#2. ბალანსი 


async def show_balance(mcp: LeaveMCPClient, say: Say, year: int | None = None) -> None:
    payload = await mcp.call("get_all_leave_balances", year=year)
    balances = payload["balances"]

    say(f"თქვენი შვებულების ნაშთი {payload['year']} წლისთვის:")
    for item in balances:
        if not item["tracked"]:
            say(f"  • {item['leave_type']}: წლიური ბალანსი არ აქვს (მუხლი 5.1)")
            continue
        if not item["known"]:
            say(f"  • {item['leave_type']}: მონაცემი არ არის")
            continue

        say(
            f"  • {item['leave_type']}: ხელმისაწვდომი "
            f"{item['available_days']} დღე  "
            f"(კუთვნილი {item['entitled_days']}"
            + (f" + გადმოტანილი {item['carried_over_days']}"
               if item["carried_over_days"] else "")
            + f", დამტკიცებული {item['approved_days']}, "
            f"განხილვაში {item['pending_days']})"
        )
        if item["note"]:
            say(f"      {item['note']}")


# 3. არსებული მოთხოვნების ნახვა


STATUS_LABELS = {
    "pending": "განხილვაში",
    "approved": "დამტკიცებული",
    "rejected": "უარყოფილი",
    "cancelled": "გაუქმებული",
}


async def list_requests_flow(
    mcp: LeaveMCPClient,
    say: Say,
    *,
    leave_type: str | None = None,
) -> None:
    """უკვე გაგზავნილი მოთხოვნების ჩვენება — ახალს არ ქმნის."""
    payload = await mcp.call("list_leave_requests", leave_type=leave_type)
    requests = payload["requests"]

    if not requests:
        say("შვებულების მოთხოვნები არ მოიძებნა.")
        return

    say(f"თქვენი შვებულების მოთხოვნები ({payload['count']}):")
    for item in requests:
        status = STATUS_LABELS.get(item["status"], item["status"])
        say(
            f"  • #{item['request_id']} · {item['leave_type']} · "
            f"{item['start_date']} – {item['end_date']} · "
            f"{item['days']} დღე · {status}"
        )


# 4. მოთხოვნის შექმნა


async def _leave_types(mcp: LeaveMCPClient) -> dict[str, dict]:
    payload = await mcp.call("list_leave_types")
    return {item["code"]: item for item in payload["leave_types"]}


def _show_violations(payload: dict, say: Say) -> None:
    say("მოთხოვნა ვერ შეიქმნა:")
    for violation in payload["violations"]:
        say(f"  • {violation['message']}")
        say(f"    საფუძველი: {violation['policy_reference']}")
        hint = REDIRECTS.get(violation.get("redirect_to") or "")
        if hint:
            say(f"    {hint}")


async def create_request_flow(
    *,
    mcp: LeaveMCPClient,
    intent: Intent,
    text: str,
    today: date,
    ask: Ask,
    say: Say,
    session: Session,
) -> None:
    types = await _leave_types(mcp)

    #სახე
    code = intent.leave_type
    if code not in types:
        answer = await ask("რა სახის შვებულება გჭირდებათ? (მოკლედ აღწერეთ მიზეზი)")
        code = detect_leave_type(answer)
        if code not in types:
            say("ვერ გავარკვიე შვებულების სახე. სცადეთ თავიდან, "
                "მაგალითად „ავად ვარ“ ან „დასვენება მინდა“.")
            return

    leave_type = types[code]
    # თემა ეწერება მაშინვე, რომ გადამისამართების შემდეგ დასმულმა
    # „რა წესებია?“-მ სწორი მუხლი იპოვოს
    session.topic = leave_type["name"]

    if not leave_type["assistant_can_create"]:
        say(
            f"„{leave_type['name']}“ მოთხოვნას ასისტენტი ვერ ქმნის. "
            f"წესები აღწერილია: {leave_type['policy_reference']}."
        )
        say(
            REDIRECTS["portal"] if leave_type["self_service"] else REDIRECTS["hr"]
        )
        say("წესებზე კითხვა თუ გაქვთ, სიამოვნებით გიპასუხებთ.")
        return

    # თარიღები
    period = parse_dates(intent.date_text or text, today)
    if period is None:
        answer = await ask(
            "რომელ თარიღებზე? (მაგალითად „15 ივნისიდან 19-მდე“ ან „2026-11-16 2026-11-20“)"
        )
        period = parse_dates(answer, today)
    if period is None:
        say("თარიღები ვერ ამოვიცანი. გთხოვთ, მიუთითოთ ფორმატით 2026-11-16.")
        return
    start, end = period

    # დამატებითი სლოტები
    reason = intent.reason
    if code == "UNPAID" and not reason:
        reason = await ask("მოკლედ მიუთითეთ მიზეზი (უხელფასო შვებულებას სჭირდება):")

    sick_period_known = False
    if code == "SICK" and start > today:
        answer = await ask(
            "მომავალი თარიღით ავადმყოფობა აღირიცხება მხოლოდ მაშინ, როცა "
            "პერიოდი წინასწარ ცნობილია (მაგალითად დაგეგმილი ოპერაცია). "
            "დაადასტურებთ, რომ ასეა? (კი/არა)"
        )
        sick_period_known = _is_yes(answer)

    # შემოწმება ჩაწერის გარეშე (მუხლი 12.2)
    try:
        preview = await mcp.call(
            "preview_leave_request",
            leave_type=code,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            reason=reason,
            sick_period_known=sick_period_known,
            conversation_id=session.conversation_id,
        )
    except ToolCallError as exc:
        say(str(exc))
        return

    if not preview["can_create"]:
        _show_violations(preview, say)
        return

    unit = "კალენდარული" if leave_type["day_unit"] == "calendar" else "სამუშაო"
    say("გთხოვთ, დაადასტუროთ:")
    say(f"  სახე:     {leave_type['name']} ({code})")
    say(f"  პერიოდი:  {start:%d.%m.%Y} – {end:%d.%m.%Y}")
    say(f"  დღეები:   {preview['days']} {unit} დღე")
    if reason:
        say(f"  მიზეზი:   {reason}")

    balance = preview.get("balance") or {}
    if balance.get("available_days") is not None:
        say(f"  ნაშთი:    {balance['available_days']} დღე (შექმნამდე)")

    answer = await ask("შევქმნა მოთხოვნა? (კი/არა)")
    if not _is_yes(answer):
        say("გასაგებია, მოთხოვნა არ შემიქმნია.")
        return

    try:
        result = await mcp.call(
            "create_leave_request",
            leave_type=code,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            reason=reason,
            sick_period_known=sick_period_known,
            proposal_id=preview["proposal_id"],
            conversation_id=session.conversation_id,
        )
    except ToolCallError as exc:
        say(str(exc))
        return

    if result.get("already_confirmed"):
        say(f"ეს მოთხოვნა უკვე დარეგისტრირებულია (#{result['request_id']}).")
        return
    if not result.get("created"):
        _show_violations(result, say)
        return

    say(f"✓ მოთხოვნა #{result['request_id']} დარეგისტრირდა.")
    say(result["message"])
