"""HR demos დემონსტრაცია.

    python -m scripts.hr_demo

CLI ასისტენტი თანამშრომლის არხია და პოლიტიკით მოთხოვნებს ვერ ამტკიცებს
(მუხლები 4.8, 12.3). ეს სკრიპტი იმავე MCP სერვერს HR როლით უერთდება და
აჩვენებს, რომ ერთი და იგივე სერვერი ორივე მხარეს ემსახურება, უფლებებს კი
როლი განსაზღვრავს.

სკრიპტი ბაზას ცვლის (ამტკიცებს ერთ მოთხოვნას). საწყისი მდგომარეობის
დასაბრუნებლად: python -m src.db.seed
"""

from __future__ import annotations

import asyncio

from src.cli.mcp_client import LeaveMCPClient, ToolCallError

EMPLOYEE_ID = "E1001"
HR_ID = "E1007"


def show(title: str) -> None:
    print(f"\n{'─' * 70}\n{title}\n{'─' * 70}")


async def main() -> None:
    show("1. თანამშრომლის არხი — დამტკიცება აკრძალულია (მუხლები 4.8, 12.3)")
    async with LeaveMCPClient(EMPLOYEE_ID, role="employee") as assistant:
        pending = await assistant.call("list_leave_requests", status="pending")
        if not pending["requests"]:
            print("განხილვაში მყოფი მოთხოვნა არ არის. გაუშვით: python -m src.db.seed")
            return

        request_id = pending["requests"][0]["request_id"]
        print(f"განხილვაშია მოთხოვნა #{request_id}")

        try:
            await assistant.call(
                "decide_leave_request", request_id=request_id, decision="approve"
            )
            print("⚠ დამტკიცება გაიარა — ეს პოლიტიკის დარღვევაა!")
        except ToolCallError as exc:
            print(f"✓ უარი: {exc}")

        try:
            await assistant.call(
                "get_leave_balance", leave_type="ANNUAL", employee_id="E1002"
            )
            print("⚠ სხვისი ბალანსი გაიცა — ეს მუხლი 5.2-ის დარღვევაა!")
        except ToolCallError as exc:
            print(f"✓ უარი: {exc}")

    show("2. HR არხი — იგივე სერვერი, სხვა უფლებები")
    async with LeaveMCPClient(HR_ID, role="hr") as hr:
        before = await hr.call(
            "get_leave_balance", leave_type="ANNUAL", employee_id=EMPLOYEE_ID
        )
        print(
            f"დამტკიცებამდე: ხელმისაწვდომი {before['available_days']} "
            f"(დამტკიცებული {before['approved_days']}, "
            f"განხილვაში {before['pending_days']})"
        )

        decided = await hr.call(
            "decide_leave_request",
            request_id=request_id,
            decision="approve",
            decided_by="E1010",
        )
        request = decided["request"]
        print(
            f"✓ მოთხოვნა #{request['request_id']} → {request['status']}, "
            f"გადაწყვიტა {request['decided_by']}"
        )

        after = await hr.call(
            "get_leave_balance", leave_type="ANNUAL", employee_id=EMPLOYEE_ID
        )
        print(
            f"დამტკიცების შემდეგ: ხელმისაწვდომი {after['available_days']} "
            f"(დამტკიცებული {after['approved_days']}, "
            f"განხილვაში {after['pending_days']})"
        )
        print("→ ჯამი არ იცვლება: განხილვაში მყოფი დღეები დამტკიცებულში გადავიდა "
              "(მუხლი 5.1)")

    print("\nსაწყისი მონაცემების დასაბრუნებლად: python -m src.db.seed")


if __name__ == "__main__":
    asyncio.run(main())
