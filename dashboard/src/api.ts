/**
 * Dashboard API client and payload types.
 *
 * This module is the SPA's single boundary to the backend. The four view
 * modules import their types from here and must not reach past it: AD-24 (d)
 * fails any view that resolves a different terminal-status source, and
 * `tools/check_terminal_status.py` encodes exactly that by treating this file
 * as the one place the raw status vocabulary may be named.
 *
 * Everything here is a type plus one factory, so the views stay pure and
 * testable against a literal payload with no HTTP involved.
 */

/** The AD-24 resolver's output. `terminal` is never computed client-side. */
export type TerminalStatus = "Done" | "Locked" | "Pending" | "Failed";
export type GateMode = "enforced" | "skipped";

export interface StepStatus {
  step: string;
  terminal: TerminalStatus;
  gate_mode: GateMode;
}

export interface RunSummary {
  project_id: string;
  run_id: string;
  steps: StepStatus[];
}

export interface RunDetail extends RunSummary {
  size: string;
}

export interface RunList {
  runs: RunSummary[];
}

export interface ErrorRecord {
  record_id: string;
  project_id: string;
  run_id: string;
  step: string;
  attempt: number;
  category: string;
  root_cause: string[];
  correction: string[];
  retry: Record<string, unknown>[];
  result: string;
  recorded_at: string;
  hash: string;
}

export interface ErrorPage {
  project_id: string;
  count: number;
  filters: Record<string, string>;
  errors: ErrorRecord[];
}

export interface RegressionDiffStep {
  step: string;
  passed: number;
  failed: number;
  skipped: number;
  total: number;
  comparable: boolean;
  non_comparable_reason: string | null;
}

export interface RegressionDiff {
  project_id: string;
  bump_id: string;
  skill_name: string;
  new_version: string;
  previous_version: string;
  state: string;
  regression_run_id: string | null;
  comparable: boolean;
  steps: RegressionDiffStep[];
}

export interface ContributingRun {
  run_event_id: string;
  run_id: string | null;
  executor_tuple_hash: string;
  outcome: string | null;
}

export interface BenchOutput {
  step: string;
  project_size_tier: string;
  artifact_contract_version: string;
  metric_definition: string;
  metric_summary: number;
  contributing_runs: ContributingRun[];
}

/** A refusal from the backend, carrying the harness error code. */
export class ApiRefusal extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message || code);
    this.name = "ApiRefusal";
  }
}

export interface DashboardApi {
  listRuns(): Promise<RunList>;
  getRun(runId: string, projectId?: string): Promise<RunDetail>;
  listErrors(projectId: string, filters: Record<string, string>): Promise<ErrorPage>;
  getRegressionDiff(projectId: string, bumpId: string): Promise<RegressionDiff>;
  getBench(step: string, tier: string, contract?: string): Promise<BenchOutput>;
}

/** The read endpoints this client uses. Writes are operator actions, not views. */
export function httpApi(baseUrl = ""): DashboardApi {
  async function get<T>(path: string, params: Record<string, string | undefined> = {}): Promise<T> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") query.set(key, value);
    }
    const suffix = query.toString() ? `?${query}` : "";
    const response = await fetch(`${baseUrl}${path}${suffix}`);
    const body: unknown = await response.json().catch(() => undefined);
    if (!response.ok) throw refusalFrom(body, response.status);
    // The harness backend is the sole producer of these payloads, and each
    // view's render test pins the shape it consumes. A per-field validator
    // here would restate harness/dashboard_service.py's contract without
    // buying a runtime guarantee the views actually use.
    const payload = body as T;
    return payload;
  }

  return {
    listRuns: () => get<RunList>("/runs"),
    getRun: (runId, projectId) => get<RunDetail>(`/runs/${encodeURIComponent(runId)}`, {
      project_id: projectId,
    }),
    listErrors: (projectId, filters) =>
      get<ErrorPage>(`/projects/${encodeURIComponent(projectId)}/errors`, filters),
    getRegressionDiff: (projectId, bumpId) =>
      get<RegressionDiff>(
        `/projects/${encodeURIComponent(projectId)}/regression-diff/${encodeURIComponent(bumpId)}`,
      ),
    getBench: (step, tier, contract) =>
      get<BenchOutput>(`/bench/${encodeURIComponent(step)}`, { tier, contract }),
  };
}

/** Narrow the refusal envelope (`{error, message}`) without trusting it. */
function refusalFrom(body: unknown, status: number): ApiRefusal {
  if (body !== null && typeof body === "object" && "error" in body && typeof body.error === "string") {
    const message = "message" in body && typeof body.message === "string" ? body.message : "";
    return new ApiRefusal(body.error, status, message);
  }
  return new ApiRefusal("request_failed", status, "");
}
