// Plain-language wording per scenario. The numbers shown always come from the run data; only the sentences live here.
import type { RequestRecord, Scenario, TrialResult } from "./types";

export interface ScenarioCopy {
  title: string;
  story: string;          // one sentence a non-engineer understands
  attackButton: string;
  start: (n: number, key: string) => string;
  end: (n: number, key: string) => string;
  action: (r: RequestRecord) => string;
  badNews: (taken: number, initial: number) => string;   // used when more was taken than existed
  genericBad: string;                                     // used when a check failed but the numbers are not "money-like"
}

const rupee = (n: number) => `₹${n}`;
const firstParam = (r: RequestRecord) => Number(Object.values(r.params)[0] ?? 0);
const GENERIC_BAD = "A check failed: the data after these requests does not add up with what the requests did. That mismatch is the bug.";

const COPY: Record<string, ScenarioCopy> = {
  wallet: {
    title: "Wallet withdrawals",
    story: "Two people withdraw ₹80 from a wallet that holds ₹100, at the exact same moment.",
    attackButton: "Send two withdrawals at the same instant",
    start: (n) => `The wallet starts with ${rupee(n)}`,
    end: (n) => `The wallet ends with ${rupee(n)}`,
    action: (r) => `Withdraw ${rupee(firstParam(r))}`,
    badNews: (taken, initial) => `Both withdrawals were approved, so ${rupee(taken)} was paid out of a wallet that only held ${rupee(initial)}. The wallet should have refused one of them.`,
    genericBad: GENERIC_BAD,
  },
  inventory: {
    title: "Last item in stock",
    story: "Two shoppers try to buy the last item in the shop at the exact same moment.",
    attackButton: "Send two purchases at the same instant",
    start: (n) => `The shop starts with ${n} in stock`,
    end: (n) => `The shop ends with ${n} in stock`,
    action: (r) => `Buy ${firstParam(r)}`,
    badNews: (taken, initial) => `Both purchases were approved, so ${taken} items were sold but the shop only had ${initial}. One shopper should have been told it is sold out.`,
    genericBad: GENERIC_BAD,
  },
};

export function copyFor(id: string, meta?: Pick<Scenario, "title" | "custom" | "race_n" | "endpoint"> | null): ScenarioCopy {
  if (COPY[id]) return COPY[id];
  const n = meta?.race_n ?? 2, ep = meta?.endpoint;
  const where = ep ? `${ep.method} ${ep.path}` : id;
  return {
    title: meta?.title ?? id,
    story: `${n} requests hit ${where} in your app at the exact same moment.`,
    attackButton: `Send ${n} requests at the same instant`,
    start: (v, key) => `Before: ${key} is ${v}`,
    end: (v, key) => `After: ${key} is ${v}`,
    action: (r) => `${r.method} ${r.path} ${Object.keys(r.params).length ? JSON.stringify(r.params) : ""}`,
    badNews: (taken, initial) => `${taken} was taken in total but only ${initial} existed. The app should have refused some of the requests.`,
    genericBad: GENERIC_BAD,
  };
}

// Plain names for the fix strategies the AI tends to propose.
export function strategyLabel(s?: string): string {
  const t = (s ?? "").toLowerCase();
  if (t.includes("for update") || t.includes("for_update") || t.includes("lock the row") || t.includes("row lock")) return "Make the second request wait its turn (lock the row)";
  if (t.includes("atomic") || t.includes("conditional") || t.includes("returning")) return "Check and update in one single step";
  if (t.includes("advisory")) return "Make requests take turns using a lock";
  if (t.includes("conflict") || t.includes("unique")) return "Let the database refuse duplicates (unique rule)";
  return s ? s : "A fix proposed by the AI";
}

export function summarise(t: TrialResult, copy: ScenarioCopy) {
  const key = Object.keys(t.initial_state).find((k) => t.initial_state[k] !== null) ?? "value";
  const initial = Number(t.initial_state[key] ?? 0), final = Number(t.final_state[key] ?? 0);
  const approved = t.requests.filter((r) => r.status === 200);
  const taken = approved.reduce((a, r) => a + firstParam(r), 0);
  const failed = Object.values(t.violations).some((rows) => !!rows && rows.length > 0);
  return { key, initial, final, taken, bothApproved: approved.length > 1 && taken > initial, failed, copy };
}
