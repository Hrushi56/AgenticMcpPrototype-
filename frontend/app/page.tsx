"use client";

import { useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────
type LogLevel = "INFO" | "SUCCESS" | "ERROR" | "DATA";

interface LogEntry {
  id: string;
  level: LogLevel;
  message: string;
  ts: string;
}

interface DagStep {
  id: string;
  tool: string;
  description: string;
  params: Record<string, unknown>;
  depends_on: string[];
  output_key: string;
}

interface Dag {
  plan: string;
  steps: DagStep[];
}

type StepStatus = "idle" | "running" | "done" | "error";

// ── Colour helpers ────────────────────────────────────────────────────────────
const LEVEL_COLOR: Record<LogLevel, string> = {
  INFO: "var(--text-dim)",
  SUCCESS: "var(--green)",
  ERROR: "var(--red)",
  DATA: "var(--blue)",
};

const LEVEL_PREFIX: Record<LogLevel, string> = {
  INFO: "[INFO]   ",
  SUCCESS: "[OK]     ",
  ERROR: "[ERROR]  ",
  DATA: "[DATA]   ",
};

// ── DAG Flowchart ─────────────────────────────────────────────────────────────
function DagFlowchart({
  dag,
  statuses,
}: {
  dag: Dag | null;
  statuses: Record<string, StepStatus>;
}) {
  if (!dag) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          color: "var(--text-dim)",
          fontSize: 12,
          padding: 24,
        }}
      >
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect x="4" y="6" width="18" height="12" rx="2" stroke="var(--border-lit)" strokeWidth="1.5" fill="var(--bg-elevated)" />
          <rect x="26" y="6" width="18" height="12" rx="2" stroke="var(--border-lit)" strokeWidth="1.5" fill="var(--bg-elevated)" />
          <rect x="14" y="30" width="20" height="12" rx="2" stroke="var(--border-lit)" strokeWidth="1.5" fill="var(--bg-elevated)" />
          <line x1="13" y1="18" x2="20" y2="30" stroke="var(--border-lit)" strokeWidth="1.5" strokeDasharray="3 2" />
          <line x1="35" y1="18" x2="28" y2="30" stroke="var(--border-lit)" strokeWidth="1.5" strokeDasharray="3 2" />
        </svg>
        <span>Awaiting command…</span>
        <span style={{ fontSize: 10, opacity: 0.5 }}>
          The LLM-generated DAG will appear here
        </span>
      </div>
    );
  }

  const CARD_W = 260;
  const CARD_H = 80;
  const GAP = 56;
  const PAD = 20;
  const totalH = dag.steps.length * CARD_H + (dag.steps.length - 1) * GAP + PAD * 2;
  const SVG_W = CARD_W + PAD * 2;

  function statusColor(s: StepStatus) {
    if (s === "done") return "var(--green)";
    if (s === "running") return "var(--amber)";
    if (s === "error") return "var(--red)";
    return "var(--border-lit)";
  }

  function statusFill(s: StepStatus) {
    if (s === "done") return "rgba(0,255,163,0.07)";
    if (s === "running") return "rgba(255,163,64,0.07)";
    if (s === "error") return "rgba(255,69,88,0.07)";
    return "var(--bg-elevated)";
  }

  function StatusBadge({ s }: { s: StepStatus }) {
    if (s === "idle") return <span style={{ color: "var(--text-dim)", fontSize: 10 }}>PENDING</span>;
    if (s === "running") return <span style={{ color: "var(--amber)", fontSize: 10, animation: "blink 0.8s step-end infinite" }}>● RUNNING</span>;
    if (s === "done") return <span style={{ color: "var(--green)", fontSize: 10 }}>✓ DONE</span>;
    return <span style={{ color: "var(--red)", fontSize: 10 }}>✗ ERROR</span>;
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: PAD }}>
      {/* Plan description */}
      <div
        style={{
          fontSize: 11,
          color: "var(--text-dim)",
          borderLeft: "2px solid var(--green)",
          paddingLeft: 10,
          marginBottom: 20,
          lineHeight: 1.5,
        }}
      >
        <span style={{ color: "var(--green)", letterSpacing: "0.1em" }}>PLAN</span>
        <br />
        {dag.plan}
      </div>

      {/* Steps */}
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {dag.steps.map((step, idx) => {
          const s = statuses[step.id] ?? "idle";
          const isLast = idx === dag.steps.length - 1;

          return (
            <div key={step.id}>
              {/* Card */}
              <div
                style={{
                  border: `1px solid ${statusColor(s)}`,
                  borderRadius: 3,
                  background: statusFill(s),
                  padding: "12px 16px",
                  transition: "all 0.3s ease",
                  animation: s === "running" ? "pulse-amber 1.4s ease-in-out infinite" : undefined,
                  position: "relative",
                  overflow: "hidden",
                }}
              >
                {/* Step number badge */}
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    right: 0,
                    background: statusColor(s),
                    color: "var(--bg)",
                    fontSize: 9,
                    fontWeight: 700,
                    padding: "2px 8px",
                    letterSpacing: "0.1em",
                  }}
                >
                  STEP {idx + 1}
                </div>

                <div
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}
                >
                  <div>
                    <div
                      style={{ color: statusColor(s), fontSize: 12, fontWeight: 700, letterSpacing: "0.05em" }}
                    >
                      {step.tool}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
                      {step.description}
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginTop: 8,
                    paddingTop: 8,
                    borderTop: "1px solid var(--border)",
                  }}
                >
                  <code
                    style={{
                      fontSize: 9,
                      color: "var(--text-dim)",
                      background: "var(--bg)",
                      padding: "2px 6px",
                      borderRadius: 2,
                    }}
                  >
                    out → {step.output_key}
                  </code>
                  <StatusBadge s={s} />
                </div>
              </div>

              {/* Connector arrow */}
              {!isLast && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    padding: "6px 0",
                    gap: 2,
                    color: "var(--text-dim)",
                  }}
                >
                  <div style={{ width: 1, height: 16, background: "var(--border-lit)" }} />
                  <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                    <path d="M5 8L0 0h10L5 8z" fill="var(--border-lit)" />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Log Terminal ──────────────────────────────────────────────────────────────
