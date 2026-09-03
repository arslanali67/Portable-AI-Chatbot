"""get_current_datetime — ISO-8601 timestamp via stdlib zoneinfo.

Safe to run in-process with no isolation beyond a timeout: a pure read of
the server clock, zero I/O beyond the OS's already-trusted tz database.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.base import ToolExecutionError


class DateTimeTool:
    name = "get_current_datetime"
    description = (
        "Get the current date and time, optionally in a specific IANA timezone "
        "(defaults to UTC if omitted)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone name, e.g. 'America/New_York'. Defaults to UTC.",
            }
        },
        "required": [],
    }

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        organization_id: int,
        chatbot_id: int,
        db_session: AsyncSession,
    ) -> str:
        tz_name = arguments.get("timezone")
        if tz_name:
            if not isinstance(tz_name, str):
                raise ToolExecutionError("'timezone' must be a string")
            try:
                tz = ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ToolExecutionError(f"unknown timezone: {tz_name}") from exc
        else:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).isoformat()
