import type { TrialResult } from "@/lib/types";
import { copyFor, summarise } from "@/lib/copy";
import Timeline from "./Timeline";

const who = (i: number) => `Person ${String.fromCharCode(65 + i)}`;

// One failing run told as a story: start, what each person asked for, what happened, why it is wrong.
export default function Story({ trial, scenarioId }: { trial: TrialResult; scenarioId: string }) {
  const copy = copyFor(scenarioId);
  const s = summarise(trial, copy);
  return (
    <div className="story">
      <div className="story-line start">{copy.start(s.initial)}</div>
      {trial.requests.map((r) => (
        <div key={r.req} className="story-line">
          <b>{who(r.req)}</b> · {copy.action(r)}
          {r.status === 200 ? <span className="pill ok">✔ approved</span> : <span className="pill bad">✖ refused</span>}
        </div>
      ))}
      <div className="story-line end">{copy.end(s.final)}</div>
      {s.bothApproved && <div className="verdict bad">⚠ {copy.badNews(s.taken, s.initial)}</div>}
      <div className="small muted" style={{ margin: "14px 0 6px" }}>The same moment, drawn as a timeline: the shaded part is when both were being handled together.</div>
      <Timeline requests={trial.requests} />
    </div>
  );
}
