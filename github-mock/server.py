"""
GitHub Mock MCP Server
======================
Uses mcp.server.Server + SseServerTransport (works with MCP SDK 1.x).

Endpoints:
  GET  /sse        – MCP SSE stream
  POST /messages/  – MCP message channel
  GET  /health     – Docker healthcheck
  GET  /issues     – View all created issues (debug)
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
log = logging.getLogger("github-mock")

# ── Fake repository / PR database ────────────────────────────────────────────
REPOS: dict[str, dict] = {
    "acme-corp/backend": {
        "name": "backend",
        "full_name": "acme-corp/backend",
        "description": "Core backend service for Acme Corp platform",
        "language": "Python",
        "stars": 42,
        "open_issues": 3,
        "default_branch": "main",
        "visibility": "private",
    },
    "acme-corp/frontend": {
        "name": "frontend",
        "full_name": "acme-corp/frontend",
        "description": "Next.js frontend for Acme Corp",
        "language": "TypeScript",
        "stars": 18,
        "open_issues": 1,
        "default_branch": "main",
        "visibility": "private",
    },
}

PULL_REQUESTS: list[dict] = [
    {
        "number": 47,
        "title": "Fix database connection pool exhaustion",
        "state": "open",
        "author": "bob",
        "repo": "acme-corp/backend",
        "branch": "fix/db-pool-timeout",
        "base": "main",
        "description": "Increases max_overflow to 20 and adds connection recycling every 5 min.",
        "reviews": ["approved"],
        "created": "2024-01-16T10:00:00Z",
        "updated": "2024-01-17T09:30:00Z",
    },
    {
        "number": 48,
        "title": "Add retry logic for OAuth redirect on mobile",
        "state": "open",
        "author": "diana",
        "repo": "acme-corp/frontend",
        "branch": "fix/mobile-oauth-redirect",
        "base": "main",
        "description": "Detects iOS 17 user-agent and uses PKCE flow instead of implicit.",
        "reviews": [],
        "created": "2024-01-17T08:00:00Z",
        "updated": "2024-01-17T11:00:00Z",
    },
]

# In-memory store for created issues
_created_issues: list[dict] = []
_issue_counter = 100


# ── MCP Server ────────────────────────────────────────────────────────────────
server = Server("github-mock")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="github_list_pull_requests",
            description=(
                "List open pull requests for a GitHub repository. "
                "Returns PR number, title, author, branch, and review status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in owner/repo format (e.g. acme-corp/backend)",
                    }
                },
                "required": ["repo"],
            },
        ),
        Tool(
            name="github_get_pull_request",
            description=(
                "Get details of a specific pull request by its number. "
                "Returns full PR metadata including description and review state."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in owner/repo format (e.g. acme-corp/backend)",
                    },
                    "pr_number": {
                        "type": "integer",
                        "description": "The pull request number",
                    },
                },
                "required": ["repo", "pr_number"],
            },
        ),
        Tool(
            name="github_create_issue",
            description=(
                "Create a new GitHub issue in a repository. "
                "Returns the created issue number and URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in owner/repo format (e.g. acme-corp/backend)",
                    },
                    "title": {
                        "type": "string",
                        "description": "The issue title",
                    },
                    "body": {
                        "type": "string",
                        "description": "The issue body / description",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of label names to apply",
                    },
                },
                "required": ["repo", "title", "body"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _issue_counter

    if name == "github_list_pull_requests":
        repo = arguments.get("repo", "").strip()
        log.info(f"[github_list_pull_requests] Listing PRs for: {repo}")
        prs = [pr for pr in PULL_REQUESTS if pr["repo"] == repo and pr["state"] == "open"]
        if not prs:
            result = json.dumps({
                "repo": repo,
                "open_prs": [],
                "message": f"No open PRs found for '{repo}'. Available repos: {list(REPOS.keys())}",
            })
        else:
            summary = [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "author": pr["author"],
                    "branch": pr["branch"],
                    "reviews": pr["reviews"],
                }
                for pr in prs
            ]
            result = json.dumps({"repo": repo, "open_prs": summary}, indent=2)
        return [TextContent(type="text", text=result)]

    if name == "github_get_pull_request":
        repo = arguments.get("repo", "").strip()
        pr_number = int(arguments.get("pr_number", 0))
        log.info(f"[github_get_pull_request] Fetching PR #{pr_number} from {repo}")
        match = next(
            (pr for pr in PULL_REQUESTS if pr["repo"] == repo and pr["number"] == pr_number),
            None,
        )
        if match is None:
            result = json.dumps({
                "error": f"PR #{pr_number} not found in '{repo}'.",
                "available_prs": [pr["number"] for pr in PULL_REQUESTS if pr["repo"] == repo],
            })
        else:
            result = json.dumps(match, indent=2)
        return [TextContent(type="text", text=result)]

    if name == "github_create_issue":
        repo = arguments.get("repo", "").strip()
        title = arguments.get("title", "").strip()
        body = arguments.get("body", "").strip()
        labels = arguments.get("labels", [])
        ts = datetime.now(timezone.utc).isoformat()
        _issue_counter += 1
        issue_number = _issue_counter

        issue = {
            "number": issue_number,
            "title": title,
            "body": body,
            "labels": labels,
            "repo": repo,
            "state": "open",
            "created_at": ts,
            "url": f"https://github.com/{repo}/issues/{issue_number}",
            "author": "bug-router-bot",
        }
        _created_issues.append(issue)
        log.info(f"[github_create_issue] Created issue #{issue_number} in {repo}: {title}")
        result = json.dumps({
            "ok": True,
            "issue_number": issue_number,
            "url": issue["url"],
            "title": title,
            "repo": repo,
        }, indent=2)
        return [TextContent(type="text", text=result)]

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
        "service": "github-mock",
        "repos": list(REPOS.keys()),
        "open_prs": len([pr for pr in PULL_REQUESTS if pr["state"] == "open"]),
        "issues_created": len(_created_issues),
    })


async def issues(request: Request) -> JSONResponse:
    return JSONResponse(_created_issues)


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Route("/issues", endpoint=issues),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    log.info("Starting GitHub Mock MCP server on port 8083")
    uvicorn.run(app, host="0.0.0.0", port=8083, log_level="info")
