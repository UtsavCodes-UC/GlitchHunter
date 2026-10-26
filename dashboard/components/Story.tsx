import type { Scenario, TrialResult } from "@/lib/types";
import { copyFor, summarise } from "@/lib/copy";
import Timeline from "./Timeline";

const who = (i: number) => `Person ${String.fromCharCode(65 + i)}`;

// One failing run told as a story: start, what each person asked for, what happened, why it is wrong.
export default function Story({ trial, scenarioId, meta }: { trial: TrialResult; scenarioId: string; meta?: Scenario | null }) {
  const copy = copyFor(scenarioId, meta);
  const s = summarise(trial, copy, meta?.custom ? (meta.qty_key ?? "") : undefined);
  return (
    <div className="story">
      <div className="story-line start">{copy.start(s.initial, s.key)}</div>
      {trial.requests.map((r) => (
        <div key={r.req} className="story-line">
          <b>{who(r.req)}</b> · {copy.action(r)}
          {r.status >= 200 && r.status < 300 ? <span className="pill ok">✔ approved</span> : <span className="pill bad">✖ refused</span>}
        </div>
      ))}
      <div className="story-line end">{copy.end(s.final, s.key)}</div>
      {s.bothApproved ? <div className="verdict bad">⚠ {copy.badNews(s.taken, s.initial)}</div>
        : s.failed ? <div className="verdict bad">⚠ {copy.genericBad}</div> : null}
      <div className="small muted" style={{ margin: "14px 0 6px" }}>The same moment, drawn as a timeline: the shaded part is when everyone was being handled together.</div>
      <Timeline requests={trial.requests} />
    </div>
  );
}
