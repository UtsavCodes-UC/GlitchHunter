"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { attack as runAttack } from "@/lib/api";
import { useScenario } from "@/lib/useScenario";
import Timeline from "@/components/Timeline";
import { Busy, ErrorBox, Stat, explainTrial } from "@/components/ui";

export default function Attack() {
  const { id } = useParams<{ id: string }>();
  const sc = useScenario(id);
  const [trials, setTrials] = useState(50);
  const [delay, setDelay] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const res = sc.attack;
  const t = res?.first_failing_trial ?? null;

  async function go() {
    setBusy(true); setError(null);
    try { sc.setAttack(await runAttack(id, { trials, delay_ms: delay })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <p className="muted">
        Simultaneous requests are released together by a barrier and the trial is repeated. After each trial the approved rules are checked against the real database.
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <label>trials <input type="number" min={1} max={500} value={trials} onChange={(e) => setTrials(Number(e.target.value))} /></label>
        <label>test pause (ms) <input type="number" min={0} max={500} value={delay} onChange={(e) => setDelay(Number(e.target.value))} /></label>
        <button disabled={busy} onClick={go}>{busy ? "Attacking…" : "Run the attack"}</button>
        {busy && <Busy text="Sending simultaneous requests…" />}
      </div>
      <ErrorBox message={error} />
      {!res && !busy && <div className="notice">No attack run yet in this session. Run one above.</div>}
      {res && (
        <>
          {res.summary.human_approved === false && <div className="notice">No rule was approved, so a built-in conservation rule was used. Approve rules on the Rules tab to use your own.</div>}
          <div className="cards">
            <Stat label="Trials run" value={res.summary.trials} sub={`${res.summary.n} simultaneous requests each, ${res.summary.delay_ms} ms pause`} />
            <Stat label="Trials where a rule broke" value={res.summary.trials_with_violation} sub={`of ${res.summary.trials}`} />
            <Stat label="Real races observed" value={res.summary.races_observed} sub="more taken out than existed (evaluation check)" />
          </div>
          <h2>Which rules broke</h2>
          <div className="tablewrap"><table>
            <thead><tr><th>Rule</th><th>Trials where it broke</th></tr></thead>
            <tbody>{Object.entries(res.summary.per_invariant).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v} of {res.summary.trials}</td></tr>)}</tbody>
          </table></div>
          <h2>One failing run, replayable</h2>
          {t ? (
            <>
              <Timeline requests={t.requests} />
              <div className="card" style={{ marginTop: 12 }}>
                <b>In plain words:</b> {explainTrial(t)}
                <div className="small muted" style={{ marginTop: 6 }}>Run <code>{res.run_id}</code>, trial {t.trial ?? 0}. The full file is saved as JSON under runs/{res.run_id}/ so it can be replayed.</div>
              </div>
              <h3 style={{ marginTop: 16 }}>Rows returned by the broken rules</h3>
              {Object.entries(t.violations).filter(([, rows]) => rows && rows.length > 0).map(([k, rows]) => (
                <div key={k} className="small"><code>{k}</code> returned <code>{JSON.stringify(rows)}</code></div>
              ))}
            </>
          ) : <div className="notice">No failing trial in this run (no rule broke). Try more trials or a longer test pause.</div>}
        </>
      )}
    </>
  );
}
