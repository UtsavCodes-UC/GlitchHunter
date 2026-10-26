import type { InvariantStatus, TrialResult } from "@/lib/types";

export function StatusBadge({ status }: { status: InvariantStatus }) {
  const map: Record<InvariantStatus, [string, string]> = {
    proposed: ["info", "proposed"], approved: ["ok", "approved"], rejected: ["bad", "rejected"],
    dropped: ["bad", "dropped"], uninformative: ["grey", "uninformative"],
  };
  const [cls, label] = map[status] ?? ["grey", status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function Busy({ text }: { text: string }) {
  return <span className="busy"><span className="spin" />{text}</span>;
}

export function ErrorBox({ message }: { message: string | null }) {
  return message ? <div className="error">{message}</div> : null;
}

// Plain-words reading of one failing trial, built only from the trial's own data.
export function explainTrial(t: TrialResult): string {
  const key = Object.keys(t.initial_state).find((k) => t.initial_state[k] !== null) ?? "value";
  const ok = t.requests.filter((r) => r.status === 200);
  const amounts = ok.map((r) => Number(Object.values(r.params)[0] ?? 0));
  const total = amounts.reduce((a, b) => a + b, 0);
  return `Started with ${key} = ${t.initial_state[key]}, ended with ${t.final_state[key]}, but ${ok.length} successful request${ok.length === 1 ? "" : "s"} took ${total} in total (${amounts.join(" + ") || "0"}).`;
}

export function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card">
      <div className="muted small">{label}</div>
      <div className="stat">{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}
