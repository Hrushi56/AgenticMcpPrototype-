"""
Slack Mock MCP Server
=====================
Uses mcp.server.Server + SseServerTransport (works with MCP SDK 1.x).

Endpoints:
  GET  /sse        – MCP SSE stream
  POST /messages/  – MCP message channel
  GET  /health     – Docker healthcheck
  GET  /inbox      – View all delivered messages (debug)
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
log = logging.getLogger("slack-mock")

# ── In-memory message store ───────────────────────────────────────────────────
_inbox: list[dict] = []

# ── MCP Server ────────────────────────────────────────────────────────────────
server = Server("slack-mock")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="slack_post_message",
            description=(
                "Post a message to a Slack channel. "
                "Returns a delivery receipt with timestamp and message ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Slack channel name without # (e.g. dev, general, alerts)",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text to post",
                    },
                },
                "required": ["channel", "message"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "slack_post_message":
        channel = arguments.get("channel", "general")
        message = arguments.get("message", "")
        ts = datetime.now(timezone.utc).isoformat()
        msg_id = f"msg_{len(_inbox) + 1:04d}"

        entry = {
            "message_id": msg_id,
            "channel": f"#{channel}",
            "message": message,
            "timestamp": ts,
            "status": "delivered",
            "author": "bug-router-bot",
        }
        _inbox.append(entry)
        log.info(f"[slack_post_message] Posted to #{channel}: {message[:80]}")

        receipt = {
            "ok": True,
            "message_id": msg_id,
            "channel": f"#{channel}",
            "timestamp": ts,
            "preview": message[:120] + ("…" if len(message) > 120 else ""),
        }
        return [TextContent(type="text", text=json.dumps(receipt, indent=2))]

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
        "service": "slack-mock",
        "messages_delivered": len(_inbox),
    })


async def inbox(request: Request) -> JSONResponse:
    return JSONResponse(_inbox)


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Route("/inbox", endpoint=inbox),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    log.info("Starting Slack Mock MCP server on port 8082")
    uvicorn.run(app, host="0.0.0.0", port=8082, log_level="info")
