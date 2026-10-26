"use client";
import { useParams } from "next/navigation";
import { Fragment, useState } from "react";
import { repair as runRepair } from "@/lib/api";
import { useScenario } from "@/lib/useScenario";
import type { RepairAttempt } from "@/lib/types";
import Timeline from "@/components/Timeline";
import { Busy, ErrorBox, explainTrial } from "@/components/ui";

function Attempt({ a }: { a: RepairAttempt }) {
  const v = a.validation;
  const fresh = v?.fresh_trials ?? [];
  return (
    <div className={`attempt ${a.accepted ? "accepted" : "rejected"}`}>
      <div className="row spread">
        <h3>Attempt {a.attempt}{a.strategy ? ` · ${a.strategy}` : ""}</h3>
        {a.accepted ? <span className="badge ok">ACCEPTED</span> : <span className="badge bad">REJECTED</span>}
      </div>
      {a.explanation && <p className="small">{a.explanation}</p>}
      {!a.accepted && a.reason && <div className="error" style={{ fontWeight: 500 }}>Why it was rejected: {a.reason}</div>}
      {v && (
        <dl className="kv" style={{ margin: "8px 0" }}>
          <dt>Normal behaviour (regression)</dt>
          <dd>{v.regression_failures.length === 0 ? "unchanged" : `changed: ${v.regression_failures.join("; ")}`}</dd>
          {v.replay && (<><dt>Replay of the failing run</dt><dd>{v.replay.violations === 0 ? "no rule broke" : `a rule still broke (${v.replay.invariants.join(", ")})`}</dd></>)}
          {fresh.map((f) => (
            <Fragment key={f.delay_ms}><dt>Fresh trials, {f.delay_ms} ms pause</dt><dd>{f.violations} of {f.trials} trials broke a rule</dd></Fragment>
          ))}
          {v.throughput_rps !== undefined && (<><dt>Throughput</dt><dd>{v.throughput_rps} requests per second (one run, noisy)</dd></>)}
        </dl>
      )}
      {a.accepted && fresh.length > 0 && (
        <div className="small muted">
          Validated by rerunning the failing run and {fresh.map((f) => `${f.trials} fresh trials with a ${f.delay_ms} ms pause`).join(" and ")}. This is evidence, not a proof that the race is gone.
        </div>
      )}
      {a.patch && (
        <details style={{ marginTop: 8 }}><summary>Show the proposed code ({a.patch.file})</summary><pre>{a.patch.code}</pre></details>
      )}
    </div>
  );
}

export default function Repair() {
  const { id } = useParams<{ id: string }>();
  const sc = useScenario(id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const res = sc.repair;

  async function go() {
    setBusy(true); setError(null);
    try { sc.setRepair(await runRepair(id, { k: 50, max_attempts: 3 })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const nc = res?.negative_control;

  return (
    <>
      <p className="muted">
        The AI proposes a fixed endpoint. Each fix runs on a <b>copy</b> of the app and is accepted only if normal behaviour is unchanged, the failing run no longer breaks a rule,
        and fresh simultaneous trials show no violation. A rejected fix is sent back to the AI with the reason.
      </p>
      <div className="row" style={{ margin: "12px 0" }}>
        <button disabled={busy} onClick={go}>{busy ? "Testing fixes…" : "Propose and test fixes"}</button>
        {busy && <Busy text="Reproducing the bug, asking the AI, testing on a copy. This can take 1 to 3 minutes." />}
      </div>
      <ErrorBox message={error} />
      {!res && !busy && <div className="notice">No repair run yet in this session. The app must be running in vulnerable mode.</div>}
      {res && (
        <>
          {res.human_approved_invariants === false && <div className="notice">No rule was approved, so a built-in conservation rule was used.</div>}
          <div className="card" style={{ marginBottom: 12 }}>
            <div className="row spread">
              <h3>Verdict</h3>
              {res.accepted ? <span className="badge ok">A fix was accepted</span> : <span className="badge bad">No fix accepted</span>}
            </div>
            <div className="small">Evidence the AI was shown: {explainTrial(res.evidence)}</div>
            <div style={{ marginTop: 10 }}><Timeline requests={res.evidence.requests} /></div>
          </div>
          {res.attempts.map((a) => <Attempt key={a.attempt} a={a} />)}
          {nc && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="row spread">
                <h3>Control: does the validator reject the original buggy code?</h3>
                {nc.validator_working ? <span className="badge ok">validator working</span> : <span className="badge bad">validator did NOT reject the bug</span>}
              </div>
              <div className="small">The original buggy code was run through the same checks. {nc.buggy_code_accepted ? "It was accepted, so an ACCEPTED verdict above means nothing." : `It was rejected: ${nc.reason}`}</div>
            </div>
          )}
        </>
      )}
    </>
  );
}
