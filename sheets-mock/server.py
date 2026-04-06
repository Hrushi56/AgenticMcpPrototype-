"""
Google Sheets Mock MCP Server
==============================
Uses mcp.server.Server + SseServerTransport (works with MCP SDK 1.x).

Endpoints:
  GET  /sse        – MCP SSE stream
  POST /messages/  – MCP message channel
  GET  /health     – Docker healthcheck
  GET  /sheets     – View all in-memory sheet data (debug)
"""

import json
import logging
from datetime import datetime, timezone

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sheets-mock")

# ── Fake spreadsheet store ────────────────────────────────────────────────────
# Each sheet is keyed by spreadsheet_id.  Rows are lists of cell values.
SPREADSHEETS: dict[str, dict] = {
    "sheet_bug_tracker": {
        "id": "sheet_bug_tracker",
        "title": "Bug Tracker 2024",
        "sheets": {
            "Incidents": {
                "headers": ["ID", "Title", "Priority", "Status", "Assignee", "Reported"],
                "rows": [
                    ["BUG-12", "Database timeout issue", "High", "Open", "bob@company.com", "2024-01-15"],
                    ["BUG-13", "Login redirect loop on mobile", "Medium", "In Progress", "diana@company.com", "2024-01-16"],
                ],
            },
            "Summary": {
                "headers": ["Metric", "Value"],
                "rows": [
                    ["Total Open", "1"],
                    ["Total In Progress", "1"],
                    ["Avg Resolution Time (days)", "3.5"],
                ],
            },
        },
    },
    "sheet_oncall_log": {
        "id": "sheet_oncall_log",
        "title": "On-Call Incident Log",
        "sheets": {
            "Log": {
                "headers": ["Date", "Incident", "Engineer", "Resolution"],
                "rows": [
                    ["2024-01-15", "DB pool exhaustion", "bob", "Increased pool size"],
                    ["2024-01-16", "Mobile OAuth loop", "diana", "In progress"],
                ],
            }
        },
    },
}


# ── MCP Server ────────────────────────────────────────────────────────────────
server = Server("sheets-mock")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sheets_read_range",
            description=(
                "Read a range of cells from a Google Sheets spreadsheet. "
                "Returns the headers and rows for the specified sheet tab."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "The spreadsheet ID (e.g. sheet_bug_tracker)",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "The name of the tab/sheet within the spreadsheet (e.g. Incidents)",
                    },
                },
                "required": ["spreadsheet_id", "sheet_name"],
            },
        ),
        Tool(
            name="sheets_append_row",
            description=(
                "Append a new row of data to a Google Sheets spreadsheet tab. "
                "Returns a write receipt confirming the appended range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "The spreadsheet ID (e.g. sheet_bug_tracker)",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "The name of the tab/sheet to append to",
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of cell values for the new row",
                    },
                },
                "required": ["spreadsheet_id", "sheet_name", "values"],
            },
        ),
        Tool(
            name="sheets_list_spreadsheets",
            description=(
                "List all available spreadsheets in the mock store. "
                "Returns spreadsheet IDs, titles, and their tab names."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "sheets_read_range":
        spreadsheet_id = arguments.get("spreadsheet_id", "").strip()
        sheet_name = arguments.get("sheet_name", "").strip()
        log.info(f"[sheets_read_range] Reading {spreadsheet_id} / {sheet_name}")

        spreadsheet = SPREADSHEETS.get(spreadsheet_id)
        if spreadsheet is None:
            result = json.dumps({
                "error": f"Spreadsheet '{spreadsheet_id}' not found.",
                "available_spreadsheets": list(SPREADSHEETS.keys()),
            })
            return [TextContent(type="text", text=result)]

        sheet = spreadsheet["sheets"].get(sheet_name)
        if sheet is None:
            result = json.dumps({
                "error": f"Sheet tab '{sheet_name}' not found in '{spreadsheet_id}'.",
                "available_tabs": list(spreadsheet["sheets"].keys()),
            })
            return [TextContent(type="text", text=result)]

        result = json.dumps({
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_title": spreadsheet["title"],
            "sheet_name": sheet_name,
            "headers": sheet["headers"],
            "rows": sheet["rows"],
            "row_count": len(sheet["rows"]),
        }, indent=2)
        return [TextContent(type="text", text=result)]

    if name == "sheets_append_row":
        spreadsheet_id = arguments.get("spreadsheet_id", "").strip()
        sheet_name = arguments.get("sheet_name", "").strip()
        values = arguments.get("values", [])
        ts = datetime.now(timezone.utc).isoformat()
        log.info(f"[sheets_append_row] Appending to {spreadsheet_id} / {sheet_name}: {values}")

        spreadsheet = SPREADSHEETS.get(spreadsheet_id)
        if spreadsheet is None:
            result = json.dumps({
                "error": f"Spreadsheet '{spreadsheet_id}' not found.",
                "available_spreadsheets": list(SPREADSHEETS.keys()),
            })
            return [TextContent(type="text", text=result)]

        # Auto-create sheet tab if it doesn't exist
        if sheet_name not in spreadsheet["sheets"]:
            spreadsheet["sheets"][sheet_name] = {"headers": [], "rows": []}

        sheet = spreadsheet["sheets"][sheet_name]
        sheet["rows"].append(values)
        row_index = len(sheet["rows"])

        result = json.dumps({
            "ok": True,
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "appended_range": f"{sheet_name}!A{row_index}",
            "row_index": row_index,
            "values": values,
            "timestamp": ts,
        }, indent=2)
        return [TextContent(type="text", text=result)]

    if name == "sheets_list_spreadsheets":
        log.info("[sheets_list_spreadsheets] Listing all spreadsheets")
        summary = [
            {
                "id": sid,
                "title": s["title"],
                "tabs": list(s["sheets"].keys()),
            }
            for sid, s in SPREADSHEETS.items()
        ]
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ── SSE transport + Starlette app ─────────────────────────────────────────────
sse_transport = SseServerTransport("/messages/")


async def handle_sse(request: Request):
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "sheets-mock",
        "spreadsheets": list(SPREADSHEETS.keys()),
    })


async def sheets_debug(request: Request) -> JSONResponse:
    return JSONResponse(SPREADSHEETS)


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Route("/sheets", endpoint=sheets_debug),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    log.info("Starting Google Sheets Mock MCP server on port 8084")
    uvicorn.run(app, host="0.0.0.0", port=8084, log_level="info")
