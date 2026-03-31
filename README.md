# 🐛 Automated Bug Router — Agentic MCP Gateway PoC

> **"Stop talking about Agentic MCP Gateways. Show them a button."**
>
> This prototype proves that an LLM can dynamically plan and execute a
> cross-platform workflow — without a single hardcoded script.

---

## What it does

You type a plain-English command like:

```
Read ticket BUG-12 and post it to the dev channel
```

Behind the scenes:

1. **FastAPI** discovers available tools from two live MCP servers
2. **Claude** builds a 2-step JSON execution DAG — dynamically, at runtime
3. FastAPI executes the DAG: calls Jira MCP → injects result → calls Slack MCP
4. Every step streams to a live terminal in the browser via SSE

No hardcoded `if ticket → slack` logic. The LLM writes the script on the fly.

---

## Architecture

```
Browser (Next.js :3000)
  │
  │  POST /execute  (natural-language command)
  │  ◀─── SSE stream (log lines, DAG JSON, step events)
  ▼
FastAPI Orchestrator (:8000)
  │
  ├── MCP SSE client ──▶  Jira Mock MCP  (:8081)
  │                         tool: jira_get_ticket
  │                         tool: jira_list_open_tickets
  │
  └── MCP SSE client ──▶  Slack Mock MCP (:8082)
                            tool: slack_post_message
```

### SSE event types

| `type`          | Payload fields                              | UI effect                     |
|-----------------|---------------------------------------------|-------------------------------|
| `log`           | `level`, `message`                          | Appends line to terminal      |
| `dag`           | `dag` (full JSON plan)                      | Renders flowchart             |
| `step_start`    | `step_id`, `tool`                           | Highlights card amber         |
| `step_complete` | `step_id`, `output_key`, `result`           | Turns card green              |
| `error`         | `message`                                   | Turns running cards red       |
| `complete`      | `outputs`                                   | Banner in terminal            |

---

## Quick start

### Prerequisites

- Docker + Docker Compose
- An Anthropic API key

### 1. Clone & configure

```bash
git clone <this-repo>
cd bug-router
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Launch all four services

```bash
docker compose up --build
```

Services start in dependency order (mocks → backend → frontend).
First build takes ~2 min (npm install + pip install).

### 3. Open the control room

```
http://localhost:3000
```

Type a command, hit **EXECUTE →**, and watch the DAG appear.

---

## Running without Docker (dev mode)

### Mock MCP servers

```bash
# Terminal 1
cd jira-mock
pip install -r requirements.txt
python server.py

# Terminal 2
cd slack-mock
pip install -r requirements.txt
python server.py
```

### Backend

```bash
cd backend
pip install -r requirements.txt
JIRA_MCP_URL=http://localhost:8081/sse \
SLACK_MCP_URL=http://localhost:8082/sse \
ANTHROPIC_API_KEY=sk-ant-... \
python main.py
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

---

## Preloaded demo data

The Jira mock ships with two tickets:

| ID     | Title                         | Status      | Priority |
|--------|-------------------------------|-------------|----------|
| BUG-12 | Database timeout issue        | Open        | High     |
| BUG-13 | Login redirect loop on mobile | In Progress | Medium   |

Try both:

```
Read ticket BUG-12 and post it to the dev channel
Get the details of BUG-13 and notify #alerts on Slack
List all open Jira tickets and post a summary to #standup
```

---

## Debugging endpoints

| URL                             | What you'll see                          |
|---------------------------------|------------------------------------------|
| `http://localhost:8081/health`  | Jira mock status + loaded ticket IDs     |
| `http://localhost:8082/health`  | Slack mock status + message count        |
| `http://localhost:8082/inbox`   | All Slack messages "delivered" so far    |
| `http://localhost:8000/tools`   | Full tool registry from both MCP servers |
| `http://localhost:8000/health`  | Backend liveness                         |

---

## File structure

```
bug-router/
├── docker-compose.yml
├── .env.example
│
├── jira-mock/          # MCP SSE server · port 8081
│   ├── server.py       # FastMCP with jira_get_ticket tool
│   ├── requirements.txt
│   └── Dockerfile
│
├── slack-mock/         # MCP SSE server · port 8082
│   ├── server.py       # FastMCP with slack_post_message tool
│   ├── requirements.txt
│   └── Dockerfile
│
├── backend/            # Orchestrator · port 8000
│   ├── main.py         # FastAPI: /tools, /execute (SSE stream)
│   ├── requirements.txt
│   └── Dockerfile
│
└── frontend/           # Control Room · port 3000
    ├── app/
    │   ├── layout.tsx
    │   ├── globals.css  # Space Mono font, mission-control theme
    │   └── page.tsx     # Command input + DAG viewer + terminal
    ├── next.config.js
    ├── tsconfig.json
    ├── package.json
    └── Dockerfile
```

---

## Extending the demo

### Add a third tool (e.g. PagerDuty)

1. Create `pagerduty-mock/server.py` with a `FastMCP` and a `pagerduty_create_incident` tool
2. Add the service to `docker-compose.yml`
3. Add `PAGERDUTY_MCP_URL` to the backend env + the `fetch_tools` loop in `main.py`

That's it. The LLM will discover the new tool automatically via `/tools` and
will start routing to it when the command calls for it.

### Swap mock servers for real ones

Replace each `server.py` with a real MCP server that calls the Jira / Slack
APIs. The orchestrator code is unchanged — it only speaks MCP.

---

## Key talking point for the demo

> "Notice we never wrote `if 'BUG' in command: call_jira()`.
> The LLM read the tool list and wrote that logic itself, live, as JSON.
> Change the command → the plan changes. Add a tool → it gets used.
> That's what an Agentic MCP Gateway buys you."
