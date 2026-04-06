"use client";

import { useEffect, useRef, useState, RefObject } from "react";

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

type StepStatus = "idle" | "running" | "done" | "error" | "pending";

interface HitlRequest {
  execution_id: string;
  step_id: string;
  tool: string;
  risk: string;
  review_payload: {
    what: string;
    why: string;
    tool: string;
    params: Record<string, unknown>;
    context_from_prior_steps: Record<string, string>;
  };
}

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
  endRef: RefObject<HTMLDivElement>;
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

// ── HITL Approval Modal ───────────────────────────────────────────────────────
function ApprovalModal({
  request,
  onDecision,
  isDeciding,
}: {
  request: HitlRequest;
  onDecision: (decision: "approve" | "reject", reason?: string) => void;
  isDeciding: boolean;
}) {
  const { review_payload: rp, tool, step_id, execution_id } = request;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6,12,20,0.85)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        backdropFilter: "blur(4px)",
        animation: "fade-up 0.2s ease-out",
      }}
    >
      <div
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--amber)",
          borderRadius: 4,
          width: "min(640px, 95vw)",
          boxShadow: "0 0 40px rgba(255,163,64,0.2)",
          overflow: "hidden",
          animation: "fade-up 0.25s ease-out",
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            background: "rgba(255,163,64,0.08)",
            borderBottom: "1px solid var(--amber)",
            padding: "12px 18px",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span
            style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "var(--amber)",
              animation: "pulse-amber 1.2s ease-in-out infinite",
              flexShrink: 0,
            }}
          />
          <span style={{ color: "var(--amber)", fontSize: 11, fontWeight: 700, letterSpacing: "0.15em" }}>
            ⚠ HUMAN APPROVAL REQUIRED
          </span>
          <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            exec: {execution_id}
          </span>
        </div>

        {/* Modal Body */}
        <div style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Tool + risk badge */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <code style={{
              fontSize: 13, fontWeight: 700,
              color: "var(--amber)",
              background: "rgba(255,163,64,0.1)",
              padding: "4px 12px", borderRadius: 3,
              border: "1px solid var(--amber)",
            }}>{tool}</code>
            <span style={{
              fontSize: 9, letterSpacing: "0.15em",
              color: "var(--red)", border: "1px solid var(--red)",
              padding: "2px 8px", borderRadius: 2,
            }}>WRITE · SENSITIVE</span>
            <span style={{ fontSize: 9, color: "var(--text-dim)", marginLeft: "auto" }}>{step_id}</span>
          </div>

          {/* What + Why */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.1em" }}>ACTION</div>
            <div style={{
              fontSize: 12, color: "var(--text-bright)",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-lit)",
              borderRadius: 3, padding: "10px 14px",
              lineHeight: 1.6,
            }}>{rp.what}</div>
            <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>{rp.why}</div>
          </div>

          {/* Params */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.1em" }}>EXACT PAYLOAD BEING SENT</div>
            <pre style={{
              fontSize: 10, color: "var(--blue)",
              background: "#03080f",
              border: "1px solid var(--border-lit)",
              borderRadius: 3, padding: "10px 14px",
              overflow: "auto", maxHeight: 140,
              fontFamily: "var(--font-mono)",
              lineHeight: 1.6,
            }}>{JSON.stringify(rp.params, null, 2)}</pre>
          </div>

          {/* Prior context */}
          {Object.keys(rp.context_from_prior_steps).length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.1em" }}>CONTEXT FROM PRIOR STEPS</div>
              <pre style={{
                fontSize: 10, color: "var(--green)",
                background: "#03080f",
                border: "1px solid var(--border-lit)",
                borderRadius: 3, padding: "10px 14px",
                overflow: "auto", maxHeight: 120,
                fontFamily: "var(--font-mono)",
                lineHeight: 1.6,
              }}>{JSON.stringify(rp.context_from_prior_steps, null, 2)}</pre>
            </div>
          )}

          {/* CTA Buttons */}
          <div style={{ display: "flex", gap: 10, paddingTop: 4 }}>
            <button
              id="hitl-approve-btn"
              onClick={() => onDecision("approve")}
              disabled={isDeciding}
              style={{
                flex: 1,
                background: isDeciding ? "transparent" : "var(--green)",
                color: isDeciding ? "var(--green)" : "var(--bg)",
                border: "1px solid var(--green)",
                padding: "10px 0",
                fontFamily: "var(--font-mono)",
                fontSize: 12, fontWeight: 700,
                letterSpacing: "0.15em",
                cursor: isDeciding ? "not-allowed" : "pointer",
                borderRadius: 3,
                transition: "all 0.15s",
              }}
            >
              {isDeciding ? "⠋ PROCESSING…" : "✓ APPROVE"}
            </button>
            <button
              id="hitl-reject-btn"
              onClick={() => onDecision("reject", "Rejected by operator")}
              disabled={isDeciding}
              style={{
                flex: 1,
                background: "transparent",
                color: isDeciding ? "var(--text-dim)" : "var(--red)",
                border: `1px solid ${isDeciding ? "var(--border)" : "var(--red)"}`,
                padding: "10px 0",
                fontFamily: "var(--font-mono)",
                fontSize: 12, fontWeight: 700,
                letterSpacing: "0.15em",
                cursor: isDeciding ? "not-allowed" : "pointer",
                borderRadius: 3,
                transition: "all 0.15s",
              }}
            >
              ✗ REJECT
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Preset commands (grouped by server combo) ────────────────────────────────
const PRESET_GROUPS = [
  {
    label: "JIRA → SLACK",
    color: "var(--blue)",
    presets: [
      "Read ticket BUG-12 and post it to the #dev channel",
      "List all open Jira tickets and notify #alerts on Slack",
    ],
  },
  {
    label: "JIRA → GITHUB",
    color: "var(--amber)",
    presets: [
      "Read ticket BUG-12 and create a GitHub issue for it in acme-corp/backend",
      "List all open Jira tickets and create a GitHub issue tracking them in acme-corp/backend",
    ],
  },
  {
    label: "GITHUB → SHEETS",
    color: "var(--green)",
    presets: [
      "Get pull request #47 from acme-corp/backend and log its details into the On-Call Log sheet of sheet_oncall_log",
      "List open PRs in acme-corp/backend and log the summary into the Incidents sheet of sheet_bug_tracker",
    ],
  },
  {
    label: "ALL 4 SERVERS",
    color: "var(--red)",
    presets: [
      "Read ticket BUG-12, create a GitHub issue for it in acme-corp/backend, log it in the Incidents sheet of sheet_bug_tracker, then notify #dev",
      "List open Jira tickets, log them into the Summary sheet of sheet_bug_tracker, create a tracking GitHub issue in acme-corp/backend, and notify #general",
    ],
  },
];

