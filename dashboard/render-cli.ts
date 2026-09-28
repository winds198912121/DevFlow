/**
 * Verification CLI: render one view from a JSON payload on stdin.
 *
 * Exists so the Python suite can close the loop between the two halves of the
 * dashboard: seed the stores, call the real endpoint, pipe its JSON here, and
 * assert the rendered HTML shows the endpoint's values. That is stronger than
 * asserting a view against a hand-written fixture, because it fails if the
 * endpoint and the view ever drift apart.
 *
 *   echo '{"runs":[]}' | bun run render-cli.ts run-status
 *
 * Not reachable from `src/main.ts`, so the bundler never ships it.
 */

import { renderBenchmarkOutput } from "./src/benchmark-output";
import { renderErrorStore } from "./src/error-store";
import { renderRegressionDiff } from "./src/regression-diff";
import { renderRunStatus } from "./src/run-status";

const views: Record<string, (payload: never) => string> = {
  "run-status": renderRunStatus as (payload: never) => string,
  "error-store": renderErrorStore as (payload: never) => string,
  "regression-diff": renderRegressionDiff as (payload: never) => string,
  "benchmark-output": renderBenchmarkOutput as (payload: never) => string,
};

const view = process.argv[2];
if (!view) {
  console.error(`usage: bun run render-cli.ts <${Object.keys(views).join("|")}>`);
  process.exit(2);
}
const render = views[view];
if (!render) {
  console.error(`unknown view: ${view}`);
  process.exit(2);
}

process.stdout.write(render(await Bun.stdin.json()));
