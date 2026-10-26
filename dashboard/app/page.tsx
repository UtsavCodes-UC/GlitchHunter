"use client";

import { useState } from "react";
import {
  attack,
  filter,
  getRun,
  propose,
  repair,
  type AttackSummary,
  type Invariant,
  type RepairAttempt,
  type RepairResponse,
  type RunResult,
} from "../lib/api";

const scenarios = [
  { id: "wallet", label: "Wallet", description: "Concurrent withdrawals" },
  { id: "inventory", label: "Inventory", description: "Concurrent checkout" },
];

type StageId = "propose" | "filter" | "attack" | "explain" | "repair";
type StageStatus = "pending" | "running" | "success" | "violated" | "rejected";

const stages: Array<{ id: StageId; label: string; description: string }> = [
  { id: "propose", label: "Propose", description: "Generate invariants" },
  { id: "filter", label: "Filter", description: "Test rule quality" },
  { id: "attack", label: "Attack", description: "Run concurrency trials" },
  { id: "explain", label: "Explain", description: "Inspect the failing run" },
  { id: "repair", label: "Repair", description: "Validate a fix" },
];

const initialStatuses: Record<StageId, StageStatus> = {
  propose: "pending",
  filter: "pending",
  attack: "pending",
  explain: "pending",
  repair: "pending",
};

function statusLabel(status: StageStatus) {
  return {
    pending: "Pending",
    running: "Running",
    success: "Complete",
    violated: "Violation found",
    rejected: "Rejected",
  }[status];
}

function StatusBadge({ status }: { status: StageStatus | Invariant["status"] }) {
  const label =
    status in initialStatuses ? statusLabel(status as StageStatus) : status;
  return <span className={`badge badge-${status}`}>{label}</span>;
}

