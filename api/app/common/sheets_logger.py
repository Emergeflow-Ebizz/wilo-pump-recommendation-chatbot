"""Buffered Google Sheets persistence for logs and LLM-call cost tracking.

Vercel's free tier only retains function logs for about an hour, so anything
not caught in that window is lost. This module buffers WARNING+ log records
(and per-LLM-call cost rows) in memory during a request, then flushes them to
a Google Sheet in a background task attached to the response - the client
never waits on the Sheets API.

Optional: stays fully inactive if GOOGLE_SERVICE_ACCOUNT_JSON /
GOOGLE_SHEET_LOG_SHEET_ID aren't set.
"""
import json
import logging
import os
from contextvars import ContextVar

_pending_rows: ContextVar[dict[str, list] | None] = ContextVar("_pending_rows", default=None)

_LOGS_TAB = "Logs"
_LLM_CALLS_TAB = "LLM_Calls"

_sheets_service = None
_spreadsheet_id: str | None = None


def _get_service():
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials = Credentials.from_service_account_info(
        creds_json, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    _sheets_service = build("sheets", "v4", credentials=credentials)
    return _sheets_service


def build_handler() -> logging.Handler | None:
    """Returns a WARNING+ handler that buffers rows for the current request's
    contextvar, or None if the two required env vars aren't set (feature off)."""
    global _spreadsheet_id
    sheet_id = os.environ.get("GOOGLE_SHEET_LOG_SHEET_ID")
    if not sheet_id or not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        return None
    _spreadsheet_id = sheet_id
    return GoogleSheetsLogHandler()


class GoogleSheetsLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        buffer = _pending_rows.get()
        if buffer is None:
            # No request in flight to flush this (e.g. cold-start startup
            # logging) - nothing to buffer into, so drop rather than leak
            # across unrelated future requests.
            return
        tab = _LLM_CALLS_TAB if record.name.endswith(".llm_cost") else _LOGS_TAB
        row = [
            self.formatTime(record),
            record.levelname,
            record.name,
            record.getMessage(),
        ]
        buffer.setdefault(tab, []).append(row)


def flush_buffered_rows(buffer: dict[str, list]) -> None:
    """Runs as a Starlette BackgroundTask after the response is already on
    its way to the client, so a slow or failing Sheets call never adds
    latency to a request."""
    if not buffer or _spreadsheet_id is None:
        return
    try:
        service = _get_service()
        for tab, rows in buffer.items():
            if not rows:
                continue
            service.spreadsheets().values().append(
                spreadsheetId=_spreadsheet_id,
                range=f"{tab}!A:A",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()
    except Exception as e:
        print(f"sheets_logger: failed to flush {sum(len(r) for r in buffer.values())} row(s): {e!r}")
