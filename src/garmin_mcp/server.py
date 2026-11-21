"""MCP server for the Garmin Connect Personal API (read-only tools for Claude and ChatGPT).

The HTTP client and auth live in client.py.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer as _Server
from mcp.types import ToolAnnotations

from .client import GarminClient, GarminError

# Logs must go to stderr: stdout is the MCP stdio transport.
logging.basicConfig(level=os.environ.get("GARMIN_LOG_LEVEL", "WARNING"), stream=sys.stderr)

DOWNLOAD_DIR = Path(os.environ.get("GARMIN_DOWNLOAD_DIR", "~/Downloads/garmin")).expanduser()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


client = GarminClient()

mcp = _Server(
    "garmin-connect",
    instructions=(
        "Read-only access to the user's own Garmin Connect health and fitness data. "
        "Dates are YYYY-MM-DD in the user's local calendar; date ranges are inclusive. "
        "Prefer range tools over many single-day calls, and keep ranges modest "
        "(e.g. <= 31 days) to avoid huge responses. Use get_daily_summaries for a "
        "broad daily overview, then drill into specific metrics."
    ),
)
RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _d(value: str, name: str = "date") -> str:
    value = value.strip()
    if value.lower() == "today":
        return _date.today().isoformat()
    if not _DATE_RE.match(value):
        raise GarminError(f"{name} must be YYYY-MM-DD (or 'today'), got {value!r}")
    return value


def _range(start_date: str, end_date: str) -> tuple[str, str]:
    s, e = _d(start_date, "start_date"), _d(end_date, "end_date")
    if s > e:
        raise GarminError("start_date must be on or before end_date")
    return s, e


def _activity_id(activity_id: int | str) -> str:
    s = str(activity_id).strip()
    if not s.isdecimal() or int(s) <= 0:
        raise GarminError("activity_id must be a positive integer")
    return s


# --------------------------------------------------------------------------- #
# Profile / config
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_user_profile_settings() -> Any:
    """Get the user's profile settings (units, birth date, height, weight, sleep times, etc.)."""
    return await client.get_json("/userprofile-service/userprofile/settings")


@mcp.tool(annotations=RO)
async def get_heart_rate_zones() -> Any:
    """Get the user's configured heart rate zones."""
    return await client.get_json("/biometric-service/heartRateZones/v2")


# --------------------------------------------------------------------------- #
# Daily summaries & wellness (date ranges)
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_daily_summaries(start_date: str, end_date: str) -> Any:
    """Daily overview (steps, calories, intensity minutes, resting HR, stress, body battery...)
    for an inclusive date range. Use the same date twice for a single day."""
    s, e = _range(start_date, end_date)
    return await client.get_json("/usersummary-service/v2/dailysummaries", {"startDate": s, "endDate": e})


@mcp.tool(annotations=RO)
async def get_daily_steps(start_date: str, end_date: str) -> Any:
    """Daily step totals and goals for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/usersummary-service/stats/steps/daily/{s}/{e}")


@mcp.tool(annotations=RO)
async def get_daily_stress(start_date: str, end_date: str) -> Any:
    """Daily stress statistics for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/usersummary-service/stats/stress/daily/{s}/{e}")


@mcp.tool(annotations=RO)
async def get_daily_hydration(start_date: str, end_date: str) -> Any:
    """Daily hydration intake and goals for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/usersummary-service/stats/hydration/daily/{s}/{e}")


@mcp.tool(annotations=RO)
async def get_body_battery(start_date: str, end_date: str, chunks: int | None = None) -> Any:
    """Daily Body Battery reports for an inclusive date range.
    `chunks` optionally controls how the server splits the range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(
        "/wellness-service/wellness/bodyBattery/reports/daily",
        {"startDate": s, "endDate": e, "chunks": chunks},
    )


@mcp.tool(annotations=RO)
async def get_wellness_activity_summaries(start_date: str, end_date: str) -> Any:
    """Wellness activity summaries for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/wellnessactivity-service/activity/summary/range/{s}/{e}")


# --------------------------------------------------------------------------- #
# Sleep
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_sleep(date: str) -> Any:
    """Detailed sleep data (stages, scores, timings) for the night ending on `date`."""
    return await client.get_json("/sleep-service/sleep/dailySleep", {"date": _d(date)})


@mcp.tool(annotations=RO)
async def get_sleep_summaries(start_date: str, end_date: str) -> Any:
    """Daily sleep summaries for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(
        "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": s, "endDate": e}
    )


# --------------------------------------------------------------------------- #
# Heart / cardio
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_heart_rate(date: str) -> Any:
    """Intraday heart rate samples plus resting/min/max HR for a single date (can be large)."""
    return await client.get_json("/wellness-service/wellness/dailyHeartRate", {"date": _d(date)})


@mcp.tool(annotations=RO)
async def get_hrv(date: str) -> Any:
    """Heart rate variability (HRV) summary and overnight readings for a single date."""
    return await client.get_json(f"/hrv-service/hrv/{_d(date)}")


