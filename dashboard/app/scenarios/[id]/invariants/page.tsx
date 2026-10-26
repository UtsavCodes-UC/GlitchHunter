"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { propose, runFilter, setInvariantStatus } from "@/lib/api";
import { useScenario } from "@/lib/useScenario";
import type { Invariant, InvariantStatus } from "@/lib/types";
import { Busy, ErrorBox, StatusBadge } from "@/components/ui";

function pct(v: number | null | undefined) { return v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`; }

export default function Invariants() {
  const { id } = useParams<{ id: string }>();
  const sc = useScenario(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decoys, setDecoys] = useState(false);
  const rows = sc.invariants ?? [];

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key); setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }
  async function decide(inv: Invariant, status: InvariantStatus) {
    setError(null);
    try { await setInvariantStatus(id, inv.id, status); await sc.refresh(); } catch (e) { setError((e as Error).message); }
  }
  const canDecide = (i: Invariant) => ["proposed", "approved", "rejected"].includes(i.status) && !!i.stats?.concurrent_fires;

  return (
    <>
      <p className="muted">
        A rule is a database query that returns nothing when the app is correct. The filter runs each rule on one-at-a-time requests (a rule that breaks there is wrong)
        and on simultaneous requests (a rule that never breaks cannot detect the bug). <b>You decide which surviving rules count.</b>
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <button disabled={busy !== null} onClick={() => run("propose", async () => { await propose(id); await sc.refresh(); })}>
          {busy === "propose" ? "Asking the AI…" : "Ask the AI for rules"}
        </button>
        <button disabled={busy !== null || rows.length === 0} className="secondary" onClick={() => run("filter", async () => { sc.setInvariants(await runFilter(id, decoys)); })}>
          {busy === "filter" ? "Filtering…" : "Run the filter"}
        </button>
        <label className="small"><input type="checkbox" checked={decoys} onChange={(e) => setDecoys(e.target.checked)} /> add a deliberately wrong rule (demo)</label>
        {busy && <Busy text={busy === "propose" ? "The AI is reading the code (usually under a minute; longer if the model is busy)…" : "Running one-at-a-time and simultaneous trials…"} />}
      </div>
      <ErrorBox message={sc.loadError} />
      <ErrorBox message={error} />
      {sc.invariants === null && <p className="muted">Loading…</p>}
      {sc.invariants !== null && rows.length === 0 && <div className="notice">No rules yet. Click “Ask the AI for rules”.</div>}
      {rows.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Rule</th><th>Source</th><th>Filter results</th><th>Status</th><th>Your decision</th></tr></thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td style={{ minWidth: 300 }}>
                    <b>{i.name}</b>
                    <div className="small">{i.english}</div>
                    <details><summary className="small">Show SQL</summary><pre>{i.sql}</pre></details>
                  </td>
                  <td>
                    {i.source === "llm" ? <span className="badge warn">AI-proposed, needs human approval</span> : <span className="badge grey">{i.source}</span>}
                  </td>
                  <td className="small">
                    {i.stats?.sequential_trials ? (
                      <dl className="kv">
                        <dt>one-at-a-time</dt><dd>fires {i.stats.sequential_fires}/{i.stats.sequential_trials}</dd>
                        <dt>simultaneous</dt><dd>fires {i.stats.concurrent_fires}/{i.stats.concurrent_trials}</dd>
                        <dt>recall on real races</dt><dd>{pct(i.stats.recall_on_race)} ({i.stats.races_observed} races)</dd>
                      </dl>
                    ) : <span className="muted">not filtered yet</span>}
                    {i.note && <div className="muted" style={{ marginTop: 4 }}>{i.note}</div>}
                  </td>
                  <td><StatusBadge status={i.status} /></td>
                  <td>
                    {canDecide(i) ? (
                      <div className="row" style={{ gap: 6 }}>
                        <button className="good" disabled={i.status === "approved"} onClick={() => decide(i, "approved")}>Approve</button>
                        <button className="danger" disabled={i.status === "rejected"} onClick={() => decide(i, "rejected")}>Reject</button>
                      </div>
                    ) : <span className="muted small">{i.status === "dropped" || i.status === "uninformative" ? "removed by the filter" : "run the filter first"}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted" style={{ marginTop: 14 }}>Approved rules: {sc.approved}. Attacks and repairs use only approved rules (if none are approved, a built-in conservation rule is used and the result says so).</p>
    </>
  );
}