function Terminal({
  logs,
  isRunning,
  endRef,
}: {
  logs: LogEntry[];
  isRunning: boolean;
  endRef: React.RefObject<HTMLDivElement>;
}) {
  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: "12px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 3,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        lineHeight: 1.7,
      }}
    >
      {logs.length === 0 ? (
        <div style={{ color: "var(--text-dim)", opacity: 0.5 }}>
          ─ Waiting for execution ─
        </div>
      ) : (
        logs.map((entry) => (
          <div
            key={entry.id}
            className="animate-slide-in"
            style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
          >
            <span style={{ color: "var(--text-dim)", flexShrink: 0, fontSize: 10 }}>
              {entry.ts}
            </span>
            <span
              style={{
                color: LEVEL_COLOR[entry.level],
                flexShrink: 0,
                fontWeight: entry.level === "SUCCESS" || entry.level === "ERROR" ? 700 : 400,
              }}
            >
              {LEVEL_PREFIX[entry.level]}
            </span>
            <span
              style={{
                color: entry.level === "DATA"
                  ? "var(--blue)"
                  : entry.level === "SUCCESS"
                    ? "var(--green)"
                    : entry.level === "ERROR"
                      ? "var(--red)"
                      : "var(--text)",
                wordBreak: "break-word",
                whiteSpace: "pre-wrap",
              }}
            >
              {entry.message}
            </span>
          </div>
        ))
      )}

      {isRunning && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--amber)", marginTop: 4 }}>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              border: "1.5px solid var(--amber)",
              borderTopColor: "transparent",
              borderRadius: "50%",
              animation: "spin 0.7s linear infinite",
            }}
          />
          <span style={{ fontSize: 11, opacity: 0.8 }}>executing…</span>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}

