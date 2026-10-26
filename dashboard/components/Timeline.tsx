import type { RequestRecord } from "@/lib/types";

// Horizontal bars positioned by start_ms / end_ms. The shaded band is the stretch where ALL requests were in flight together.
export default function Timeline({ requests }: { requests: RequestRecord[] }) {
  if (requests.length === 0) return null;
  const max = Math.max(...requests.map((r) => r.end_ms), 1);
  const pct = (ms: number) => `${(ms / max) * 100}%`;
  const oStart = Math.max(...requests.map((r) => r.start_ms));
  const oEnd = Math.min(...requests.map((r) => r.end_ms));
  const overlap = requests.length > 1 && oEnd > oStart;
  return (
    <div className="timeline" role="img" aria-label="Timeline of the simultaneous requests">
      {requests.map((r) => (
        <div className="tl-row" key={r.req}>
          <div className="tl-label">Person {String.fromCharCode(65 + r.req)}</div>
          <div className="tl-track">
            {overlap && <div className="tl-overlap" style={{ left: pct(oStart), width: `${((oEnd - oStart) / max) * 100}%` }} />}
            <div className={`tl-bar ${r.status === 200 ? "s200" : r.status === 409 ? "s409" : "sother"}`}
                 style={{ left: pct(r.start_ms), width: `${Math.max(((r.end_ms - r.start_ms) / max) * 100, 6)}%` }}>
              {r.status === 200 ? "approved" : r.status === 409 ? "refused" : `error ${r.status}`}
            </div>
          </div>
        </div>
      ))}
      <div className="tl-axis"><span>0 ms</span><span>{max.toFixed(0)} ms</span></div>
      {overlap && <div className="small muted" style={{ marginTop: 6 }}>Both were being handled together for {(oEnd - oStart).toFixed(0)} ms.</div>}
    </div>
  );
}
