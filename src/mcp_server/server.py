"""NorthStar HR — MCP სერვერი (stdio).

გაშვება:

    python -m src.mcp_server.server

სერვერი ორივე მხარეს ემსახურება: HR ასისტენტსა და HR პორტალს. როლი
`CURRENT_ROLE` ცვლადით განისაზღვრება (`employee` | `hr`) და
`src/mcp_server/auth.py`-ში მოწმდება.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.config import DATABASE_PATH
from src.db.repository import Repository, connect
from src.mcp_server import tools
from src.mcp_server.auth import PermissionDenied, Principal, current_principal

INSTRUCTIONS = """\
შპს „ნორთსტარ სერვისეზის“ შვებულებების სერვერი.

წესები „შვებულებისა და გაცდენის პოლიტიკა v4.0“-დან მოდის. ხელსაწყოები
თავად ამოწმებენ პოლიტიკას: თუ მოთხოვნა ვერ იქმნება, პასუხში `violations`
სიაა, სადაც თითოეულ ჩანაწერს აქვს `message`, `policy_reference` და
`redirect_to`. ამ ტექსტს ცვლილებების გარეშე გადაეცით თანამშრომელს.

მოთხოვნის შექმნამდე გამოიძახეთ `preview_leave_request`, აჩვენეთ
თანამშრომელს სახე, თარიღები და დღეების რაოდენობა, მიიღეთ მკაფიო
დადასტურება და მხოლოდ ამის შემდეგ გამოიძახეთ `create_leave_request`
მიღებული `proposal_id`-ით.
"""

server = MCPServer(
    name="northstar-leave",
    title="NorthStar HR — შვებულებები",
    version="0.1.0",
    instructions=INSTRUCTIONS,
    # უფლების უარი მოსალოდნელი შედეგია და არა ავარია — INFO დონეზე ის
    # კლიენტის ტერმინალში stack-ის სახით იყრებოდა. შეცდომა კლიენტს
    # ToolError-ით მაინც მიუვა.
    log_level="WARNING",
)


@contextmanager
def session() -> Iterator[tuple[Repository, Principal]]:
    """ყოველ გამოძახებაზე ცალკე კავშირი — thread-safe და მოკლე სიცოცხლით.

    უფლებისა და ვალიდაციის შეცდომები `ToolError`-ად გარდაიქმნება, რათა
    კლიენტს ქართული ახსნა და პოლიტიკის მუხლი მიუვიდეს და არა სერვერის
    გენერიკული stack trace.
    """
    if not DATABASE_PATH.exists():
        raise ToolError(
            f"ბაზა არ არსებობს: {DATABASE_PATH}. ჯერ გაუშვით `python -m src.db.seed`."
        )
    conn = connect()
    try:
        yield Repository(conn), current_principal()
    except PermissionDenied as exc:
        raise ToolError(f"{exc.message} ({exc.policy_ref})") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        conn.close()



@server.tool()
def list_leave_types() -> dict[str, Any]:
    """შვებულების ხელმისაწვდომი სახეების სია.

    თითოეულზე აბრუნებს დათვლის ერთეულს (სამუშაო/კალენდარული დღეები),
    წლიურ ლიმიტს, პოლიტიკის მუხლს და იმას, შეუძლია თუ არა ასისტენტს
    ამ სახის მოთხოვნის შექმნა (`assistant_can_create`).
    """
    with session() as (repo, principal):
        return tools.list_leave_types(repo, principal)


@server.tool()
def get_leave_balance(
    leave_type: str, year: int | None = None, employee_id: str | None = None
) -> dict[str, Any]:
    """თანამშრომლის დარჩენილი დღეები მოცემული წლისა და სახისთვის.

    ბრუნდება დაშლილი სახით: კუთვნილი, გადმოტანილი, დამტკიცებული,
    განხილვაში და ხელმისაწვდომი დღეები. `year`-ის გამოტოვებისას
    მიმდინარე შვებულების წელი გამოიყენება. თანამშრომლის როლში
    `employee_id` უგულებელყოფილია — ბრუნდება მხოლოდ საკუთარი ბალანსი.
    """
    with session() as (repo, principal):
        return tools.get_leave_balance(
            repo, principal, leave_type=leave_type, year=year, employee_id=employee_id
        )


@server.tool()
def get_all_leave_balances(
    year: int | None = None, employee_id: str | None = None
) -> dict[str, Any]:
    """ყველა სახის ბალანსი ერთ პასუხში — „ჩემი შვებულებები“ ხედისთვის."""
    with session() as (repo, principal):
        return tools.get_all_leave_balances(
            repo, principal, year=year, employee_id=employee_id
        )


@server.tool()
def list_leave_requests(
    employee_id: str | None = None,
    status: str | None = None,
    leave_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """შვებულების მოთხოვნების სია ფილტრებით.

    `status`: pending | approved | rejected | cancelled.
    `date_from` / `date_to` (YYYY-MM-DD) პერიოდთან გადაკვეთაზე ფილტრავს.
    """
    with session() as (repo, principal):
        return tools.list_leave_requests(
            repo,
            principal,
            employee_id=employee_id,
            status=status,
            leave_type=leave_type,
            date_from=date_from,
            date_to=date_to,
        )


@server.tool()
def preview_leave_request(
    leave_type: str,
    start_date: str,
    end_date: str,
    employee_id: str | None = None,
    reason: str | None = None,
    sick_period_known: bool = False,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """ამოწმებს მოთხოვნას ჩაწერის გარეშე და ამზადებს დასადასტურებელ შეთავაზებას.

    აბრუნებს დღეების რაოდენობას, მიმდინარე ბალანსს და, უარის შემთხვევაში,
    `violations` სიას მუხლების მითითებით. წარმატებისას `proposal_id`
    ბრუნდება — სწორედ ის უნდა გადასცეთ `create_leave_request`-ს.
    """
    with session() as (repo, principal):
        return tools.preview_leave_request(
            repo,
            principal,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            employee_id=employee_id,
            reason=reason,
            sick_period_known=sick_period_known,
            conversation_id=conversation_id,
        )


@server.tool()
def create_leave_request(
    leave_type: str,
    start_date: str,
    end_date: str,
    employee_id: str | None = None,
    reason: str | None = None,
    sick_period_known: bool = False,
    proposal_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """ქმნის შვებულების მოთხოვნას სტატუსით „განხილვის პროცესში“.

    ასისტენტი მოთხოვნას მხოლოდ ANNUAL, SICK და UNPAID სახეებზე ქმნის.
    UNPAID-ს მოკლე მიზეზი სჭირდება (`reason`). მომავალი თარიღით SICK
    აღირიცხება მხოლოდ მაშინ, როცა პერიოდი წინასწარ ცნობილია
    (`sick_period_known=true`).

    `proposal_id`-ის გადაცემისას ოპერაცია იდემპოტენტურია: განმეორებითი
    გამოძახება იმავე `request_id`-ს აბრუნებს და დუბლიკატს არ ქმნის.
    """
    with session() as (repo, principal):
        return tools.create_leave_request(
            repo,
            principal,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            employee_id=employee_id,
            reason=reason,
            sick_period_known=sick_period_known,
            proposal_id=proposal_id,
            conversation_id=conversation_id,
        )


@server.tool()
def decide_leave_request(
    request_id: int, decision: str, decided_by: str | None = None
) -> dict[str, Any]:
    """მოთხოვნის დამტკიცება ან უარყოფა (`decision`: approve | reject).

    მხოლოდ HR არხისთვისაა: მუხლი 12.3-ით ასისტენტს მოთხოვნის დამტკიცება
    ან უარყოფა არ შეუძლია.
    """
    with session() as (repo, principal):
        return tools.decide_leave_request(
            repo, principal, request_id=request_id,
            decision=decision, decided_by=decided_by,
        )


@server.tool()
def cancel_leave_request(request_id: int) -> dict[str, Any]:
    """განხილვაში მყოფი მოთხოვნის გაუქმება.

    მხოლოდ HR არხისთვისაა: მუხლი 4.8-ით „HR ასისტენტი მოთხოვნებს არ
    აუქმებს და არ ცვლის“.
    """
    with session() as (repo, principal):
        return tools.cancel_leave_request(repo, principal, request_id=request_id)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