// ── Preset commands ───────────────────────────────────────────────────────────
const PRESETS = [
  "Read ticket BUG-12 and post it to the dev channel",
  "Get the details of BUG-12 and notify #alerts on Slack",
  "Fetch BUG-12 from Jira and send a summary to the engineering channel",
];

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const [command, setCommand] = useState(PRESETS[0]);
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [dag, setDag] = useState<Dag | null>(null);
  const [stepStatuses, setStepStatuses] = useState<Record<string, StepStatus>>({});
  const [isDone, setIsDone] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll terminal
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  function addLog(level: LogLevel, message: string) {
    setLogs((prev) => [
      ...prev,
      {
        id: Math.random().toString(36).slice(2),
        level,
        message,
        ts: new Date().toTimeString().slice(0, 8),
      },
    ]);
  }

  async function handleExecute() {
    if (!command.trim() || isRunning) return;

    setIsRunning(true);
    setLogs([]);
    setDag(null);
    setStepStatuses({});
    setIsDone(false);

    const apiUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    try {
      const res = await fetch(`${apiUrl}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });

      if (!res.ok) {
        addLog("ERROR", `HTTP ${res.status} — ${res.statusText}`);
        return;
      }

      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });

        // SSE frames are separated by "\n\n"
        const frames = buf.split("\n\n");
        buf = frames.pop() ?? "";

        for (const frame of frames) {
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const evt = JSON.parse(line.slice(6));

              switch (evt.type) {
                case "log":
                  addLog(evt.level as LogLevel, evt.message);
                  break;
                case "dag":
                  setDag(evt.dag);
                  break;
                case "step_start":
                  setStepStatuses((p) => ({ ...p, [evt.step_id]: "running" }));
                  break;
                case "step_complete":
                  setStepStatuses((p) => ({ ...p, [evt.step_id]: "done" }));
                  break;
                case "error":
                  addLog("ERROR", evt.message ?? "Unknown error");
                  // Mark any running steps as errored
                  setStepStatuses((p) => {
                    const next = { ...p };
                    for (const k in next) {
                      if (next[k] === "running") next[k] = "error";
                    }
                    return next;
                  });
                  break;
                case "complete":
                  setIsDone(true);
                  break;
              }
            } catch {
              /* skip malformed frame */
            }
          }
        }
      }
    } catch (e) {
      addLog(
        "ERROR",
        `Connection failed: ${e instanceof Error ? e.message : String(e)}`
      );
    } finally {
      setIsRunning(false);
    }
  }

  // Derive panel dot status
  const dagDotClass = isRunning && dag ? "amber" : dag ? "green" : "";
  const logDotClass = isRunning ? "amber" : isDone ? "green" : "";

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        padding: 16,
        gap: 14,
        maxWidth: 1400,
        margin: "0 auto",
      }}
    >
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          paddingBottom: 12,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 9,
              letterSpacing: "0.35em",
              color: "var(--green)",
              marginBottom: 4,
            }}
          >
            MCP GATEWAY · PROOF OF CONCEPT
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 26,
              fontWeight: 800,
              color: "var(--text-bright)",
              letterSpacing: "0.05em",
              lineHeight: 1,
            }}
          >
            AUTOMATED BUG ROUTER
          </h1>
          <div
            style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}
          >
            2-Tool Demo · Jira MCP ↔ Slack MCP
          </div>
        </div>

        {/* Service status pills */}
        <div style={{ display: "flex", gap: 8 }}>
          {["JIRA :8081", "SLACK :8082", "BACKEND :8000"].map((s) => (
            <div
              key={s}
              style={{
                fontSize: 9,
                letterSpacing: "0.1em",
                color: "var(--green)",
                border: "1px solid var(--green)",
                padding: "3px 10px",
                borderRadius: 2,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "var(--green)",
                  display: "inline-block",
                }}
              />
              {s}
            </div>
          ))}
        </div>
      </header>

      {/* ── Command Input ──────────────────────────────────────────────────── */}
      <div className="panel">
        <div className="panel-header">
          <div className={`dot ${isRunning ? "amber" : "green"}`} />
          NATURAL LANGUAGE COMMAND
        </div>

        <div style={{ padding: "14px 16px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              border: "1px solid var(--border-lit)",
              background: "var(--bg)",
              borderRadius: 2,
              padding: "10px 14px",
              marginBottom: 10,
            }}
          >
            <span style={{ color: "var(--green)", fontSize: 14, flexShrink: 0 }}>
              ›_
            </span>
            <input
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                outline: "none",
                color: "var(--text-bright)",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                caretColor: "var(--green)",
              }}
              placeholder="Type a natural language command…"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleExecute()}
              disabled={isRunning}
            />
            <span className={isRunning ? "" : "blink"} style={{ color: "var(--green)", fontSize: 14 }}>
              ▋
            </span>
          </div>

          {/* Preset commands */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            <span style={{ fontSize: 10, color: "var(--text-dim)", marginRight: 4 }}>
              PRESETS:
            </span>
            {PRESETS.map((p, i) => (
              <button
                key={i}
                onClick={() => setCommand(p)}
                disabled={isRunning}
                style={{
                  fontSize: 10,
                  color: command === p ? "var(--green)" : "var(--text-dim)",
                  border: `1px solid ${command === p ? "var(--green)" : "var(--border)"}`,
                  background: command === p ? "var(--green-glow)" : "transparent",
                  padding: "2px 10px",
                  borderRadius: 2,
                  cursor: "pointer",
                  fontFamily: "var(--font-mono)",
                  transition: "all 0.15s",
                }}
              >
                {p.slice(0, 48)}…
              </button>
            ))}
          </div>

          <button
            onClick={handleExecute}
            disabled={isRunning || !command.trim()}
            style={{
              background: isRunning ? "transparent" : "var(--green)",
              color: isRunning ? "var(--amber)" : "var(--bg)",
              border: `1px solid ${isRunning ? "var(--amber)" : "var(--green)"}`,
              padding: "8px 28px",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: "0.15em",
              cursor: isRunning ? "not-allowed" : "pointer",
              borderRadius: 2,
              transition: "all 0.15s",
              animation: isRunning ? "pulse-amber 1.4s ease-in-out infinite" : undefined,
            }}
          >
            {isRunning ? "⠋ EXECUTING…" : "EXECUTE →"}
          </button>
        </div>
      </div>

      {/* ── Main Content: DAG + Terminal ───────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 14,
          minHeight: 460,
        }}
      >
        {/* ── Left: DAG Viewer ────────────────────────────────────────────── */}
        <div
          className="panel"
          style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <div className="panel-header">
            <div className={`dot ${dagDotClass}`} />
            EXECUTION PLAN · LLM-GENERATED DAG
            {dag && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 9,
                  color: "var(--green)",
                  border: "1px solid var(--green)",
                  padding: "1px 8px",
                  borderRadius: 2,
                }}
              >
                {dag.steps.length} STEP{dag.steps.length !== 1 ? "S" : ""}
              </span>
            )}
          </div>
          <DagFlowchart dag={dag} statuses={stepStatuses} />
        </div>

        {/* ── Right: Terminal ──────────────────────────────────────────────── */}
        <div
          className="panel"
          style={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            background: "#03080f",
          }}
        >
          <div className="panel-header" style={{ background: "#050d18" }}>
            <div className={`dot ${logDotClass}`} />
            LIVE EXECUTION LOGS
            {isDone && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 9,
                  color: "var(--green)",
                  fontWeight: 700,
                }}
              >
                WORKFLOW COMPLETE ✓
              </span>
            )}
          </div>
          <Terminal logs={logs} isRunning={isRunning} endRef={logsEndRef} />
        </div>
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <footer
        style={{
          borderTop: "1px solid var(--border)",
          paddingTop: 10,
          display: "flex",
          justifyContent: "space-between",
          fontSize: 9,
          color: "var(--text-dim)",
          letterSpacing: "0.1em",
        }}
      >
        <span>AUTOMATED BUG ROUTER v0.1 · AGENTIC MCP GATEWAY PoC</span>
        <span>JIRA-MOCK · SLACK-MOCK · GEMINI 1.5 FLASH</span>
      </footer>
    </div>
  );
}
