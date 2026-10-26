import attackRun from "../mock/attack_run.json";
import filterResult from "../mock/filter.json";
import proposeResult from "../mock/propose.json";
import repairResult from "../mock/repair.json";

export type ScenarioId = string;

export interface Invariant {
  id: string;
  name: string;
  english: string;
  sql: string;
  source: "llm" | "mined" | "manual";
  status: "proposed" | "approved" | "dropped" | "uninformative";
  stats?: {
    sequential_fires: number;
    concurrent_fires: number;
    recall_on_race: number;
  };
}

export interface InvariantResponse {
  invariants: Invariant[];
}

export interface AttackRequest {
  n: number;
  trials: number;
  delay_ms: number;
}

export interface AttackSummary {
  total_trials: number;
  trials_with_violation: number;
  rule_name: string;
}

export interface AttackResponse {
  run_id: string;
  summary: AttackSummary;
}

export interface RunResult {
  run_id: string;
  scenario: string;
  n: number;
  delay_ms: number;
  trial: number;
  initial_state: Record<string, number>;
  requests: Array<Record<string, unknown>>;
  final_state: Record<string, number>;
  violations: Record<string, unknown[][]>;
  summary?: AttackSummary;
}

export interface FreshTrialResult {
  delay_ms: number;
  trials: number;
  violations: number;
}

export interface RepairValidation {
  regression_failures: string[];
  replay: {
    trials: number;
    violations: number;
  };
  fresh_trials: FreshTrialResult[];
  throughput_rps: number;
}

export interface RepairAttempt {
  attempt: number;
  strategy: string;
  explanation: string;
  patch: {
    file: string;
    function: string;
    code: string;
  };
  validation: RepairValidation;
  accepted: boolean;
  reason: string;
}

export interface RepairResponse {
  attempts: RepairAttempt[];
  accepted: boolean;
}

const useMock = process.env.NEXT_PUBLIC_USE_MOCK === "true";
const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:9000";

async function request<T>(
  path: string,
  init: RequestInit,
  mockData: T,
): Promise<T> {
  if (useMock) {
    return mockData;
  }

  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API request failed (${response.status}): ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export async function propose(scenarioId: ScenarioId): Promise<InvariantResponse> {
  return request(
    `/scenarios/${encodeURIComponent(scenarioId)}/propose`,
    { method: "POST" },
    proposeResult as InvariantResponse,
  );
}

export async function filter(scenarioId: ScenarioId): Promise<InvariantResponse> {
  return request(
    `/scenarios/${encodeURIComponent(scenarioId)}/filter`,
    { method: "POST" },
    filterResult as InvariantResponse,
  );
}

export async function attack(
  scenarioId: ScenarioId,
  body: AttackRequest,
): Promise<AttackResponse> {
  return request(
    `/scenarios/${encodeURIComponent(scenarioId)}/attack`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
    {
      run_id: attackRun.run_id,
      summary: attackRun.summary as AttackSummary,
    },
  );
}

export async function repair(scenarioId: ScenarioId): Promise<RepairResponse> {
  return request(
    `/scenarios/${encodeURIComponent(scenarioId)}/repair`,
    { method: "POST" },
    repairResult as RepairResponse,
  );
}

export async function getRun(runId: string): Promise<RunResult> {
  return request(
    `/runs/${encodeURIComponent(runId)}`,
    { method: "GET" },
    attackRun as RunResult,
  );
}
