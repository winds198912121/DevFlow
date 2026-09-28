/**
 * Error-store view (surface 2 of 4) — FR-25.
 *
 * Pure, apart from pagination: `renderErrorStore(page, pageIndex, pageSize)` is
 * a function of the `/projects/{id}/errors` payload plus the page cursor. The
 * cursor is the only client-side state the AD-13 read model permits, because it
 * changes which slice of an already-fetched projection is shown and nothing
 * about the projection itself.
 */

import type { ErrorPage, ErrorRecord } from "./api";
import { escapeHtml, table } from "./html";

export const PAGE_SIZE = 25;

/** The filters this view offers, in the order the backend documents them. */
export const FILTER_FIELDS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "run_id", label: "Run" },
  { key: "step", label: "Step" },
  { key: "category", label: "Category" },
  { key: "executor_tuple", label: "Executor tuple" },
  { key: "since", label: "Since (ISO 8601)" },
  { key: "until", label: "Until (ISO 8601)" },
];

export function paginate(records: ErrorRecord[], pageIndex: number, pageSize = PAGE_SIZE): {
  slice: ErrorRecord[];
  pageIndex: number;
  pageCount: number;
} {
  const pageCount = Math.max(1, Math.ceil(records.length / pageSize));
  const clamped = Math.min(Math.max(pageIndex, 0), pageCount - 1);
  return {
    slice: records.slice(clamped * pageSize, (clamped + 1) * pageSize),
    pageIndex: clamped,
    pageCount,
  };
}

export function renderErrorStore(page: ErrorPage, pageIndex = 0, pageSize = PAGE_SIZE): string {
  const { slice, pageIndex: current, pageCount } = paginate(page.errors, pageIndex, pageSize);
  const applied = Object.entries(page.filters)
    .map(([k, v]) => `<span class="chip">${escapeHtml(k)}=${escapeHtml(v)}</span>`)
    .join(" ");

  const rows = slice.map((record) => [
    escapeHtml(record.record_id),
    escapeHtml(record.run_id),
    escapeHtml(record.step),
    `<span class="pill">${escapeHtml(record.category)}</span>`,
    String(record.attempt),
    escapeHtml(record.recorded_at),
    escapeHtml(record.root_cause.join("; ")),
  ]);

  return `
<section class="view view-error-store">
  <h2>Error store</h2>
  <p class="meta">
    <strong>${escapeHtml(page.project_id)}</strong>
    <span class="badge">${page.count} error(s)</span>
    ${applied || '<span class="chip muted">no filters</span>'}
  </p>
  ${
    page.errors.length === 0
      ? '<p class="empty">No errors match these filters.</p>'
      : table(["Record", "Run", "Step", "Category", "Attempt", "Recorded", "Root cause"], rows)
  }
  <p class="pager">
    Page ${current + 1} / ${pageCount}
  </p>
</section>`.trim();
}