function AttackResultView({
  run,
  summary,
}: {
  run: RunResult;
  summary?: AttackSummary;
}) {
  const requestList = Array.isArray(run.requests)
    ? (run.requests as Array<{
        req: number;
        method: string;
        path: string;
        status: number;
        start_ms: number;
        end_ms: number;
      }>)
    : [];

  const entries = Object.entries(run.violations ?? {});
  const violationName =
    summary?.rule_name ?? (entries.length > 0 ? entries[0][0] : "unknown");
  const violationRows =
    violationName && run.violations?.[violationName]
      ? (run.violations[violationName] as number[][])
      : [];
  const violationRow = violationRows[0] ?? [];
  const [initialBalance, finalBalance, withdrawnAmount] = violationRow as number[];

  const startTimes = requestList.map((request) => Number(request.start_ms));
  const endTimes = requestList.map((request) => Number(request.end_ms));
  const minStart = startTimes.length ? Math.min(...startTimes) : 0;
  const maxEnd = endTimes.length ? Math.max(...endTimes) : 0;
  const span = maxEnd - minStart || 1;

  return (
    <section className="panel attack-result-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Attack result</p>
          <h2>Violation snapshot</h2>
        </div>
      </div>

      <div className="attack-summary-grid">
        <div className="metric-card">
          <span>Total trials</span>
          <strong>{summary?.total_trials ?? run.n}</strong>
        </div>
        <div className="metric-card">
          <span>Trials with violation</span>
          <strong>{summary?.trials_with_violation ?? 0}</strong>
        </div>
        <div className="metric-card">
          <span>Broken rule</span>
          <strong>{violationName}</strong>
        </div>
      </div>

      <div className="timeline-panel">
        <div className="timeline-header">
          <span>Failing trial timeline</span>
        </div>
        <div className="timeline-scale" aria-label="request timeline">
          {requestList.map((request) => {
            const left =
              ((Number(request.start_ms) - minStart) / span) * 100;
            const width =
              ((Number(request.end_ms) - Number(request.start_ms)) / span) * 100;

            return (
              <div
                key={`${request.req}-${request.path}-${request.status}`}
                className="request-bar"
                style={{
                  left: `${left}%`,
                  width: `${Math.max(width, 8)}%`,
                  background:
                    request.status >= 400 ? "#f05656" : "#41c9a8",
                }}
              >
                <span>{request.status}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="violation-copy">
        {violationRow.length > 0 ? (
          <p>
            started with {initialBalance}, ended with {finalBalance}, but {withdrawnAmount} was withdrawn
          </p>
        ) : (
          <p>Violation data is not available for this run.</p>
        )}
      </div>
    </section>
  );
}

function RepairView({ result }: { result: RepairResponse }) {
  return (
    <section className="panel repair-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Repair validation</p>
          <h2>Repair attempts</h2>
        </div>
        <span className="count-pill">{result.attempts.length} attempts</span>
      </div>

      <div className="repair-list">
        {result.attempts.map((attempt) => (
          <RepairAttemptCard key={attempt.attempt} attempt={attempt} />
        ))}
      </div>
    </section>
  );
}

function RepairAttemptCard({ attempt }: { attempt: RepairAttempt }) {
  const freshTrialCount = attempt.validation.fresh_trials.reduce(
    (total, trial) => total + trial.trials,
    0,
  );
  const statusLabel = attempt.accepted ? "ACCEPTED" : "REJECTED";

  return (
    <article className={`repair-card ${attempt.accepted ? "accepted" : ""}`}>
      <div className="repair-card-header">
        <div>
          <p className="eyebrow">Attempt {attempt.attempt}</p>
          <h3>{attempt.strategy}</h3>
        </div>
        <span className={`repair-status ${attempt.accepted ? "accepted" : "rejected"}`}>
          {statusLabel}
        </span>
      </div>

      <p className="repair-explanation">{attempt.explanation}</p>

      <div className="repair-grid">
        <div className="repair-block">
          <h4>Patch</h4>
          <p className="code-location">
            {attempt.patch.file} · {attempt.patch.function}
          </p>
          <pre className="patch-code"><code>{attempt.patch.code}</code></pre>
        </div>

        <div className="repair-block">
          <h4>Validation</h4>
          <dl className="validation-list">
            <div>
              <dt>Regression failures</dt>
              <dd>
                {attempt.validation.regression_failures.length > 0
                  ? attempt.validation.regression_failures.join(", ")
                  : "0"}
              </dd>
            </div>
            <div>
              <dt>Replay</dt>
              <dd>
                {attempt.validation.replay.trials} trials ·{" "}
                {attempt.validation.replay.violations} violations
              </dd>
            </div>
            {attempt.validation.fresh_trials.map((trial) => (
              <div key={trial.delay_ms}>
                <dt>Fresh trials at {trial.delay_ms} ms</dt>
                <dd>
                  {trial.trials} trials · {trial.violations} violations
                </dd>
              </div>
            ))}
            <div>
              <dt>Throughput</dt>
              <dd>{attempt.validation.throughput_rps} requests/sec</dd>
            </div>
          </dl>
        </div>
      </div>

      <div className={`repair-outcome ${attempt.accepted ? "accepted" : "rejected"}`}>
        <strong>{attempt.accepted ? "Accepted repair" : "Rejected repair"}</strong>
        <span>
          {attempt.accepted
            ? `validated by rerunning the failing run and ${freshTrialCount} fresh trials`
            : attempt.reason}
        </span>
      </div>
    </article>
  );
}

function InvariantsView({
  invariants,
  onStatusChange,
}: {
  invariants: Invariant[];
  onStatusChange: (id: string, status: "approved" | "dropped") => void;
}) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Rules ledger</p>
          <h2>Invariants</h2>
        </div>
        <span className="count-pill">{invariants.length} rules</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>English description</th>
              <th>SQL</th>
              <th>Source</th>
              <th>Filter stats</th>
              <th>Status</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {invariants.map((invariant) => {
              const stats = invariant.stats;
              return (
                <tr key={invariant.id}>
                  <td>
                    <strong>{invariant.name}</strong>
                    <small>{invariant.id}</small>
                  </td>
                  <td>{invariant.english}</td>
                  <td>
                    <details>
                      <summary>View SQL</summary>
                      <code>{invariant.sql}</code>
                    </details>
                  </td>
                  <td>
                    <span className="source">{invariant.source}</span>
                    {invariant.source === "llm" && (
                      <small className="approval-note">
                        AI-proposed, needs human approval
                      </small>
                    )}
                  </td>
                  <td>
                    <div className="stats">
                      <span>Seq: {stats?.sequential_fires ?? "—"}</span>
                      <span>Conc: {stats?.concurrent_fires ?? "—"}</span>
                      <span>
                        Recall:{" "}
                        {stats ? `${Math.round(stats.recall_on_race * 100)}%` : "—"}
                      </span>
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={invariant.status} />
                    {invariant.source === "llm" && (
                      <small className="approval-note">
                        AI-proposed, needs human approval
                      </small>
                    )}
                  </td>
                  <td>
                    {invariant.status === "proposed" ? (
                      <div className="review-actions">
                        <button
                          className="button button-approve"
                          onClick={() => onStatusChange(invariant.id, "approved")}
                        >
                          Approve
                        </button>
                        <button
                          className="button button-reject"
                          onClick={() => onStatusChange(invariant.id, "dropped")}
                        >
                          Reject
                        </button>
                      </div>
                    ) : (
                      <span className="muted">Reviewed</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function HomePage() {
  const [selectedScenario, setSelectedScenario] = useState("wallet");
  const [statuses, setStatuses] =
    useState<Record<StageId, StageStatus>>(initialStatuses);
  const [invariants, setInvariants] = useState<Invariant[]>([]);
  const [run, setRun] = useState<RunResult | null>(null);
  const [attackSummary, setAttackSummary] = useState<AttackSummary | null>(null);
  const [repairResult, setRepairResult] = useState<RepairResponse | null>(null);
  const [message, setMessage] = useState("Select a stage to begin.");

  // TODO: Use a PATCH to /scenarios/{id}/invariants/{invariant_id} with {"status": "approved"|"rejected"} once the contract is updated.
  const updateInvariantStatus = (id: string, status: "approved" | "dropped") => {
    setInvariants((current) =>
      current.map((invariant) =>
        invariant.id === id ? { ...invariant, status } : invariant,
      ),
    );
  };

  const updateStage = (stage: StageId, status: StageStatus) => {
    setStatuses((current) => ({ ...current, [stage]: status }));
  };

  const runStage = async (stage: StageId) => {
    updateStage(stage, "running");
    setMessage(`Running ${stage} for ${selectedScenario}...`);
    try {
      if (stage === "propose") {
        const result = await propose(selectedScenario);
        setInvariants(result.invariants);
        updateStage(stage, "success");
      } else if (stage === "filter") {
        const result = await filter(selectedScenario);
        setInvariants(result.invariants);
        updateStage(stage, "success");
      } else if (stage === "attack") {
        const result = await attack(selectedScenario, { n: 2, trials: 50, delay_ms: 0 });
        setAttackSummary(result.summary);
        const fetchedRun = await getRun(result.run_id);
        setRun(fetchedRun);
        updateStage(stage, Object.keys(fetchedRun.violations).length ? "violated" : "success");
      } else if (stage === "explain") {
        const result = await getRun(run?.run_id ?? "r_001");
        setRun(result);
        setAttackSummary(result.summary ?? attackSummary ?? { total_trials: 1, trials_with_violation: 1, rule_name: Object.keys(result.violations).at(0) ?? "unknown" });
        updateStage(stage, Object.keys(result.violations).length ? "violated" : "success");
      } else {
        const result = await repair(selectedScenario);
        setRepairResult(result);
        updateStage(stage, result.accepted ? "success" : "rejected");
      }
      setMessage(`${stage[0].toUpperCase()}${stage.slice(1)} completed.`);
    } catch (error) {
      updateStage(stage, "rejected");
      setMessage(error instanceof Error ? error.message : "The stage failed.");
    }
  };

  const selectScenario = (id: string) => {
    setSelectedScenario(id);
    setStatuses(initialStatuses);
    setInvariants([]);
    setRun(null);
    setAttackSummary(null);
    setRepairResult(null);
    setMessage("Select a stage to begin.");
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Concurrency diagnostics</p>
          <h1>GlitchHunter</h1>
        </div>
        <div className="live-indicator">
          <span /> Demo workspace
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">Scenario execution</p>
          <h2>Concurrency test results</h2>
          <p className="hero-copy">
            Run the analysis stages against a selected target and review the
            rules, request timeline, and repair validation.
          </p>
        </div>
        <div className="hero-metric">
          <strong>{invariants.length}</strong>
          <span>invariants loaded</span>
        </div>
      </section>

      <div className="workspace">
        <aside className="scenario-list panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Targets</p>
              <h2>Scenarios</h2>
            </div>
          </div>
          <div className="scenario-buttons">
            {scenarios.map((scenario) => (
              <button
                key={scenario.id}
                className={`scenario-button ${
                  selectedScenario === scenario.id ? "selected" : ""
                }`}
                onClick={() => selectScenario(scenario.id)}
              >
                <span className="scenario-icon">
                  {scenario.id === "wallet" ? "$" : "#"}
                </span>
                <span>
                  <strong>{scenario.label}</strong>
                  <small>{scenario.description}</small>
                </span>
                <span className="chevron">›</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel stepper-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Selected target</p>
              <h2>{selectedScenario} investigation</h2>
            </div>
            <span className="run-message">{message}</span>
          </div>
          <div className="stepper">
            {stages.map((stage, index) => (
              <div className="step" key={stage.id}>
                <div className={`step-number step-${statuses[stage.id]}`}>
                  {index + 1}
                </div>
                <div className="step-content">
                  <div className="step-title">
                    <div>
                      <strong>{stage.label}</strong>
                      <small>{stage.description}</small>
                    </div>
                    <StatusBadge status={statuses[stage.id]} />
                  </div>
                  <button
                    className="button button-run"
                    onClick={() => runStage(stage.id)}
                    disabled={statuses[stage.id] === "running"}
                  >
                    {statuses[stage.id] === "running" ? "Running..." : "Run"}
                  </button>
                </div>
              </div>
            ))}
          </div>
          {run && (
            <div className="run-summary">
              <span>Latest run: <strong>{run.run_id}</strong></span>
              <span>{Object.keys(run.violations).length} violation(s) detected</span>
            </div>
          )}
        </section>
      </div>

      {run && Object.keys(run.violations ?? {}).length > 0 && (
        <AttackResultView run={run} summary={attackSummary ?? run.summary} />
      )}

      {repairResult && <RepairView result={repairResult} />}

      <InvariantsView
        invariants={invariants}
        onStatusChange={updateInvariantStatus}
      />
    </main>
  );
}
