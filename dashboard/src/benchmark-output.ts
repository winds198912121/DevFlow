/**
 * Benchmark-output view (surface 4 of 4) — FR-21.
 *
 * Pure: a function of the `/bench/{step}` payload.
 *
 * Ticket 4.7's verify line requires this view to render the same
 * recommendation, metric and contributing runs the endpoint returned. That is
 * why the render function takes the payload verbatim and prints its fields
 * rather than summarizing: a summarizing view could agree with the endpoint by
 * coincidence while dropping a contributing run.
 */

import type { BenchOutput, ContributingRun } from "./api";
import { escapeHtml, shortHash, table } from "./html";

function contributorRow(run: ContributingRun): string[] {
  return [
    escapeHtml(run.run_event_id),
    escapeHtml(run.run_id ?? "—"),
    shortHash(run.executor_tuple_hash),
  ];
}

export function renderBenchmarkOutput(output: BenchOutput): string {
  const rows = output.contributing_runs.map(contributorRow);
  return `
<section class="view view-benchmark-output">
  <h2>Benchmark output</h2>
  <p class="meta">
    <strong>${escapeHtml(output.step)}</strong>
    <span class="badge">tier ${escapeHtml(output.project_size_tier)}</span>
    <span class="badge">contract ${escapeHtml(output.artifact_contract_version)}</span>
  </p>
  ${table(["Recommendation", "Metric", "Value", "Contributing runs"], [[
    escapeHtml(output.metric_definition),
    escapeHtml(output.metric_definition),
    `<span class="num">${escapeHtml(output.metric_summary)}</span>`,
    `<span class="num">${output.contributing_runs.length}</span>`,
  ]])}
  <h3>Contributing comparable runs</h3>
  ${table(["Run event", "Run", "Executor tuple hash"], rows)}
</section>`.trim();
}
