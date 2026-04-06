"""
Bug Router Orchestrator — FastAPI Backend  (v0.3 — HITL Gate)
==============================================================
Responsibilities:
  1. GET  /tools                  → Discover all tools from connected MCP servers
  2. POST /execute                → Accept a natural-language command, ask Gemini
                                    to build a JSON DAG, execute with HITL gate.
  3. GET  /hitl/pending           → List executions awaiting human approval
  4. POST /hitl/{exec_id}/approve → Approve a paused WRITE step
  5. POST /hitl/{exec_id}/reject  → Reject a paused WRITE step
  6. GET  /hitl/audit             → Full audit trail of every HITL decision
  7. GET  /health                 → Liveness probe

SSE Event schema (newline-delimited):
  data: {"type": "log",              "level": "INFO|SUCCESS|ERROR|DATA", "message": "..."}
  data: {"type": "dag",              "dag": { plan, steps[] }}
  data: {"type": "step_start",       "step_id": "step_1", "tool": "jira_get_ticket"}
  data: {"type": "step_complete",    "step_id": "step_1", "output_key": "...", "result": "..."}
  data: {"type": "pending_approval", "execution_id": "...", "step_id": "...",
                                     "tool": "...", "risk": "WRITE", "review_payload": {...}}
  data: {"type": "approved",         "execution_id": "...", "step_id": "...", "reason": "..."}
  data: {"type": "rejected",         "execution_id": "...", "step_id": "...", "reason": "..."}
  data: {"type": "error",            "message": "..."}
  data: {"type": "complete",         "outputs": {...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import aiosqlite
import google.generativeai as genai
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mcp import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orchestrator")

# ── Config ────────────────────────────────────────────────────────────────────
JIRA_MCP_URL   = os.getenv("JIRA_MCP_URL",   "http://jira-mock:8081/sse")
SLACK_MCP_URL  = os.getenv("SLACK_MCP_URL",  "http://slack-mock:8082/sse")
GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "http://github-mock:8083/sse")
SHEETS_MCP_URL = os.getenv("SHEETS_MCP_URL", "http://sheets-mock:8084/sse")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
HITL_DB_PATH   = os.getenv("HITL_DB_PATH",   "/data/hitl.db")
HITL_TIMEOUT_S = int(os.getenv("HITL_TIMEOUT_S", "300"))   # 5-minute default

# ── Risk Registry ─────────────────────────────────────────────────────────────
# WRITE tools pause and wait for human approval before executing.
# READ tools execute immediately without any gate.
RISK_REGISTRY: dict[str, str] = {
    # ── WRITE (mutating) ──────────────────────────────
    "slack_post_message":       "WRITE",
    "github_create_issue":      "WRITE",
    "sheets_append_row":        "WRITE",
    # ── READ (safe, auto-run) ─────────────────────────
    "jira_get_ticket":              "READ",
    "jira_list_open_tickets":       "READ",
    "github_list_pull_requests":    "READ",
    "github_get_pull_request":      "READ",
    "sheets_read_range":            "READ",
    "sheets_list_spreadsheets":     "READ",
}

# ── HITL State Machine ────────────────────────────────────────────────────────
# Keyed by execution_id.
# Each gate holds an asyncio.Event + the decision once set.
HITL_GATES: dict[str, dict] = {}
# {exec_id: {"event": asyncio.Event, "decision": "approved"|"rejected", "reason": str}}

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Bug Router Orchestrator", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SQLite DB bootstrap ───────────────────────────────────────────────────────
async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(HITL_DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


@app.on_event("startup")
async def init_db():
    os.makedirs(os.path.dirname(HITL_DB_PATH), exist_ok=True)
    async with aiosqlite.connect(HITL_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                exec_id       TEXT PRIMARY KEY,
                command       TEXT NOT NULL,
                dag_json      TEXT NOT NULL,
                outputs_json  TEXT NOT NULL,
                pending_step  INTEGER NOT NULL,
                created_at    TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                exec_id     TEXT NOT NULL,
                step_id     TEXT NOT NULL,
                tool        TEXT NOT NULL,
                decision    TEXT NOT NULL,
                reason      TEXT,
                actor       TEXT DEFAULT 'human',
                ts          TEXT NOT NULL
            )
        """)
        await db.commit()
    log.info("HITL SQLite DB initialised at %s", HITL_DB_PATH)


