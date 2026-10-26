"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { attack as runAttack, propose, repair as runRepair, runFilter, setInvariantStatus } from "@/lib/api";
import { copyFor, strategyLabel } from "@/lib/copy";
import { useScenario } from "@/lib/useScenario";
import type { Invariant, RepairAttempt } from "@/lib/types";
import Story from "@/components/Story";
import { Busy, ErrorBox } from "@/components/ui";

const usable = (i: Invariant) => ["proposed", "approved", "rejected"].includes(i.status) && !!i.stats?.concurrent_fires;

// Checks that behaved identically in every run (same counts on the one-at-a-time and the simultaneous runs) are the same check
// worded differently, so they are shown as ONE card and a decision applies to the whole group.
function groupChecks(list: Invariant[]): Invariant[][] {
  const groups = new Map<string, Invariant[]>();
  for (const i of list) {
    const s = i.stats;
    const key = [s.sequential_fires, s.concurrent_fires, s.concurrent_trials, s.races_observed].join("|");
    groups.set(key, [...(groups.get(key) ?? []), i]);
  }
  // show the shortest wording first
  return [...groups.values()].map((g) => [...g].sort((a, b) => (a.english || a.name).length - (b.english || b.name).length));
}
const groupStatus = (g: Invariant[]) => (g.some((i) => i.status === "approved") ? "approved" : g.every((i) => i.status === "rejected") ? "rejected" : "proposed");

function Check({ group, onDecide }: { group: Invariant[]; onDecide: (g: Invariant[], s: "approved" | "rejected") => void }) {
  const inv = group[0], s = inv.stats, status = groupStatus(group);
  const others = group.length - 1;
  return (
    <div className={`check ${status}`}>
      <div className="row spread">
        <div>
          <b>{inv.english || inv.name}</b>
          <div className="small muted">
            {group.some((i) => i.source === "llm") ? "Suggested by the AI" : "Built-in check"}
            {others > 0 && ` · ${others} other suggestion${others > 1 ? "s" : ""} said the same thing in different words`}
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button className={status === "approved" ? "good" : "secondary"} onClick={() => onDecide(group, "approved")}>{status === "approved" ? "✔ Using this" : "Use this check"}</button>
          {status !== "rejected" && <button className="danger" onClick={() => onDecide(group, "rejected")}>Skip</button>}
          {status === "rejected" && <span className="badge grey">skipped</span>}
        </div>
      </div>
      <details>
        <summary className="small">Why we trust it</summary>
        <p className="small" style={{ margin: "6px 0" }}>
          In normal use (one request at a time) it stayed quiet in {s.sequential_trials! - s.sequential_fires!} of {s.sequential_trials} runs.
          With simultaneous requests it raised the alarm in {s.concurrent_fires} of {s.concurrent_trials} runs.
          {others > 0 && " The other wordings behaved identically in every run, so we treat them as one check."}
        </p>
        <pre>{inv.sql}</pre>
      </details>
    </div>
  );
}

function FixResult({ attempts, accepted, control }: { attempts: RepairAttempt[]; accepted: boolean; control: { validator_working: boolean; reason: string } }) {
  const final = attempts.find((a) => a.accepted) ?? attempts[attempts.length - 1];
  const earlier = attempts.filter((a) => a !== final);
  const v = final?.validation;
  const tick = (key: string, ok: boolean, text: string) => <li key={key} className={ok ? "tick ok" : "tick bad"}>{ok ? "✔" : "✖"} {text}</li>;
  return (
    <div>
      <div className={`verdict ${accepted ? "ok" : "bad"}`}>{accepted ? "✅ A fix was found and it passed every test." : "❌ No safe fix was found in the attempts we made."}</div>
      {final && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3>What the AI changed</h3>
          <p style={{ margin: "2px 0 6px" }}><b>{strategyLabel(final.strategy)}</b></p>
          {final.explanation && <p className="small muted" style={{ margin: 0 }}>{final.explanation}</p>}
          {v && (
            <>
              <h3 style={{ marginTop: 14 }}>How we tested it</h3>
              <ul className="ticks">
                {tick("everyday", v.regression_failures.length === 0, "Everyday use still works as before")}
                {v.replay && tick("replay", v.replay.violations === 0, "The exact situation that broke it before no longer breaks")}
                {v.fresh_trials?.map((f) => tick(`fresh-${f.delay_ms}`, f.violations === 0, `${f.trials} more simultaneous tries${f.delay_ms ? ` with a ${f.delay_ms} ms pause` : ""}: ${f.violations === 0 ? "none went wrong" : `${f.violations} went wrong`}`))}
              </ul>
              {v.throughput_rps !== undefined && <p className="small muted">Speed check: about {v.throughput_rps} requests per second (a single quick measurement).</p>}
            </>
          )}
          {final.patch && <details style={{ marginTop: 8 }}><summary className="small">Show the code the AI wrote</summary><pre>{final.patch.code}</pre></details>}
        </div>
      )}
      {earlier.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary className="small">{earlier.length} earlier attempt{earlier.length > 1 ? "s were" : " was"} rejected: see why</summary>
          {earlier.map((a) => <p key={a.attempt} className="small muted">Attempt {a.attempt}: {a.reason || "rejected"}</p>)}
        </details>
      )}
      <div className={`trust ${control.validator_working ? "" : "bad"}`}>
        {control.validator_working
          ? "Can we trust the tests? We also fed the ORIGINAL buggy code through the same tests, and they rejected it, as they should."
          : "Warning: the tests did NOT reject the original buggy code, so do not trust the verdict above."}
      </div>
      <p className="small muted">“Passed” means no failure showed up in these tests. It is evidence, not a mathematical proof.</p>
    </div>
  );
}

