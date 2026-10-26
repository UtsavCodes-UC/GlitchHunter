// Shapes follow docs/contracts.md. Do not rename fields here without changing the contract.
export type InvariantStatus = "proposed" | "approved" | "rejected" | "dropped" | "uninformative";

export interface InvariantStats {
  sequential_trials?: number;
  sequential_fires?: number;
  concurrent_trials?: number;
  concurrent_fires?: number;
  races_observed?: number;
  recall_on_race?: number | null;
}

export interface Invariant {
  id: string;
  name: string;
  english: string;
  sql: string;
  source: "llm" | "mined" | "manual";
  status: InvariantStatus;
  stats: InvariantStats;
  note?: string;
}

export interface RequestRecord {
  req: number;
  method: string;
  path: string;
  params: Record<string, number | string>;
  status: number;
  start_ms: number;
  end_ms: number;
}

export interface TrialResult {
  run_id?: string;
  scenario: string;
  n: number;
  delay_ms: number;
  trial?: number;
  initial_state: Record<string, number | null>;
  requests: RequestRecord[];
  final_state: Record<string, number | null>;
  violations: Record<string, unknown[][] | null>;
}

export interface Scenario {
  id: string;
  endpoint: { method: string; path: string; params: Record<string, number | string> };
  invariants: number;
}

export interface AttackSummary {
  run_id: string;
  scenario: string;
  n: number;
  delay_ms: number;
  trials: number;
  trials_with_violation: number;
  races_observed: number;
  per_invariant: Record<string, number>;
  invariants_used?: string[];
  human_approved?: boolean;
}

export interface AttackResponse {
  run_id: string;
  summary: AttackSummary;
  first_failing_trial: TrialResult | null;
}

export interface FreshTrials {
  delay_ms: number;
  trials: number;
  violations: number;
  invariants: string[];
}

export interface Validation {
  regression_failures: string[];
  replay?: { trials: number; violations: number; invariants: string[] };
  fresh_trials?: FreshTrials[];
  throughput_rps?: number;
}

export interface RepairAttempt {
  attempt: number;
  strategy?: string;
  explanation?: string;
  patch?: { file: string; function: string; code: string };
  validation?: Validation;
  accepted: boolean;
  reason?: string;
}

export interface RepairResponse {
  attempts: RepairAttempt[];
  accepted: boolean;
  negative_control: { buggy_code_accepted: boolean; validator_working: boolean; reason: string };
  evidence: TrialResult;
  human_approved_invariants?: boolean;
}

export interface RunResponse {
  summary: Partial<AttackSummary>;
  failing_trials: TrialResult[];
}
