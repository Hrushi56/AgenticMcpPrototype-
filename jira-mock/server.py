"""
Jira Mock MCP Server
====================
Uses mcp.server.Server + SseServerTransport (works with MCP SDK 1.x).

Endpoints:
  GET  /sse        – MCP SSE stream
  POST /messages/  – MCP message channel
  GET  /health     – Docker healthcheck
"""

import json
import logging

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("jira-mock")

# ── Fake ticket database ──────────────────────────────────────────────────────
TICKETS: dict[str, dict] = {
    "BUG-12": {
        "id": "BUG-12",
        "title": "Database timeout issue",
        "status": "Open",
        "priority": "High",
        "reporter": "alice@company.com",
        "assignee": "bob@company.com",
        "description": (
            "Production database connection pool is exhausted during peak hours, "
            "causing 30-second timeouts for ~12% of users. "
            "First observed 2024-01-15T09:00Z. "
            "Primarily affects the checkout and user-profile flows."
        ),
        "labels": ["database", "production", "p1"],
        "created": "2024-01-15T09:23:00Z",
        "updated": "2024-01-16T11:45:00Z",
    },
    "BUG-13": {
        "id": "BUG-13",
        "title": "Login redirect loop on mobile",
        "status": "In Progress",
        "priority": "Medium",
        "reporter": "charlie@company.com",
        "assignee": "diana@company.com",
        "description": (
            "Mobile users on iOS 17 experience an infinite redirect loop "
            "when authenticating via OAuth. Affects ~3% of mobile traffic."
        ),
        "labels": ["auth", "mobile", "ios"],
        "created": "2024-01-16T14:10:00Z",
        "updated": "2024-01-17T08:30:00Z",
    },
}

# ── MCP Server ────────────────────────────────────────────────────────────────
server = Server("jira-mock")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="jira_get_ticket",
            description=(
                "Retrieve a Jira ticket by its ID. "
                "Returns full ticket details including title, status, priority, "
                "assignee, and description."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The Jira ticket identifier (e.g. BUG-12)",
                    }
                },
                "required": ["ticket_id"],
            },
        ),
        Tool(
            name="jira_list_open_tickets",
            description=(
                "List all open Jira tickets in the project. "
                "Returns a JSON array of ticket summaries."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "jira_get_ticket":
        key = arguments.get("ticket_id", "").upper().strip()
        log.info(f"[jira_get_ticket] Fetching: {key}")
        if key not in TICKETS:
            result = json.dumps({
                "error": f"Ticket '{key}' not found.",
                "available_tickets": list(TICKETS.keys()),
            })
        else:
            result = json.dumps(TICKETS[key], indent=2)
        return [TextContent(type="text", text=result)]

    if name == "jira_list_open_tickets":
        log.info("[jira_list_open_tickets] Listing open tickets")
        open_tickets = [
            {"id": t["id"], "title": t["title"], "priority": t["priority"]}
            for t in TICKETS.values()
            if t["status"] == "Open"
        ]
        return [TextContent(type="text", text=json.dumps(open_tickets, indent=2))]

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
        "service": "jira-mock",
        "tickets": list(TICKETS.keys()),
    })


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    log.info("Starting Jira Mock MCP server on port 8081")
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info")
