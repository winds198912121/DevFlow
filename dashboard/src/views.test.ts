/**
 * View tests — Story 4.4.
 *
 * Each view is a pure function of one API payload, so these tests are the
 * "renders the same" half of the Story 4.6 / 4.7 verify lines: given the exact
 * JSON the endpoint returns, the view must show those values.
 *
 * Run with `bun test` (wired into the Python suite by
 * `tests/test_dashboard_spa.py` so one `uv run pytest` covers both halves).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { ApiRefusal, httpApi } from "./api";
import type {
  BenchOutput,
  ErrorPage,
  RegressionDiff,
  RunDetail,
} from "./api";
import { PAGE_SIZE, paginate, renderErrorStore } from "./error-store";
import { escapeHtml, shortHash } from "./html";
import { renderBenchmarkOutput } from "./benchmark-output";
import { renderRegressionDiff } from "./regression-diff";
import { renderRunStatus } from "./run-status";

const RUN_DETAIL: RunDetail = {
  project_id: "python-hello",
  run_id: "R1",
  size: "epic",
  steps: [
    { step: "research", terminal: "Locked", gate_mode: "enforced" },
    { step: "design", terminal: "Pending", gate_mode: "enforced" },
    { step: "coding", terminal: "Failed", gate_mode: "enforced" },
    { step: "testing", terminal: "Done", gate_mode: "skipped" },
  ],
};

const ERROR_PAGE: ErrorPage = {
  project_id: "python-hello",
  count: 2,
  filters: { step: "coding" },
  errors: [
    {
      record_id: "01HREC1",
      project_id: "python-hello",
      run_id: "R1",
      step: "coding",
      attempt: 1,
      category: "coding",
      root_cause: ["assertion failed"],
      correction: [],
      retry: [],
      result: "fail",
      recorded_at: "2026-01-01T00:00:00+00:00",
      hash: "sha256:abc",
    },
    {
      record_id: "01HREC2",
      project_id: "python-hello",
      run_id: "R2",
      step: "coding",
      attempt: 2,
      category: "llm",
      root_cause: ["timeout"],
      correction: [],
      retry: [],
      result: "error",
      recorded_at: "2026-01-02T00:00:00+00:00",
      hash: "sha256:def",
    },
  ],
};

const REGRESSION_DIFF: RegressionDiff = {
  project_id: "python-hello",
  bump_id: "01HBUMP",
  skill_name: "bmad-build",
  new_version: "2.0",
  previous_version: "1.0",
  state: "pending_promotion",
  regression_run_id: "REGRUN",
  comparable: false,
  steps: [
    {
      step: "coding", passed: 2, failed: 1, skipped: 0, total: 3,
      comparable: true, non_comparable_reason: null,
    },
    {
      step: "testing", passed: 0, failed: 1, skipped: 0, total: 1,
      comparable: false, non_comparable_reason: "insufficient_comparable_runs_at_tier:epic",
    },
  ],
};

const BENCH: BenchOutput = {
  step: "coding",
  project_size_tier: "trivial",
  artifact_contract_version: "v1",
  metric_definition: "pass_rate",
  metric_summary: 0.915,
  contributing_runs: [
    { run_event_id: "01HRUN1", run_id: "R1", executor_tuple_hash: "sha256:aaa", outcome: "pass" },
    { run_event_id: "01HRUN2", run_id: "R2", executor_tuple_hash: "sha256:bbb", outcome: "pass" },
    { run_event_id: "01HRUN3", run_id: "R3", executor_tuple_hash: "sha256:ccc", outcome: "pass" },
    { run_event_id: "01HRUN4", run_id: "R4", executor_tuple_hash: "sha256:ddd", outcome: "pass" },
  ],
};

describe("run-status view", () => {
  test("renders every step's terminal status verbatim", () => {
    const html = renderRunStatus(RUN_DETAIL);
    for (const status of RUN_DETAIL.steps) {
      expect(html).toContain(status.step);
      expect(html).toContain(status.terminal);
    }
    expect(html).toContain("python-hello");
    expect(html).toContain("R1");
    expect(html).toContain("epic");
  });

  test("does not invent a status the payload did not contain", () => {
    const html = renderRunStatus({ ...RUN_DETAIL, steps: [
      { step: "research", terminal: "Pending", gate_mode: "enforced" },
    ] });
    expect(html).not.toContain("Locked");
    expect(html).not.toContain("Failed");
  });
});

describe("error-store view", () => {
  test("renders the count, the applied filters and every record", () => {
    const html = renderErrorStore(ERROR_PAGE);
    expect(html).toContain("2 error(s)");
    expect(html).toContain("step=coding");
    for (const record of ERROR_PAGE.errors) {
      expect(html).toContain(record.record_id);
    }
  });

  test("says so when no errors match instead of rendering an empty table", () => {
    const html = renderErrorStore({ ...ERROR_PAGE, count: 0, errors: [] });
    expect(html).toContain("No errors match these filters.");
    expect(html).not.toContain("<table>");
  });

  test("paginate clamps the cursor into range", () => {
    const records = ERROR_PAGE.errors;
    expect(paginate(records, 0).pageCount).toBe(1);
    // A cursor past the end clamps rather than returning an empty slice.
    expect(paginate(records, 99).pageIndex).toBe(0);
    expect(paginate(records, -5).pageIndex).toBe(0);
    expect(paginate(records, 0).slice).toHaveLength(2);
  });

  test("renders only one page of a long result set", () => {
    const many = Array.from({ length: PAGE_SIZE + 5 }, (_, i) => ({
      ...ERROR_PAGE.errors[0]!,
      record_id: `01HREC${i}`,
    }));
    const html = renderErrorStore({ ...ERROR_PAGE, count: many.length, errors: many }, 0);
    expect(html).toContain("01HREC0");
    expect(html).not.toContain(`01HREC${PAGE_SIZE}`);
    expect(html).toContain("Page 1 / 2");
    const second = renderErrorStore({ ...ERROR_PAGE, count: many.length, errors: many }, 1);
    expect(second).toContain(`01HREC${PAGE_SIZE}`);
  });
});

describe("regression-diff view", () => {
  test("renders per-step pass/fail counts from the payload", () => {
    const html = renderRegressionDiff(REGRESSION_DIFF);
    expect(html).toContain("bmad-build");
    expect(html).toContain("1.0");
    expect(html).toContain("2.0");
    expect(html).toContain("coding");
    expect(html).toContain("testing");
  });

  test("flags a non-comparable step and shows the backend's reason", () => {
    const html = renderRegressionDiff(REGRESSION_DIFF);
    expect(html).toContain("not comparable");
    expect(html).toContain("insufficient_comparable_runs_at_tier:epic");
    expect(html).toContain("comparable");
  });

  test("says so when the bump has no regression run yet", () => {
    const html = renderRegressionDiff({
      ...REGRESSION_DIFF, steps: [], regression_run_id: null,
    });
    expect(html).toContain("No regression run recorded for this bump yet.");
  });
});

describe("benchmark-output view", () => {
  test("renders the same recommendation, metric and contributing runs", () => {
    const html = renderBenchmarkOutput(BENCH);
    expect(html).toContain(BENCH.metric_definition);
    expect(html).toContain(String(BENCH.metric_summary));
    expect(html).toContain(BENCH.project_size_tier);
    expect(html).toContain(BENCH.artifact_contract_version);
    // Every contributing run must appear: dropping one would make the view
    // disagree with the endpoint while still looking plausible.
    for (const run of BENCH.contributing_runs) {
      expect(html).toContain(run.run_event_id);
    }
    expect(html).toContain("4");
  });

  test("renders the full contributing-run count, not just the visible page", () => {
    const html = renderBenchmarkOutput(BENCH);
    expect(html.match(/01HRUN\d/g)).toHaveLength(BENCH.contributing_runs.length);
  });
});

describe("escaping", () => {
  test("a root cause containing markup is escaped, not injected", () => {
    const html = renderErrorStore({
      ...ERROR_PAGE,
      count: 1,
      errors: [{ ...ERROR_PAGE.errors[0]!, root_cause: ['<script>alert("x")</script>'] }],
    });
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  test("shortHash abbreviates the digest but keeps the full value reachable", () => {
    const html = shortHash("sha256:" + "a".repeat(64), 8);
    expect(html).toContain("aaaaaaaa…");
    expect(html).toContain("sha256:" + "a".repeat(64));
    expect(shortHash("")).toBe("—");
  });

  test("escapeHtml covers the five significant characters", () => {
    expect(escapeHtml(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
  });
});

describe("api client", () => {
  const realFetch = globalThis.fetch;

  /** Install a stub fetch. Double-cast once here: the stub omits `preconnect`. */
  function setFetch(handler: (url: string) => Promise<Response>): void {
    globalThis.fetch = handler as unknown as typeof fetch;
  }

  function mockFetch(status: number, body: unknown): void {
    setFetch(() =>
      Promise.resolve(new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      })));
  }

  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  test("a 409 refusal surfaces the harness error code", async () => {
    mockFetch(409, { error: "regression_set_insufficient", message: "needs k=3" });
    const failure = await httpApi("").getBench("coding", "trivial").catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiRefusal);
    expect((failure as ApiRefusal).code).toBe("regression_set_insufficient");
    expect((failure as ApiRefusal).status).toBe(409);
  });

  test("a non-JSON error body still yields a refusal, not a crash", async () => {
    setFetch(() => Promise.resolve(new Response("<html>oops</html>", { status: 500 })));
    const failure = await httpApi("").listRuns().catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiRefusal);
    expect((failure as ApiRefusal).code).toBe("request_failed");
  });

  test("undefined and empty filters are omitted from the query string", async () => {
    let seen = "";
    setFetch((url: string) => {
      seen = url;
      return Promise.resolve(new Response(JSON.stringify(
        { project_id: "p", count: 0, filters: {}, errors: [] },
      ), { status: 200, headers: { "content-type": "application/json" } }));
    });
    await httpApi("").listErrors("p", {
      step: "coding",
      category: "",
      since: undefined as unknown as string,
    });
    expect(seen).toContain("step=coding");
    expect(seen).not.toContain("category=");
    expect(seen).not.toContain("since=");
  });
});
