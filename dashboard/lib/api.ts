// One function per endpoint in docs/contracts.md. NEXT_PUBLIC_USE_MOCK=true returns the JSON in ../mock instead of calling the API.
import type { AttackResponse, Invariant, InvariantStatus, Project, RepairResponse, RunResponse, Scenario } from "./types";
import scenariosMock from "../mock/scenarios.json";
import invariantsMock from "../mock/invariants.json";
import attackMock from "../mock/attack.json";
import repairMock from "../mock/repair.json";

export const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "true";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:9000";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const mock = <T,>(x: unknown): T => JSON.parse(JSON.stringify(x)) as T; // mock JSON is loosely typed; the real API is the source of truth

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`Cannot reach the orchestrator at ${API_URL}. Is it running (python -m uvicorn orchestrator.api:app --port 9000)?`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// Mock mode keeps invariant decisions in memory so Approve / Reject still work without a backend.
let mockInvariants: Invariant[] = mock<Invariant[]>(invariantsMock.invariants);

export async function listScenarios(): Promise<Scenario[]> {
  if (USE_MOCK) { await sleep(150); return mock<Scenario[]>(scenariosMock); }
  return call("GET", "/scenarios");
}

export async function getInvariants(id: string): Promise<Invariant[]> {
  if (USE_MOCK) { await sleep(150); return id === "wallet" ? clone(mockInvariants) : []; }
  return (await call<{ invariants: Invariant[] }>("GET", `/scenarios/${id}/invariants`)).invariants;
}

export async function propose(id: string, samples = 3): Promise<{ invariants: Invariant[]; stats?: Record<string, unknown> }> {
  if (USE_MOCK) { await sleep(800); return { invariants: clone(mockInvariants), stats: invariantsMock.stats }; }
  return call("POST", `/scenarios/${id}/propose`, { samples });
}

export async function runFilter(id: string, includeDecoys = false): Promise<Invariant[]> {
  if (USE_MOCK) { await sleep(1200); return clone(mockInvariants); }
  return (await call<{ invariants: Invariant[] }>("POST", `/scenarios/${id}/filter`, { include_decoys: includeDecoys })).invariants;
}

export async function setInvariantStatus(id: string, invId: string, status: InvariantStatus): Promise<Invariant> {
  if (USE_MOCK) {
    mockInvariants = mockInvariants.map((i) => (i.id === invId ? { ...i, status } : i));
    return clone(mockInvariants.find((i) => i.id === invId)!);
  }
  return call("PATCH", `/scenarios/${id}/invariants/${encodeURIComponent(invId)}`, { status });
}

export async function attack(id: string, opts: { trials: number; delay_ms: number }): Promise<AttackResponse> {
  if (USE_MOCK) { await sleep(1000); return mock<AttackResponse>(attackMock); }
  return call("POST", `/scenarios/${id}/attack`, opts);
}

export async function repair(id: string, opts: { k: number; max_attempts: number }): Promise<RepairResponse> {
  if (USE_MOCK) { await sleep(1500); return mock<RepairResponse>(repairMock); }
  return call("POST", `/scenarios/${id}/repair`, opts);
}

const needLive = () => { throw new Error("“Try your own app” needs live mode: set NEXT_PUBLIC_USE_MOCK=false in dashboard/.env.local and restart the dashboard."); };

export async function uploadProject(p: { name: string; filename: string; content_b64: string; setup_sql: string; db_env: string; db_scheme: string; env: Record<string, string> }): Promise<Project> {
  if (USE_MOCK) return needLive();
  return call("POST", "/projects", p);
}

export interface NewScenario {
  method: string; path: string; params: Record<string, unknown>; path_params: Record<string, unknown>; json: unknown;
  headers: Record<string, string>; race_n: number; state: { table: string; column: string } | null; qty_key: string | null; pause_ms: number;
}

export async function createScenario(pid: string, p: NewScenario): Promise<{ id: string; title: string }> {
  if (USE_MOCK) return needLive();
  return call("POST", `/projects/${pid}/scenario`, p);
}

export async function getRun(runId: string): Promise<RunResponse> {
  if (USE_MOCK) { await sleep(100); const a = mock<AttackResponse>(attackMock); return { summary: a.summary, failing_trials: a.first_failing_trial ? [a.first_failing_trial] : [] }; }
  return call("GET", `/runs/${runId}`);
}
