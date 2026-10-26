import type { Scenario, TrialResult } from "@/lib/types";
import { copyFor, summarise } from "@/lib/copy";
import Timeline from "./Timeline";

const who = (i: number) => `Person ${String.fromCharCode(65 + i)}`;

// Uploaded projects: no single number to watch, so show every request and every table before and after.
function TableStory({ trial }: { trial: TrialResult }) {
  const bad = Object.values(trial.violations).some((rows) => !!rows && rows.length > 0);
  return (
    <div className="story">
      <div className="story-line start"><b>Before the requests</b></div>
      <pre>{JSON.stringify(trial.initial_tables, null, 1)}</pre>
      {trial.requests.map((r) => (
        <div key={r.req} className="story-line">
          <b>{who(r.req)}</b> · {r.method} {r.path} <code>{JSON.stringify(r.params)}</code>
          {r.status >= 200 && r.status < 300 ? <span className="pill ok">✔ approved ({r.status})</span> : <span className="pill bad">✖ refused ({r.status})</span>}
        </div>
      ))}
      <div className="story-line end"><b>After the requests</b></div>
      <pre>{JSON.stringify(trial.final_tables, null, 1)}</pre>
      {bad && <div className="verdict bad">⚠ A check failed: the tables after these requests do not add up with what the requests did. That mismatch is the bug.</div>}
      <div className="small muted" style={{ margin: "14px 0 6px" }}>The same moment, drawn as a timeline: the shaded part is when everyone was being handled together.</div>
      <Timeline requests={trial.requests} />
    </div>
  );
}

// One failing run told as a story: start, what each person asked for, what happened, why it is wrong.
export default function Story({ trial, scenarioId, meta }: { trial: TrialResult; scenarioId: string; meta?: Scenario | null }) {
  const copy = copyFor(scenarioId, meta);
  if (trial.initial_tables) return <TableStory trial={trial} />;
  const s = summarise(trial, copy);
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