# ── Pydantic models ───────────────────────────────────────────────────────────
class ExecuteRequest(BaseModel):
    command: str

class DecisionRequest(BaseModel):
    reason: str = ""


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


# ── SQLite helpers ────────────────────────────────────────────────────────────
async def save_snapshot(
    exec_id: str,
    command: str,
    dag: dict,
    outputs: dict,
    pending_step: int,
):
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(HITL_DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO snapshots
               (exec_id, command, dag_json, outputs_json, pending_step, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (exec_id, command, json.dumps(dag), json.dumps(outputs), pending_step, ts),
        )
        await db.commit()


async def write_audit(
    exec_id: str,
    step_id: str,
    tool: str,
    decision: str,
    reason: str,
):
    ts = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(HITL_DB_PATH) as db:
        await db.execute(
            """INSERT INTO audit_log (exec_id, step_id, tool, decision, reason, ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (exec_id, step_id, tool, decision, reason, ts),
        )
        await db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "bug-router-backend", "version": "0.3.0"}


@app.get("/tools")
async def list_tools():
    """Discover and return all tools from all connected MCP servers."""
    result: dict[str, object] = {}
    for label, url in [
        ("jira",   JIRA_MCP_URL),
        ("slack",  SLACK_MCP_URL),
        ("github", GITHUB_MCP_URL),
        ("sheets", SHEETS_MCP_URL),
    ]:
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
      Phase 3 – Execute the DAG step-by-step, with HITL gate on WRITE tools
    """
    return StreamingResponse(
        _workflow(req.command),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── HITL approval endpoints ───────────────────────────────────────────────────
@app.get("/hitl/pending")
async def hitl_pending():
    """Return all execution IDs currently waiting for human approval."""
    pending = [
        {"execution_id": eid, "step_id": gate.get("step_id"), "tool": gate.get("tool")}
        for eid, gate in HITL_GATES.items()
        if not gate["event"].is_set()
    ]
    return {"pending": pending, "count": len(pending)}


@app.post("/hitl/{exec_id}/approve")
async def hitl_approve(exec_id: str, body: DecisionRequest = DecisionRequest()):
    """Approve a paused WRITE step — workflow will resume and execute the tool."""
    gate = HITL_GATES.get(exec_id)
    if gate is None or gate["event"].is_set():
        raise HTTPException(status_code=404, detail="No pending gate for that execution_id")
    gate["decision"] = "approved"
    gate["reason"]   = body.reason or "Approved by human operator"
    gate["event"].set()
    log.info("HITL APPROVED: exec=%s step=%s", exec_id, gate.get("step_id"))
    return {"ok": True, "execution_id": exec_id, "decision": "approved"}


@app.post("/hitl/{exec_id}/reject")
async def hitl_reject(exec_id: str, body: DecisionRequest = DecisionRequest()):
    """Reject a paused WRITE step — workflow will abort."""
    gate = HITL_GATES.get(exec_id)
    if gate is None or gate["event"].is_set():
        raise HTTPException(status_code=404, detail="No pending gate for that execution_id")
    gate["decision"] = "rejected"
    gate["reason"]   = body.reason or "Rejected by human operator"
    gate["event"].set()
    log.info("HITL REJECTED: exec=%s step=%s", exec_id, gate.get("step_id"))
    return {"ok": True, "execution_id": exec_id, "decision": "rejected"}


@app.get("/hitl/audit")
async def hitl_audit():
    """Return the full audit trail of every HITL decision."""
    async with aiosqlite.connect(HITL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM audit_log ORDER BY ts DESC LIMIT 200"
        ) as cur:
            rows = await cur.fetchall()
    return {"audit": [dict(r) for r in rows]}


# ── Workflow generator ────────────────────────────────────────────────────────
async def _workflow(command: str) -> AsyncGenerator[str, None]:  # type: ignore[override]
    """Core workflow — yields SSE frames, pauses at WRITE steps for human approval."""

    exec_id = uuid.uuid4().hex[:12]   # short unique ID for this run

    yield sse("log", level="INFO", message="━━━ BUG ROUTER INITIALISING ━━━")
    yield sse("log", level="INFO", message=f"Command: {command}")
    yield sse("log", level="INFO", message=f"Execution ID: {exec_id}")
    await asyncio.sleep(0.2)

    # ── Phase 1: Tool discovery ───────────────────────────────────────────────
    yield sse("log", level="INFO", message="Phase 1 › Discovering MCP tools…")

    all_tools: list[dict] = []
    tool_to_server: dict[str, str] = {}

    for label, url in [
        ("Jira",   JIRA_MCP_URL),
        ("Slack",  SLACK_MCP_URL),
        ("GitHub", GITHUB_MCP_URL),
        ("Sheets", SHEETS_MCP_URL),
    ]:
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
        "You are an orchestration engine that routes tasks across Jira, Slack, GitHub, and Google Sheets. "
        "Given a user command and a list of available MCP tools, produce a step-by-step execution plan "
        "as a JSON DAG. Steps execute in order; each step may depend on the output of a previous step. "
        "Output ONLY valid JSON — no markdown, no prose, no code fences."
    )

    user_prompt = f"""\
Available tools:
{tool_docs}

User command: "{command}"

Produce JSON with this exact shape (use as many steps as needed, up to 4):
{{
  "plan": "<one-sentence description of the full workflow>",
  "steps": [
    {{
      "id": "step_1",
      "tool": "<exact tool name from the list above>",
      "description": "<human-readable label for this step>",
      "params": {{ "<param_name>": "<param_value>" }},
      "depends_on": [],
      "output_key": "<snake_case variable name to store this step's result>"
    }},
    {{
      "id": "step_2",
      "tool": "<exact tool name from the list above>",
      "description": "<human-readable label for this step>",
      "params": {{
        "<param_name>": "{{<output_key_from_previous_step>}}"
      }},
      "depends_on": ["step_1"],
      "output_key": "<snake_case variable name>"
    }}
  ]
}}

Rules:
- Use EXACTLY the tool names listed above — do not invent new tool names.
- Steps execute sequentially in the order listed. Always number them step_1, step_2, step_3, step_4.
- To inject the result of a previous step into a param value, wrap its output_key in single curly braces: {{output_key}}.
- Only use {{output_key}} references for params — never use them as the tool name or step id.
- Keep steps to the minimum needed to fulfil the command (maximum 4 steps).
- For sheets_append_row, the 'values' param must be a JSON array of strings, e.g. ["BUG-12", "High", "Open"].
- For github_create_issue, set 'repo' to a valid owner/repo string (e.g. acme-corp/backend).
- For slack_post_message, the message should include all relevant details from prior steps.
- For sheets_read_range, always provide both 'spreadsheet_id' and 'sheet_name'.
- Do not add extra fields beyond: id, tool, description, params, depends_on, output_key.
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

    # Label each step with its risk level so the UI can preview
    write_steps = [s["tool"] for s in dag["steps"] if RISK_REGISTRY.get(s["tool"]) == "WRITE"]
    if write_steps:
        yield sse("log", level="INFO",
                  message=f"  ⚠ WRITE tools requiring approval: {write_steps}")
    await asyncio.sleep(0.3)

    # ── Phase 3: Execute DAG ──────────────────────────────────────────────────
    yield sse("log", level="INFO", message="Phase 3 › Executing DAG…")

    outputs: dict[str, str] = {}
    total = len(dag["steps"])

    for i, step in enumerate(dag["steps"], start=1):
        step_id    = step["id"]
        tool_name  = step["tool"]
        raw_params = step.get("params", {})
        out_key    = step.get("output_key", f"out_{i}")
        risk       = RISK_REGISTRY.get(tool_name, "UNKNOWN")

        yield sse("step_start", step_id=step_id, tool=tool_name, risk=risk)
        yield sse("log", level="INFO",
                  message=f"▶ [{i}/{total}] {step_id} — {step.get('description', tool_name)} [{risk}]")

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
            yield sse("log", level="ERROR", message=f"  ✗ Unknown tool: {tool_name}")
            yield sse("error", message=f"Unknown tool '{tool_name}'")
            return

        server_url = tool_to_server[tool_name]
        yield sse("log", level="INFO", message=f"  ↳ Routing to MCP: {server_url}")
        yield sse("log", level="INFO", message=f"  ↳ Params: {json.dumps(resolved)[:200]}")

        # ── HITL Gate (WRITE tools only) ──────────────────────────────────────
        if risk == "WRITE":
            yield sse("log", level="INFO",
                      message=f"  ⚠ HITL Gate activated for WRITE tool: {tool_name}")

            # Save execution snapshot so the run can be audited/resumed
            await save_snapshot(exec_id, command, dag, outputs, i)

            # Build a structured review payload for the human
            prior_context = {
                k: (v[:300] + "…" if len(v) > 300 else v)
                for k, v in outputs.items()
            }
            review_payload = {
                "what":  step.get("description", tool_name),
                "why":   f"This is step {i} of {total}: {dag['plan']}",
                "tool":  tool_name,
                "params": resolved,
                "context_from_prior_steps": prior_context,
            }

            # Register the gate
            gate: dict = {
                "event":    asyncio.Event(),
                "decision": None,
                "reason":   "",
                "step_id":  step_id,
                "tool":     tool_name,
            }
            HITL_GATES[exec_id] = gate

            # Emit pending_approval — UI will show the approval modal
            yield sse(
                "pending_approval",
                execution_id=exec_id,
                step_id=step_id,
                tool=tool_name,
                risk=risk,
                review_payload=review_payload,
            )
            yield sse("log", level="INFO",
                      message=f"  ↳ Waiting for human approval (timeout: {HITL_TIMEOUT_S}s)…")

            # Wait for approval (or timeout → auto-reject)
            try:
                await asyncio.wait_for(gate["event"].wait(), timeout=HITL_TIMEOUT_S)
                decision = gate["decision"]
                reason   = gate["reason"]
            except asyncio.TimeoutError:
                decision = "rejected"
                reason   = f"Auto-rejected: no human response within {HITL_TIMEOUT_S}s"
                gate["decision"] = decision
                gate["reason"]   = reason
                gate["event"].set()

            # Write to audit log
            await write_audit(exec_id, step_id, tool_name, decision, reason)

            # Clean up gate
            HITL_GATES.pop(exec_id, None)

            if decision == "approved":
                yield sse("approved",
                          execution_id=exec_id,
                          step_id=step_id,
                          reason=reason)
                yield sse("log", level="SUCCESS",
                          message=f"  ✓ APPROVED by human — proceeding with {tool_name}")
            else:
                yield sse("rejected",
                          execution_id=exec_id,
                          step_id=step_id,
                          reason=reason)
                yield sse("log", level="ERROR",
                          message=f"  ✗ REJECTED: {reason}")
                yield sse("error", message=f"Step {step_id} rejected: {reason}")
                return
        # ── End HITL Gate ─────────────────────────────────────────────────────

        try:
            result_text = await invoke_tool(server_url, tool_name, resolved)
            outputs[out_key] = result_text

            display = result_text[:300] + ("…" if len(result_text) > 300 else "")
            yield sse("log", level="DATA",    message=f"  ↳ Result: {display}")
            yield sse("step_complete",
                      step_id=step_id,
                      output_key=out_key,
                      result=result_text)
            yield sse("log", level="SUCCESS", message=f"  ✓ {step_id} complete")

        except Exception as exc:
            yield sse("log", level="ERROR", message=f"  ✗ {step_id} failed: {exc}")
            yield sse("error", message=str(exc))
            return

        await asyncio.sleep(0.25)

    yield sse("log", level="SUCCESS", message="━━━ WORKFLOW COMPLETE ━━━")
    yield sse("complete", outputs=outputs)


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
