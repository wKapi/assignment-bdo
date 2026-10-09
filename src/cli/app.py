"""CLI ასისტენტი.აპლიკაცია ბაზას პირდაპირ არ ეხება: ის MCP სერვერს ცალკე პროცესად
უშვებს და მის ხელსაწყოებს იძახებს
"""

from __future__ import annotations
import argparse
import asyncio
import sys

from rich.console import Console
from rich.panel import Panel

from src.cli.flows import (
    Session,
    answer_policy_question,
    create_request_flow,
    list_requests_flow,
    show_balance,
)
from src.cli.mcp_client import LeaveMCPClient, ToolCallError
from src.config import CURRENT_EMPLOYEE_ID, CURRENT_ROLE, DATABASE_PATH, INDEX_DIR
from src.core.clock import today
from src.llm.client import LLMClient, LLMError
from src.rag.index import INDEX_FILE
from src.rag.retriever import IndexNotBuilt, Retriever

console = Console()

HELP = """\
შემიძლია:
  • ვუპასუხო კითხვებს კომპანიის პოლიტიკებზე (წყაროს მითითებით)
  • გაჩვენოთ თქვენი დარჩენილი შვებულების ნაშთი
  • გაჩვენოთ უკვე გაგზავნილი მოთხოვნები და მათი სტატუსი
  • შევქმნა შვებულების მოთხოვნა (ANNUAL, SICK, UNPAID)

ბრძანებები: /balance — ნაშთი, /requests — მოთხოვნები,
            /help — დახმარება, /exit — გასვლა
"""


def say(message: str) -> None:
    console.print(message)


async def ask(prompt: str) -> str:
    console.print(f"[bold cyan]{prompt}[/bold cyan]")
    return (await asyncio.to_thread(input, "> ")).strip()


def _preflight() -> bool:
    """გაშვებამდე ამოწმებს, რომ ბაზა და ინდექსი ადგილზეა."""
    ok = True
    if not DATABASE_PATH.exists():
        console.print(
            f"[red]ბაზა არ არსებობს:[/red] {DATABASE_PATH}\n"
            "გაუშვით: python -m src.db.seed"
        )
        ok = False
    if not (INDEX_DIR / INDEX_FILE).exists():
        console.print(
            f"[red]RAG ინდექსი არ არსებობს:[/red] {INDEX_DIR / INDEX_FILE}\n"
            "გაუშვით: python -m src.rag.index"
        )
        ok = False
    return ok


async def run(employee_id: str, role: str) -> int:
    if not _preflight():
        return 1

    try:
        retriever = Retriever()
    except IndexNotBuilt as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    try:
        llm = LLMClient()
    except LLMError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    mode = "mock" if llm.is_mock else f"anthropic ({llm.model})"
    console.print(
        Panel(
            f"შპს „BDO“ — HR ასისტენტი\n"
            f"თანამშრომელი: {employee_id} · როლი: {role} · "
            f"თარიღი: {today():%d.%m.%Y}\n"
            f"LLM: {mode} · დოკუმენტების ნაწილები: {len(retriever)}",
            border_style="cyan",
        )
    )
    console.print(HELP)

    session = Session()

    async with LeaveMCPClient(employee_id, role) as mcp:
        while True:
            try:
                message = (await asyncio.to_thread(input, "\n> ")).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nნახვამდის")
                return 0

            if not message:
                continue
            if message in {"/exit", "/quit", "გამოსვლა"}:
                console.print("ნახვამდის")
                return 0
            if message == "/help":
                console.print(HELP)
                continue

            try:
                if message == "/balance":
                    await show_balance(mcp, say)
                    continue
                if message == "/requests":
                    await list_requests_flow(mcp, say)
                    continue

                intent = llm.classify(message)

                if intent.intent == "balance":
                    await show_balance(mcp, say)
                elif intent.intent == "list_requests":
                    await list_requests_flow(
                        mcp, say, leave_type=intent.leave_type
                    )
                elif intent.intent == "create_request":
                    await create_request_flow(
                        mcp=mcp,
                        intent=intent,
                        text=message,
                        today=today(),
                        ask=ask,
                        say=say,
                        session=session,
                    )
                elif intent.intent == "policy_question":
                    answer_policy_question(message, retriever, llm, say, session)
                else:
                    console.print(HELP)

            except ToolCallError as exc:
                console.print(f"[yellow]{exc}[/yellow]")
            except LLMError as exc:
                console.print(f"[red]{exc}[/red]")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="BDO",
        description="„BDO“ HR ასისტენტი (ქართული CLI).",
    )
    parser.add_argument(
        "--employee", default=CURRENT_EMPLOYEE_ID,
        help="თანამშრომლის ID, მაგ. E1002",
    )
    parser.add_argument(
        "--role", default=CURRENT_ROLE, choices=["employee", "hr"],
        help="არხი: employee (ასისტენტი) ან hr (პორტალი)",
    )
    args = parser.parse_args()

    # CLI თანამშრომლის არხია: ყველა ნაკადი საკუთარ მონაცემებზე მუშაობს.
    # HR როლი სერვერზე employee_id-ს ითხოვს (მუხლი 5.2), რასაც CLI არ კითხულობს,
    # ამიტომ აქ ვჩერდებით და HR არხზე ვამისამართებთ.
    if args.role == "hr":
        console.print(
            "[yellow]CLI ასისტენტი თანამშრომლის არხია და HR როლით არ ეშვება.[/yellow]\n"
            "HR ხედავს სხვისი მონაცემებს, რაც კონკრეტულ employee_id-ს მოითხოვს "
            "(მუხლი 5.2).\n\n"
            "HR არხისთვის გამოიყენეთ:\n"
            "  • python -m scripts.hr_demo — HR არხის დემო\n"
            "  • python -m src.mcp_server.server — MCP სერვერი HR პორტალისთვის"
        )
        sys.exit(2)

    try:
        sys.exit(asyncio.run(run(args.employee, args.role)))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
