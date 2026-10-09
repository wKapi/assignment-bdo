"""CLI-ის ტესტები — თარიღები, განზრახვა, mock LLM და ნაკადები.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.cli.dates import parse_dates
from src.cli.flows import Session, create_request_flow, show_balance
from src.cli.mcp_client import _clean
from src.llm.client import LLMClient, detect_leave_type
from src.mcp_server import tools
from src.mcp_server.auth import PermissionDenied, Principal, Role
from tests.conftest import TODAY




@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15 ივნისიდან 19-მდე", (date(2026, 6, 15), date(2026, 6, 19))),
        ("15 ივნისიდან 19 ივნისამდე", (date(2026, 6, 15), date(2026, 6, 19))),
        ("16 ნოემბრიდან 20-მდე დასვენება", (date(2026, 11, 16), date(2026, 11, 20))),
        ("3 დეკემბერს", (date(2026, 12, 3), date(2026, 12, 3))),
        ("2026-11-16 2026-11-20", (date(2026, 11, 16), date(2026, 11, 20))),
        ("16.11.2026", (date(2026, 11, 16), date(2026, 11, 16))),
        ("დღეს", (TODAY, TODAY)),
        ("ხვალ", (date(2026, 10, 20), date(2026, 10, 20))),
        ("ზეგ", (date(2026, 10, 21), date(2026, 10, 21))),
    ],
)
def test_georgian_date_parsing(text, expected):
    assert parse_dates(text, TODAY) == expected


def test_dates_use_app_today_not_the_real_clock():
    """„ხვალ“ APP_TODAY-ს მიმართ უნდა დაითვალოს."""
    assert parse_dates("ხვალ", date(2026, 10, 19)) == (
        date(2026, 10, 20),
        date(2026, 10, 20),
    )


@pytest.mark.parametrize("text", ["", "გამარჯობა", "რამდენი დღე მეკუთვნის?"])
def test_text_without_dates(text):
    assert parse_dates(text, TODAY) is None


def test_invalid_calendar_date_is_rejected():
    assert parse_dates("31 თებერვალს", TODAY) is None


#ტიპის ამოცნობა


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ავად ვარ", "SICK"),
        ("გავცივდი და ექიმთან უნდა წავიდე", "SICK"),
        ("დასვენება მინდა", "ANNUAL"),
        ("უხელფასო შვებულება მჭირდება", "UNPAID"),
        ("ბებია გარდამეცვალა", "BEREAVEMENT"),
        ("ACCA-ს გამოცდა მაქვს", "STUDY"),
        ("დეკრეტში გავდივარ", "PARENTAL"),
        ("გამარჯობა", None),
    ],
)
def test_all_six_leave_types_are_recognised(text, expected):
    """ლექსიკონის მოთხოვნა: ასისტენტმა ექვსივე სახე უნდა ამოიცნოს."""
    assert detect_leave_type(text) == expected


# mock LLM 


def test_mock_classifies_intents():
    llm = LLMClient(provider="mock")
    assert llm.classify("რამდენი დღე დამრჩა?").intent == "balance"
    assert llm.classify("როდის მჭირდება სამედიცინო ცნობა?").intent == "policy_question"
    assert llm.classify("ავად ვარ, დღეს ვერ მოვალ").intent == "create_request"
    assert llm.classify("გამარჯობა").intent == "other"


def test_mock_answer_without_context_says_not_found():
    llm = LLMClient(provider="mock")
    answer = llm.answer_policy_question("რამე", "")
    assert "ვერ ვიპოვე" in answer


def test_mock_answer_keeps_citations():
    llm = LLMClient(provider="mock")
    context = (
        "[1] შვებულებისა და გაცდენის პოლიტიკა v4.0, მუხლი 4.7\n"
        "(წყაროს ტიპი: მოქმედი პოლიტიკა)\n"
        "არაუმეტეს 5 სამუშაო დღე გადადის."
    )
    answer = llm.answer_policy_question("გადატანა?", context)
    assert "მუხლი 4.7" in answer
    assert "არაუმეტეს 5 სამუშაო დღე" in answer


def test_anthropic_provider_requires_a_key(monkeypatch):
    monkeypatch.setattr("src.llm.client.ANTHROPIC_API_KEY", "")
    with pytest.raises(Exception, match="ANTHROPIC_API_KEY"):
        LLMClient(provider="anthropic")


# MCP შეცდომის ტექსტი


def test_tool_error_message_is_unwrapped():
    raw = "Error executing tool cancel_leave_request: ასისტენტს არ შეუძლია (მუხლი 4.8)"
    assert _clean(raw) == "ასისტენტს არ შეუძლია (მუხლი 4.8)"


# ნაკადები


class FakeMCP:
    """`LeaveMCPClient.call`-ის შემცვლელი, რომელიც რეალურ ხელსაწყოებს ეძახის."""

    def __init__(self, repo, employee_id: str, role: Role = Role.EMPLOYEE) -> None:
        self.repo = repo
        self.principal = Principal(role=role, employee_id=employee_id)
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, **arguments: Any) -> dict:
        self.calls.append((tool, arguments))
        function = getattr(tools, tool)
        try:
            return function(self.repo, self.principal, **arguments)
        except PermissionDenied as exc:
            raise RuntimeError(str(exc)) from exc


class Transcript:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.lines: list[str] = []

    async def ask(self, prompt: str) -> str:
        self.lines.append(f"? {prompt}")
        return self.answers.pop(0) if self.answers else ""

    def say(self, message: str) -> None:
        self.lines.append(message)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.mark.asyncio
async def test_balance_flow_separates_approved_and_pending(repo):
    mcp = FakeMCP(repo, "E1001")
    transcript = Transcript([])

    await show_balance(mcp, transcript.say)

    assert "ANNUAL" in transcript.text
    assert "დამტკიცებული 15" in transcript.text
    assert "განხილვაში 3" in transcript.text
    assert "წლიური ბალანსი არ აქვს" in transcript.text  


@pytest.mark.asyncio
async def test_create_flow_confirms_before_writing(repo):
    """მუხლი 12.2 — შექმნამდე სახე, თარიღები და დღეები უნდა გამოჩნდეს."""
    mcp = FakeMCP(repo, "E1013")
    transcript = Transcript(["კი"])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "ANNUAL", date_text="16 ნოემბრიდან 20-მდე"),
        text="16 ნოემბრიდან 20-მდე დასვენება მინდა",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "5 სამუშაო დღე" in transcript.text
    assert "16.11.2026" in transcript.text
    assert "დარეგისტრირდა" in transcript.text

    called = [name for name, _ in mcp.calls]
    assert called.index("preview_leave_request") < called.index("create_leave_request")


@pytest.mark.asyncio
async def test_create_flow_aborts_when_user_declines(repo):
    mcp = FakeMCP(repo, "E1013")
    transcript = Transcript(["არა"])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "ANNUAL", date_text="2026-11-16 2026-11-20"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "არ შემიქმნია" in transcript.text
    assert "create_leave_request" not in [name for name, _ in mcp.calls]


@pytest.mark.asyncio
async def test_create_flow_explains_refusal_with_article(repo):
    mcp = FakeMCP(repo, "E1013")
    transcript = Transcript([])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "ANNUAL", date_text="2026-10-20 2026-10-21"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "ვერ შეიქმნა" in transcript.text
    assert "მუხლი 4.4" in transcript.text
    assert "27.10.2026" in transcript.text  # შემოთავაზებული ალტერნატივა


@pytest.mark.asyncio
async def test_create_flow_redirects_unsupported_types(repo):
    mcp = FakeMCP(repo, "E1009")
    transcript = Transcript([])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "STUDY", date_text="2026-12-07 2026-12-08"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "ასისტენტი ვერ ქმნის" in transcript.text
    assert "მუხლი 9" in transcript.text
    assert "preview_leave_request" not in [name for name, _ in mcp.calls]


@pytest.mark.asyncio
async def test_unpaid_flow_asks_for_a_reason(repo):
    mcp = FakeMCP(repo, "E1013")
    transcript = Transcript(["ოჯახური გარემოება", "კი"])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "UNPAID", date_text="2026-12-01 2026-12-05"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "მიზეზი" in transcript.text
    assert "დარეგისტრირდა" in transcript.text


@pytest.mark.asyncio
async def test_future_sick_leave_asks_whether_the_period_is_known(repo):
    mcp = FakeMCP(repo, "E1001")
    transcript = Transcript(["კი", "კი"])

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "SICK", date_text="2026-11-02 2026-11-03"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=Session(conversation_id="conv-test"),
    )

    assert "წინასწარ ცნობილია" in transcript.text
    assert "დარეგისტრირდა" in transcript.text



def test_followup_question_uses_the_previous_topic(retriever_for_cli):
    """„რა წესებია?“ მარტო არაფერს ხვდება, თემასთან ერთად კი — სწორ მუხლს."""
    llm = LLMClient(provider="mock")
    session = Session(topic="სასწავლო და საგამოცდო შვებულება")
    transcript = Transcript([])

    from src.cli.flows import answer_policy_question

    answer_policy_question("რა წესებია?", retriever_for_cli, llm, transcript.say, session)

    assert "ვერ ვიპოვე" not in transcript.text
    assert "სასწავლო" in transcript.text or "მუხლი 9" in transcript.text


def test_followup_without_a_topic_still_says_not_found(retriever_for_cli):
    llm = LLMClient(provider="mock")
    transcript = Transcript([])

    from src.cli.flows import answer_policy_question

    answer_policy_question("რა წესებია?", retriever_for_cli, llm, transcript.say, Session())
    assert "ვერ ვიპოვე" in transcript.text


def test_substantive_question_becomes_the_new_topic(retriever_for_cli):
    llm = LLMClient(provider="mock")
    session = Session()
    transcript = Transcript([])

    from src.cli.flows import answer_policy_question

    question = "რამდენი დღე გადადის მომდევნო წელზე?"
    answer_policy_question(question, retriever_for_cli, llm, transcript.say, session)
    assert session.topic == question


@pytest.mark.asyncio
async def test_redirect_sets_the_topic_for_followups(repo):
    """გადამისამართების შემდეგ „რა წესებია?“ უნდა მუშაობდეს."""
    mcp = FakeMCP(repo, "E1009")
    transcript = Transcript([])
    session = Session(conversation_id="conv-test")

    from src.llm.client import Intent

    await create_request_flow(
        mcp=mcp,
        intent=Intent("create_request", "STUDY", date_text="2026-12-07 2026-12-08"),
        text="",
        today=TODAY,
        ask=transcript.ask,
        say=transcript.say,
        session=session,
    )

    assert session.topic == "სასწავლო და საგამოცდო შვებულება"
