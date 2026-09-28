/**
 * Dashboard shell — owns requests and mounts the four pure views.
 *
 * Every view is a pure function of an API payload (`renderX(payload)`); this
 * module is the only place that fetches, holds state, or touches the DOM. The
 * one piece of state it keeps is the error view's pagination cursor, which
 * AD-13 allows ("no client-side state beyond pagination").
 */

import { ApiRefusal, httpApi, type DashboardApi } from "./api";
import { FILTER_FIELDS, renderErrorStore } from "./error-store";
import { renderBenchmarkOutput } from "./benchmark-output";
import { renderRegressionDiff } from "./regression-diff";
import { renderRunStatus } from "./run-status";

const TAB = {
  runStatus: "run-status",
  errorStore: "error-store",
  regressionDiff: "regression-diff",
  benchmarkOutput: "benchmark-output",
} as const;

type Tab = (typeof TAB)[keyof typeof TAB];

interface ShellState {
  tab: Tab;
  pageIndex: number;
}

/**
 * Every element id the shell looks up, derived from the same constants the
 * wiring uses so the list cannot drift from the lookups.
 *
 * `mount` verifies all of these exist before binding anything. Without that,
 * a renamed input surfaced as a per-tab "missing element" error only when the
 * operator happened to open that tab — which is exactly how the filter inputs
 * were first broken.
 */
export const REQUIRED_ELEMENTS: readonly string[] = [
  "surface",
  "refresh",
  "page-prev",
  "page-next",
  ...Object.values(TAB).map((tab) => `tab-${tab}`),
  "input-project_id",
  "input-run_id",
  "input-bump_id",
  "input-step",
  "input-tier",
  "input-contract",
  ...FILTER_FIELDS.map((f) => `input-filter-${f.key}`),
];

export function mount(api: DashboardApi, root: HTMLElement): void {
  void root;
  const state: ShellState = { tab: TAB.runStatus, pageIndex: 0 };

  const el = (id: string): HTMLElement => {
    const found = document.getElementById(id);
    if (!found) throw new Error(`missing element #${id}`);
    return found;
  };

  const missing = REQUIRED_ELEMENTS.filter((id) => !document.getElementById(id));
  if (missing.length > 0) {
    throw new Error(`dashboard shell is missing element(s): ${missing.join(", ")}`);
  }

  function field(name: string): string {
    const input = el(`input-${name}`);
    if (input instanceof HTMLInputElement) return input.value;
    return "";
  }

  function show(html: string): void {
    el("surface").innerHTML = html;
  }

  function showError(error: unknown): void {
    const code = error instanceof ApiRefusal ? error.code : "unexpected_error";
    const message = error instanceof Error ? error.message : String(error);
    show(
      `<section class="view"><h2>${code}</h2><p class="meta">${message}</p></section>`,
    );
  }

  async function refresh(): Promise<void> {
    const projectId = field("project_id");
    const runId = field("run_id");
    const bumpId = field("bump_id");
    const step = field("step") || "coding";
    try {
      switch (state.tab) {
        case TAB.runStatus:
          show(renderRunStatus(await api.getRun(runId, projectId || undefined)));
          break;
        case TAB.errorStore: {
          const filters: Record<string, string> = {};
          for (const { key } of FILTER_FIELDS) {
            const value = field(`filter-${key}`);
            if (value) filters[key] = value;
          }
          show(renderErrorStore(await api.listErrors(projectId, filters), state.pageIndex));
          break;
        }
        case TAB.regressionDiff:
          show(renderRegressionDiff(await api.getRegressionDiff(projectId, bumpId)));
          break;
        case TAB.benchmarkOutput:
          show(renderBenchmarkOutput(await api.getBench(step, field("tier") || "epic",
            field("contract") || undefined)));
          break;
      }
    } catch (error) {
      showError(error);
    }
  }

  for (const tab of Object.values(TAB)) {
    el(`tab-${tab}`).addEventListener("click", () => {
      state.tab = tab;
      state.pageIndex = 0;
      void refresh();
    });
  }
  el("refresh").addEventListener("click", () => void refresh());
  el("page-prev").addEventListener("click", () => {
    state.pageIndex = Math.max(0, state.pageIndex - 1);
    void refresh();
  });
  el("page-next").addEventListener("click", () => {
    state.pageIndex += 1;
    void refresh();
  });

  void refresh();
}

if (typeof document !== "undefined") {
  const root = document.getElementById("app");
  if (root) mount(httpApi(""), root);
}