export default function ScenarioPage() {
  const { id } = useParams<{ id: string }>();
  const copy = copyFor(id);
  const sc = useScenario(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key); setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }
  async function decide(group: Invariant[], status: "approved" | "rejected") {
    setError(null);
    try { for (const i of group) await setInvariantStatus(id, i.id, status); await sc.refresh(); } catch (e) { setError((e as Error).message); }
  }

  const inv = sc.invariants ?? [];
  const checks = groupChecks(inv.filter(usable));
  const selected = checks.filter((g) => groupStatus(g) === "approved").length;
  const thrown = inv.filter((i) => i.status === "dropped" || i.status === "uninformative");
  const a = sc.attack, r = sc.repair, t = a?.first_failing_trial ?? null;

  return (
    <>
      <p><Link href="/">← All examples</Link></p>
      <h1>{copy.title}</h1>
      <p className="lead">{copy.story}</p>
      <ErrorBox message={error ?? sc.loadError} />

      <section className="sec">
        <div className="secnum">1</div>
        <div className="secbody">
          <h2>See the bug</h2>
          <p className="muted">We send the requests at the same instant, 50 times, and look at what happens.</p>
          <button disabled={busy !== null} onClick={() => run("attack", async () => { sc.setAttack(await runAttack(id, { trials: 50, delay_ms: 0 })); })}>
            {busy === "attack" ? "Sending requests…" : copy.attackButton}
          </button>{" "}
          {busy === "attack" && <Busy text="Hitting the app 50 times…" />}
          {a && (
            <div style={{ marginTop: 16 }}>
              <div className={`verdict ${a.summary.trials_with_violation > 0 ? "bad" : "ok"}`}>
                {a.summary.trials_with_violation > 0
                  ? `It went wrong in ${a.summary.trials_with_violation} of ${a.summary.trials} tries.`
                  : `It did not go wrong in these ${a.summary.trials} tries. Try again.`}
              </div>
              {t && <div style={{ marginTop: 12 }}><h3>One of the failed tries</h3><Story trial={t} scenarioId={id} /></div>}
            </div>
          )}
        </div>
      </section>

      <section className="sec">
        <div className="secnum">2</div>
        <div className="secbody">
          <h2>How does the app know it went wrong?</h2>
          <p className="muted">
            A <b>check</b> is a statement that must always be true, such as “money that left the wallet plus money still in it equals what we started with”.
            If a check fails, there is a bug. The AI suggests checks, we test them, and <b>you decide which ones count</b>.
          </p>
          <button className="secondary" disabled={busy !== null} onClick={() => run("checks", async () => { await propose(id); sc.setInvariants(await runFilter(id, true)); })}>
            {busy === "checks" ? "Working…" : checks.length ? "Ask the AI again" : "Ask the AI to suggest checks"}
          </button>{" "}
          {busy === "checks" && <Busy text="The AI is reading the code, then we test its checks. This can take a minute or two." />}
          {checks.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <h3>Checks that can spot this bug</h3>
              {checks.map((g) => <Check key={g[0].id} group={g} onDecide={decide} />)}
              <p className="small muted">{selected} selected. If you select none, we use a built-in check. Your choices are used the next time you press the button in step 1 or step 3.</p>
            </div>
          )}
          {thrown.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary className="small">{thrown.length} suggested check{thrown.length > 1 ? "s were" : " was"} thrown out: see why</summary>
              {thrown.map((i) => (
                <p key={i.id} className="small muted">
                  <b>{i.english || i.name}</b><br />
                  {i.status === "dropped" ? "Thrown out: it raised the alarm even when nothing was wrong, so the check itself is wrong." : "Thrown out: it never raised the alarm in the broken runs, so it cannot spot this bug."}
                </p>
              ))}
            </details>
          )}
        </div>
      </section>

      <section className="sec">
        <div className="secnum">3</div>
        <div className="secbody">
          <h2>Fix it, then prove the fix</h2>
          <p className="muted">The AI writes a fix. We run it on a <b>copy</b> of the app and only accept it if it passes every test.</p>
          <button disabled={busy !== null} onClick={() => run("repair", async () => { sc.setRepair(await runRepair(id, { k: 50, max_attempts: 3 })); })}>
            {busy === "repair" ? "Working on a fix…" : "Ask the AI for a fix and test it"}
          </button>{" "}
          {busy === "repair" && <Busy text="The AI writes a fix, then we test it 100+ times. This takes 1 to 3 minutes." />}
          {r && <div style={{ marginTop: 16 }}><FixResult attempts={r.attempts} accepted={r.accepted} control={r.negative_control} /></div>}
        </div>
      </section>
    </>
  );
}
