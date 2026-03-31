"""
Bug Router Orchestrator — FastAPI Backend
==========================================
Responsibilities:
  1. GET /tools   → Discover all tools from connected MCP servers
  2. POST /execute → Accept a natural-language command, ask Gemini to build a
                     2-step JSON DAG, execute that DAG against the real MCP
                     servers, and stream structured SSE events back to the UI.
  3. GET /health  → Liveness probe

SSE Event schema (newline-delimited):
  data: {"type": "log",          "level": "INFO|SUCCESS|ERROR|DATA", "message": "..."}
  data: {"type": "dag",          "dag": { plan, steps[] }}
  data: {"type": "step_start",   "step_id": "step_1", "tool": "jira_get_ticket"}
  data: {"type": "step_complete","step_id": "step_1", "output_key": "...", "result": "..."}
  data: {"type": "error",        "message": "..."}
  data: {"type": "complete",     "outputs": {...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncGenerator

import google.generativeai as genai
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mcp import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orchestrator")

# ── Config ────────────────────────────────────────────────────────────────────
JIRA_MCP_URL  = os.getenv("JIRA_MCP_URL",  "http://jira-mock:8081/sse")
SLACK_MCP_URL = os.getenv("SLACK_MCP_URL", "http://slack-mock:8082/sse")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Map tool name → MCP server URL (populated lazily)
TOOL_REGISTRY: dict[str, str] = {}

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Bug Router Orchestrator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    command: str


# ── MCP helpers ───────────────────────────────────────────────────────────────
async def fetch_tools(server_url: str) -> list[dict]:
    """Open an MCP SSE connection, list tools, then close."""
    async with sse_client(server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema,
                }
                for t in result.tools
            ]


async def invoke_tool(server_url: str, tool_name: str, params: dict) -> str:
    """Open an MCP SSE connection, call one tool, return text output."""
    async with sse_client(server_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, params)
            return "\n".join(
                block.text for block in result.content if hasattr(block, "text")
            )


# ── SSE helper ────────────────────────────────────────────────────────────────
def sse(event_type: str, **payload) -> str:
    """Format one SSE frame."""
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "bug-router-backend"}


@app.get("/tools")
async def list_tools():
    """
    Discover and return all tools from both MCP servers.
    Useful for the UI to show what the gateway knows about.
    """
    result: dict[str, object] = {}

    for label, url in [("jira", JIRA_MCP_URL), ("slack", SLACK_MCP_URL)]:
        try:
            tools = await fetch_tools(url)
            result[label] = tools
        except Exception as exc:
            result[label] = {"error": str(exc)}

    return result


@app.post("/execute")
async def execute(req: ExecuteRequest):
    """
    Accept a natural-language command, stream SSE events:
      Phase 1 – Discover MCP tools
      Phase 2 – LLM generates a JSON DAG
      Phase 3 – Execute the DAG step-by-step
    """
    return StreamingResponse(
        _workflow(req.command),
        media_type="text/event-stream",
        headers={
            "Cache-Control":   "no-cache",
            "Connection":      "keep-alive",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


# ── Workflow generator ────────────────────────────────────────────────────────
async def _workflow(command: str) -> AsyncGenerator[str, None]:  # type: ignore[override]
    """Core workflow — yields SSE frames."""

    yield sse("log", level="INFO",    message="━━━ BUG ROUTER INITIALISING ━━━")
    yield sse("log", level="INFO",    message=f"Command: {command}")
    await asyncio.sleep(0.2)

    # ── Phase 1: Tool discovery ───────────────────────────────────────────────
    yield sse("log", level="INFO", message="Phase 1 › Discovering MCP tools…")

    all_tools: list[dict] = []
    tool_to_server: dict[str, str] = {}

    for label, url in [("Jira", JIRA_MCP_URL), ("Slack", SLACK_MCP_URL)]:
        yield sse("log", level="INFO", message=f"  Connecting to {label} MCP @ {url} …")
        try:
            tools = await fetch_tools(url)
            for t in tools:
                all_tools.append(t)
                tool_to_server[t["name"]] = url
            names = [t["name"] for t in tools]
            yield sse("log", level="SUCCESS", message=f"  ✓ {label} MCP ready — tools: {names}")
        except Exception as exc:
            yield sse("log", level="ERROR", message=f"  ✗ {label} MCP unreachable: {exc}")
            yield sse("error", message=f"{label} MCP unreachable: {exc}")
            return

        await asyncio.sleep(0.15)

    yield sse("log", level="INFO",
              message=f"Tool registry: {list(tool_to_server.keys())}")
    await asyncio.sleep(0.2)

    # ── Phase 2: LLM generates DAG ────────────────────────────────────────────
    yield sse("log", level="INFO", message="Phase 2 › Invoking Gemini for execution plan…")

    tool_docs = "\n".join(
        f"  • {t['name']}: {t['description']}"
        for t in all_tools
    )

    system_prompt = (
        "You are an orchestration engine. "
        "Given a user command and a list of available tools, produce an execution plan "
        "as a JSON DAG. Output ONLY valid JSON — no markdown, no prose, no code fences."
    )

    user_prompt = f"""\
