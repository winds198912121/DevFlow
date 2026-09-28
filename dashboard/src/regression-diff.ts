/**
 * Regression-diff view (surface 3 of 4) — FR-18.
 *
 * Pure: a function of the `/projects/{id}/regression-diff/{bump_id}` payload.
 *
 * FR-18's "non-comparable" flag is decided by the backend (it owns the
 * regression set's comparable keys); this view only renders the flag and the
 * reason it was given. Deciding comparability here would duplicate the
 * benchmark's rule and let the two disagree.
 */

import type { RegressionDiff, RegressionDiffStep } from "./api";
import { escapeHtml, table, toneClass } from "./html";

function stepRow(step: RegressionDiffStep): string[] {
  const flag = step.comparable
    ? '<span class="pill tone-done">comparable</span>'
    : `<span class="pill tone-failed" title="${escapeHtml(step.non_comparable_reason ?? "")}">not comparable</span>`;
  return [
    escapeHtml(step.step),
    `<span class="${toneClass(step.passed, "good")}">${step.passed}</span>`,
    `<span class="${toneClass(step.failed, "bad")}">${step.failed}</span>`,
    String(step.skipped),
    String(step.total),
    flag,
  ];
}

export function renderRegressionDiff(diff: RegressionDiff): string {
  const rows = diff.steps.map(stepRow);
  return `
<section class="view view-regression-diff">
  <h2>Regression diff</h2>
  <p class="meta">
    <strong>${escapeHtml(diff.skill_name)}</strong>
    <span class="badge">${escapeHtml(diff.previous_version)} → ${escapeHtml(diff.new_version)}</span>
    <span class="badge">${escapeHtml(diff.state)}</span>
    <span class="badge">run ${escapeHtml(diff.regression_run_id ?? "—")}</span>
  </p>
  ${
    diff.steps.length === 0
      ? '<p class="empty">No regression run recorded for this bump yet.</p>'
      : table(["Step", "Passed", "Failed", "Skipped", "Total", "Comparability"], rows)
  }
  <p class="legend">
    ${diff.comparable
      ? "Every step has at least one comparable run in its cell."
      : "One or more steps have no comparable run in their (tier, contract) cell (FR-18)."}
  </p>
</section>`.trim();
}
