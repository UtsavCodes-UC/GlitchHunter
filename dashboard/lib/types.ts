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
  initial_tables?: Record<string, unknown[]>;   // uploaded projects: every table before and after the try
  final_tables?: Record<string, unknown[]>;
  violations: Record<string, unknown[][] | null>;
}

export interface Scenario {
  id: string;
  title?: string | null;     // set for uploaded apps
  custom?: boolean;          // true for uploaded apps ("Try your own app")
  race_n?: number | null;    // simultaneous requests per try
  burst?: Record<string, unknown>[] | null;   // uploaded projects: the requests sent together in one try
  endpoint: { method: string; path: string; params: Record<string, number | string>; path_params?: Record<string, unknown>; json?: unknown; header_names?: string[] };
  invariants: number;
  rules_approved?: number;   // checks a person approved
  failing_runs?: number;     // failing tries found in saved attacks on this machine
  fixes_accepted?: number;   // accepted fixes in saved repairs on this machine
}

export type Verdict = "suspect" | "guarded" | "writes" | "read-only";

export interface ScanRoute {
  method: string;
  path: string;               // full path with router prefixes
  function: string;
  file: string;
  lineno: number;
  is_async: boolean;
  app: string | null;         // "pkg.module:attr" of the app that serves it
  verdict: Verdict;           // a hint from code patterns, never a proof
  reasons: string[];
  path_params: string[];
  body: Record<string, unknown> | null;
  query: Record<string, unknown>;
  sample: Record<string, unknown>;
}

export interface Setup {
  app: string;
  file: string;
  func: string;
  method: string;
  path: string;
  body: "json" | "query";
  burst: Record<string, unknown>[];
  schema_sql: string;
  seed_sql: string;
  db_env: string;
  env: Record<string, string>;
  headers?: Record<string, string>;
  db_scheme?: string;
  pause_ms?: number;
}

export interface UploadSummary {
  id: string;
  name: string;
  created: number;
  endpoints: number;
  risky: number;
  status: "needs setup" | "set up";
  files: string[];
  skipped: number;
  config: Setup | null;
}

export interface UploadDetail extends UploadSummary {
  scan: {
    apps: { spec: string; file: string; routes: number }[];
    routes: ScanRoute[];
    db_env: { guess: string; found: string[]; env: Record<string, string> };
    schema_sql: string; seed_sql: string; schema_source: string | null;
    warnings: string[]; py_files: number; risky: number;
  };
  suggested: Setup | null;
}

export interface Job {
  id: string;
  status: "running" | "done" | "error";
  log: { t: number; msg: string }[];
  result: { verdict: "ok" | "warning" | "server error" | "setup error"; message: string; statuses?: number[]; initial_tables?: Record<string, unknown[]>; final_tables?: Record<string, unknown[]> } | null;
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