Available tools:
{tool_docs}

User command: "{command}"

Produce JSON with this exact shape:
{{
  "plan": "<one-sentence description of what you will do>",
  "steps": [
    {{
      "id": "step_1",
      "tool": "<exact tool name>",
      "description": "<human-readable label>",
      "params": {{ "<param>": "<value>" }},
      "depends_on": [],
      "output_key": "<variable name for the result>"
    }},
    {{
      "id": "step_2",
      "tool": "<exact tool name>",
      "description": "<human-readable label>",
      "params": {{
        "<param>": "<value or {{output_key_from_step_1}} to inject previous output>"
      }},
      "depends_on": ["step_1"],
      "output_key": "final_result"
    }}
  ]
}}

Rules:
- Use EXACTLY the tool names listed above — no inventing new ones.
- To pass the result of step N into step N+1, reference it as {{output_key_value}}.
- Keep it to 2 steps for this workflow.
- For the Slack message, include the full Jira ticket content.
"""

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_prompt,
        )
        response = model.generate_content(user_prompt)
        raw = response.text.strip()

        # Defensively strip any accidental markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

        dag = json.loads(raw)

    except json.JSONDecodeError as exc:
        yield sse("log", level="ERROR", message=f"LLM returned malformed JSON: {exc}")
        yield sse("log", level="DATA",  message=f"Raw LLM output: {raw[:400]}")
        yield sse("error", message="LLM DAG parse failure")
        return
    except Exception as exc:
        yield sse("log", level="ERROR", message=f"LLM call failed: {exc}")
        yield sse("error", message=str(exc))
        return

    yield sse("dag", dag=dag)
    yield sse("log", level="SUCCESS", message=f"  ✓ DAG generated: {len(dag['steps'])} step(s)")
    yield sse("log", level="INFO",    message=f"  Plan: {dag['plan']}")
    await asyncio.sleep(0.3)

    # ── Phase 3: Execute DAG ──────────────────────────────────────────────────
    yield sse("log", level="INFO", message="Phase 3 › Executing DAG…")

    outputs: dict[str, str] = {}
    total = len(dag["steps"])

    for i, step in enumerate(dag["steps"], start=1):
        step_id   = step["id"]
        tool_name = step["tool"]
        raw_params = step.get("params", {})
        out_key   = step.get("output_key", f"out_{i}")

        yield sse("step_start", step_id=step_id, tool=tool_name)
        yield sse("log", level="INFO",
                  message=f"▶ [{i}/{total}] {step_id} — {step.get('description', tool_name)}")

        # Resolve template references like {ticket_data}
        resolved: dict = {}
        for k, v in raw_params.items():
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                ref = v[1:-1]
                if ref in outputs:
                    resolved[k] = outputs[ref]
                    yield sse("log", level="INFO",
                              message=f"  ↳ Injected {ref!r} → param {k!r}")
                else:
                    yield sse("log", level="INFO",
                              message=f"  ↳ Ref {ref!r} not found; using literal")
                    resolved[k] = v
            else:
                resolved[k] = v

        if tool_name not in tool_to_server:
            yield sse("log", level="ERROR",
                      message=f"  ✗ Unknown tool: {tool_name}")
            yield sse("error", message=f"Unknown tool '{tool_name}'")
            return

        server_url = tool_to_server[tool_name]
        yield sse("log", level="INFO",
                  message=f"  ↳ Routing to MCP: {server_url}")
        yield sse("log", level="INFO",
                  message=f"  ↳ Params: {json.dumps(resolved)[:200]}")

        try:
            result_text = await invoke_tool(server_url, tool_name, resolved)
            outputs[out_key] = result_text

            display = result_text[:300] + ("…" if len(result_text) > 300 else "")
            yield sse("log", level="DATA",
                      message=f"  ↳ Result: {display}")
            yield sse("step_complete",
                      step_id=step_id,
                      output_key=out_key,
                      result=result_text)
            yield sse("log", level="SUCCESS",
                      message=f"  ✓ {step_id} complete")

        except Exception as exc:
            yield sse("log", level="ERROR",
                      message=f"  ✗ {step_id} failed: {exc}")
            yield sse("error", message=str(exc))
            return

        await asyncio.sleep(0.25)

    yield sse("log", level="SUCCESS", message="━━━ WORKFLOW COMPLETE ━━━")
    yield sse("complete", outputs=outputs)


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