const PRESETS = PRESET_GROUPS.flatMap((g) => g.presets);

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const [command, setCommand] = useState(PRESETS[0]);
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [dag, setDag] = useState<Dag | null>(null);
  const [stepStatuses, setStepStatuses] = useState<Record<string, StepStatus>>({});
  const [isDone, setIsDone] = useState(false);
  const [hitlRequest, setHitlRequest] = useState<HitlRequest | null>(null);
  const [isDeciding, setIsDeciding] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
                case "pending_approval":
                  setHitlRequest(evt as HitlRequest);
                  setStepStatuses((p) => ({ ...p, [evt.step_id]: "pending" }));
                  break;
                case "approved":
                  addLog("SUCCESS", `✓ Approved by human — step ${evt.step_id} will execute`);
                  setHitlRequest(null);
                  setIsDeciding(false);
                  break;
                case "rejected":
                  addLog("ERROR", `✗ Rejected — ${evt.reason}`);
                  setHitlRequest(null);
                  setIsDeciding(false);
                  setStepStatuses((p) => ({ ...p, [evt.step_id]: "error" }));
                  break;
                case "error":
                  addLog("ERROR", evt.message ?? "Unknown error");
                  setHitlRequest(null);
                  setIsDeciding(false);
                  setStepStatuses((p) => {
                    const next = { ...p };
                    for (const k in next) {
                      if (next[k] === "running" || next[k] === "pending") next[k] = "error";
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
      setHitlRequest(null);
      setIsDeciding(false);
    }
  }

  async function handleDecision(decision: "approve" | "reject", reason?: string) {
    if (!hitlRequest || isDeciding) return;
    setIsDeciding(true);
    try {
      await fetch(`${apiUrl}/hitl/${hitlRequest.execution_id}/${decision}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason ?? "" }),
      });
      // Modal will be dismissed by the `approved` / `rejected` SSE event
    } catch (e) {
      addLog("ERROR", `Failed to send decision: ${e instanceof Error ? e.message : String(e)}`);
      setIsDeciding(false);
    }
  }

  // Derive panel dot status
  const dagDotClass = hitlRequest ? "amber" : isRunning && dag ? "amber" : dag ? "green" : "";
  const logDotClass = hitlRequest ? "amber" : isRunning ? "amber" : isDone ? "green" : "";

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
      {/* ── HITL Approval Modal (renders on top of everything) ─────────────── */}
      {hitlRequest && (
        <ApprovalModal
          request={hitlRequest}
          onDecision={handleDecision}
          isDeciding={isDeciding}
        />
      )}

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
            4-Server Gateway · Jira · Slack · GitHub · Google Sheets
          </div>
        </div>

        {/* Service status pills */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {[
            { label: "JIRA", port: "8081", color: "var(--blue)" },
            { label: "SLACK", port: "8082", color: "var(--green)" },
            { label: "GITHUB", port: "8083", color: "var(--amber)" },
            { label: "SHEETS", port: "8084", color: "var(--green)" },
            { label: "BACKEND", port: "8000", color: "var(--green)" },
          ].map((s) => (
            <div
              key={s.label}
              style={{
                fontSize: 9,
                letterSpacing: "0.1em",
                color: s.color,
                border: `1px solid ${s.color}`,
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
                  background: s.color,
                  display: "inline-block",
                  animation: "pulse-amber 2s ease-in-out infinite",
                }}
              />
              {s.label} :{s.port}
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

          {/* Preset commands grouped by server combo */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
            {PRESET_GROUPS.map((group) => (
              <div key={group.label} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    color: group.color,
                    border: `1px solid ${group.color}`,
                    padding: "3px 8px",
                    borderRadius: 2,
                    flexShrink: 0,
                    marginTop: 1,
                    whiteSpace: "nowrap",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {group.label}
                </span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {group.presets.map((p, i) => (
                    <button
                      key={i}
                      onClick={() => setCommand(p)}
                      disabled={isRunning}
                      style={{
                        fontSize: 10,
                        color: command === p ? group.color : "var(--text-dim)",
                        border: `1px solid ${command === p ? group.color : "var(--border)"}`,
                        background: command === p ? `color-mix(in srgb, ${group.color} 10%, transparent)` : "transparent",
                        padding: "3px 10px",
                        borderRadius: 2,
                        cursor: isRunning ? "not-allowed" : "pointer",
                        fontFamily: "var(--font-mono)",
                        transition: "all 0.15s",
                        textAlign: "left",
                        maxWidth: 380,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={p}
                    >
                      {p.length > 52 ? p.slice(0, 52) + "…" : p}
                    </button>
                  ))}
                </div>
              </div>
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
        <span>AGENTIC MCP GATEWAY v0.2 · 4-SERVER ORCHESTRATION PoC</span>
        <span>JIRA-MOCK · SLACK-MOCK · GITHUB-MOCK · SHEETS-MOCK · GEMINI FLASH</span>
      </footer>
    </div>
  );
}
