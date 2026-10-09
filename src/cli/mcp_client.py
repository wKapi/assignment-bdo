"""MCP კლიენტი CLI-სთვის.

CLI ბაზას პირდაპირ არ ეხება: ის დავალება 1-ში შექმნილ MCP სერვერს
ცალკე პროცესად უშვებს და stdio-თი ესაუბრება, ზუსტად ისე, როგორც
ნებისმიერი სხვა MCP კლიენტი. ასე ერთი და იგივე ხელსაწყოები ემსახურება
ასისტენტსაც და გარე კლიენტსაც.
"""

from __future__ import annotations
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import ROOT


class ToolCallError(RuntimeError):
    """სერვერმა შესრულებაზე შეცდომა დააბრუნა."""


class LeaveMCPClient:
    """MCP სერვერის ხელსაწყოებზე."""

    def __init__(self, employee_id: str, role: str = "employee") -> None:
        self.employee_id = employee_id
        self.role = role
        self._session: ClientSession | None = None
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "LeaveMCPClient":
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server.server"],
            cwd=str(ROOT),
            env={
                **os.environ,
                "CURRENT_EMPLOYEE_ID": self.employee_id,
                "CURRENT_ROLE": self.role,
            },
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._stack.aclose()
        self._session = None

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("MCP სესია არ არის გახსნილი.")

        result = await self._session.call_tool(tool, arguments)
        if result.is_error:
            message = next(
                (b.text for b in result.content if getattr(b, "type", "") == "text"),
                "უცნობი შეცდომა",
            )
            raise ToolCallError(_clean(message))

        return result.structured_content or {}

    async def list_tool_names(self) -> list[str]:
        assert self._session is not None
        return [tool.name for tool in (await self._session.list_tools()).tools]


def _clean(message: str) -> str:
    """SDK-ის პრეფიქსს აშორებს, რომ თანამშრომლისგან სუფთა ტექსტი მივიდეს."""
    marker = "Error executing tool "
    if message.startswith(marker):
        _, _, tail = message.partition(": ")
        return tail or message
    return message
