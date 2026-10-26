"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { attack as runAttack, propose, repair as runRepair, runFilter } from "@/lib/api";
import { useScenario } from "@/lib/useScenario";
import { Busy, ErrorBox } from "@/components/ui";

export default function Overview() {
  const { id } = useParams<{ id: string }>();
  const sc = useScenario(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decoys, setDecoys] = useState(false);

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key); setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }
  const actions: Record<string, { label: string; go: () => Promise<void> }> = {
    propose: { label: "Ask the AI for rules", go: async () => { await propose(id); await sc.refresh(); } },
    filter: { label: "Run the filter", go: async () => { sc.setInvariants(await runFilter(id, decoys)); } },
    attack: { label: "Attack (50 trials)", go: async () => { sc.setAttack(await runAttack(id, { trials: 50, delay_ms: 0 })); } },
    repair: { label: "Propose and test fixes", go: async () => { sc.setRepair(await runRepair(id, { k: 50, max_attempts: 3 })); } },
  };
  const notes: Record<string, string> = {
    propose: "The AI reads the endpoint code and the live table schema and proposes rules.",
    filter: "Rules that break on one-at-a-time runs are dropped; rules that never break under attack are uninformative.",
    attack: "Simultaneous requests released together, repeated. Needs at least one APPROVED rule (otherwise a built-in rule is used).",
    explain: "The saved failing run: who overlapped, which rule broke.",
    repair: "Each fix runs on a copy of the app. Can take 1 to 3 minutes.",
  };

  return (
    <>
      <ErrorBox message={sc.loadError} />
      <ErrorBox message={error} />
      <div className="stepper">
        {sc.stages.map((st, i) => (
          <div key={st.key} className={`step ${st.done ? "done" : ""}`}>
            <div className="n">Step {i + 1}</div>
            <h3>{st.label}</h3>
            <div className="small muted" style={{ minHeight: 40 }}>{notes[st.key]}</div>
            <div className="small" style={{ margin: "6px 0 10px" }}><span className={`badge ${st.done ? "ok" : "grey"}`}>{st.done ? "done" : "to do"}</span> {st.detail}</div>
            {actions[st.key] ? (
              <button disabled={busy !== null} onClick={() => run(st.key, actions[st.key].go)}>
                {busy === st.key ? "Running…" : actions[st.key].label}
              </button>
            ) : (
              <Link href={`/scenarios/${id}/attack`}>View the failing run</Link>
            )}
            {st.key === "filter" && (
              <label style={{ display: "flex", marginTop: 8 }} className="small">
                <input type="checkbox" checked={decoys} onChange={(e) => setDecoys(e.target.checked)} /> add a deliberately wrong rule (demo)
              </label>
            )}
            {st.key === "filter" && <div className="small" style={{ marginTop: 6 }}><Link href={`/scenarios/${id}/invariants`}>Review and approve rules</Link></div>}
          </div>
        ))}
      </div>
      {busy && <p><Busy text={busy === "repair" ? "Testing fixes on a copy of the app. This can take a few minutes." : "Working…"} /></p>}
      <p className="small muted" style={{ marginTop: 18 }}>
        A human approves the rules before they count. AI-proposed rules are suggestions; the filter only removes rules that are wrong on one-at-a-time runs.
      </p>
    </>
  );
}
