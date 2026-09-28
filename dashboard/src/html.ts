/**
 * Escaping and formatting helpers shared by the four views.
 *
 * Kept separate so each view module stays a pure render function and nothing
 * here can grow a dependency on a status source (AD-24 (d) scans this file
 * too): these are string utilities only.
 */

/** Escape text for interpolation into HTML. */
export function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Render a `<th>`/`<td>` table body from rows of already-escaped cells. */
export function table(headers: string[], rows: string[][]): string {
  const head = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows
    .map((cells) => `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/** `sha256:abc…` → `abc…` shortened for a table cell, with the full value as a title. */
export function shortHash(hash: string, length = 12): string {
  if (!hash) return "—";
  const digest = hash.includes(":") ? hash.slice(hash.indexOf(":") + 1) : hash;
  const shown = digest.slice(0, length);
  return `<span title="${escapeHtml(hash)}" class="hash">${escapeHtml(shown)}…</span>`;
}

/** A count with a zero/orange/green tone class, for pass/fail cells. */
export function toneClass(value: number, tone: "good" | "bad"): string {
  if (value === 0) return "num zero";
  return tone === "good" ? "num good" : "num bad";
}