@mcp.tool(annotations=RO)
async def get_hrv_summaries(start_date: str, end_date: str) -> Any:
    """Daily HRV summaries (weekly avg, baseline, status) for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/hrv-service/hrv/daily/{s}/{e}")


@mcp.tool(annotations=RO)
async def get_spo2(date: str) -> Any:
    """Pulse Ox (SpO2) and altitude acclimation data for a single date."""
    return await client.get_json(f"/wellness-service/wellness/daily/spo2acclimation/{_d(date)}")


@mcp.tool(annotations=RO)
async def get_fitness_age(date: str) -> Any:
    """Fitness age data as of a date."""
    return await client.get_json(f"/fitnessage-service/fitnessage/v2/{_d(date)}")


# --------------------------------------------------------------------------- #
# Body composition & nutrition
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_weight_measurements(start_date: str, end_date: str) -> Any:
    """All weight / body composition entries for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/weight-service/weight/range/{s}/{e}", {"includeAll": "true"})


@mcp.tool(annotations=RO)
async def get_weight_goals(start_date: str, end_date: str) -> Any:
    """Effective weight goals for an inclusive date range."""
    s, e = _range(start_date, end_date)
    return await client.get_json(f"/goal-service/goal/user/effective/weightgoal/{s}/{e}")


@mcp.tool(annotations=RO)
async def get_food_logs(date: str) -> Any:
    """Nutrition / food log entries for a single date."""
    return await client.get_json(f"/nutrition-service/food/logs/{_d(date)}")


# --------------------------------------------------------------------------- #
# Women's health
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def get_menstrual_cycle_summary(date: str) -> Any:
    """Menstrual cycle summary for a date."""
    return await client.get_json(f"/periodichealth-service/menstrualcycle/summary/{_d(date)}")


@mcp.tool(annotations=RO)
async def get_menstrual_cycle_day_view(date: str, today_date: str = "today") -> Any:
    """Menstrual cycle day view for `date`, relative to `today_date` (defaults to today)."""
    return await client.get_json(
        f"/periodichealth-service/menstrualcycle/dayview/{_d(date)}",
        {"todayDate": _d(today_date, "today_date")},
    )


# --------------------------------------------------------------------------- #
# Activities
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def search_activities(
    start: int = 0,
    limit: int = 20,
    start_date: str | None = None,
    end_date: str | None = None,
    activity_type: str | None = None,
) -> Any:
    """List recorded activities, newest first. Paginate with `start`/`limit` (max 100).
    Optional filters: date range (YYYY-MM-DD) and activity_type (e.g. 'running',
    'cycling', 'swimming', 'strength_training'). Returns activityId values for the
    other activity tools."""
    params: dict[str, Any] = {"start": max(0, start), "limit": min(max(1, limit), 100)}
    if start_date:
        params["startDate"] = _d(start_date, "start_date")
    if end_date:
        params["endDate"] = _d(end_date, "end_date")
    if activity_type:
        params["activityType"] = activity_type
    return await client.get_json("/activitylist-service/activities/search/activities", params)


@mcp.tool(annotations=RO)
async def get_activity(activity_id: int) -> Any:
    """Full details/summary for one activity (distance, pace, HR, splits summary, etc.)."""
    return await client.get_json(f"/activity-service/activity/{_activity_id(activity_id)}")


@mcp.tool(annotations=RO)
async def get_activity_workouts(activity_id: int) -> Any:
    """Structured workouts associated with an activity."""
    return await client.get_json(f"/activity-service/activity/{_activity_id(activity_id)}/workouts")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
async def download_activity_file(activity_id: int, overwrite: bool = False) -> dict[str, Any]:
    """Download the original activity file (ZIP containing the .fit) to GARMIN_DOWNLOAD_DIR
    on the machine running this server. Returns the saved path."""
    aid = _activity_id(activity_id)
    resp = await client.request(
        f"/download-service/files/activity/{aid}",
        accept="application/zip, application/x-zip-compressed, application/octet-stream",
    )
    if not resp.content:
        raise GarminError("Activity download returned an empty file.")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOAD_DIR / f"activity_{aid}.zip"
    if dest.exists() and not overwrite:
        raise GarminError(f"{dest} already exists; pass overwrite=true to replace it.")
    tmp = dest.with_suffix(".zip.part")
    tmp.write_bytes(resp.content)
    tmp.replace(dest)
    return {"path": str(dest), "bytes": len(resp.content)}


# --------------------------------------------------------------------------- #
# Escape hatch for endpoints added to the Swagger spec later
# --------------------------------------------------------------------------- #
@mcp.tool(annotations=RO)
async def garmin_get(path: str, params: dict[str, str] | None = None) -> Any:
    """Raw authenticated GET against the Personal API for endpoints without a dedicated tool.
    `path` must start with '/' (e.g. '/hrv-service/hrv/2026-11-01')."""
    if not path.startswith("/") or "://" in path or ".." in path:
        raise GarminError("path must be an absolute API path like '/service/resource'")
    return await client.get_json(path, params)


def main() -> None:
    transport = os.environ.get("GARMIN_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(
            "streamable-http",
            host=os.environ.get("GARMIN_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("GARMIN_MCP_PORT", "8000")),
            streamable_http_path=os.environ.get("GARMIN_MCP_PATH", "/mcp"),
        )
    else:
        mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
