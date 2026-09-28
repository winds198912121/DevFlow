/**
 * Run-status view (surface 1 of 4).
 *
 * Pure: `renderRunStatus(detail)` is a function of the `/runs/{id}` payload
 * alone — no module state, no fetching, no clock. The caller owns the request
 * and the snapshot time, which is what makes the view reproducible in a test.
 *
 * The step terminal status is printed exactly as the backend returned it. This
 * view never inspects the fields AD-24 (c) resolves from, so it cannot arrive
 * at a different answer than the resolver (AD-24 (b), enforced by
 * `tools/check_terminal_status.py`).
 */

import type { RunDetail, StepStatus } from "./api";
import { escapeHtml, table } from "./html";

/** CSS tone per terminal status. A presentation map, not a status decision. */
const TONE: Record<StepStatus["terminal"], string> = {
  Done: "tone-done",
  Locked: "tone-locked",
  Pending: "tone-pending",
  Failed: "tone-failed",
};

export function renderRunStatus(detail: RunDetail): string {
  const rows = detail.steps.map((status) => [
    escapeHtml(status.step),
    `<span class="pill ${TONE[status.terminal]}">${escapeHtml(status.terminal)}</span>`,
    escapeHtml(status.gate_mode),
  ]);
  return `
<section class="view view-run-status">
  <h2>Run status</h2>
  <p class="meta">
    <strong>${escapeHtml(detail.project_id)}</strong> / ${escapeHtml(detail.run_id)}
    <span class="badge">${escapeHtml(detail.size)}</span>
  </p>
  ${table(["Step", "Terminal", "Gate"], rows)}
  <p class="legend">
    Terminal status is resolved once, server-side (AD-24); this view only renders it.
  </p>
</section>`.trim();
}
