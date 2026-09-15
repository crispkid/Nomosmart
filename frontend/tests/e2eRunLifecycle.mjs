import { mkdtemp, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export async function createRunManifestPath() {
  // realpath avoids macOS /var -> /private/var symlink ambiguity; mkdtemp is 0700.
  const directory = await mkdtemp(join(await realpath(tmpdir()), "nomosmart-e2e-"));
  return join(directory, "run.json");
}

export async function runWithCleanup({ setup, execute, close, cleanup }) {
  let primary;
  const secondary = [];
  try {
    const fixture = await setup();
    await execute(fixture);
  } catch (error) {
    primary = error;
  } finally {
    // Browser startup can fail without a handle. A close error never suppresses
    // cleanup; a cleanup error never replaces the setup/product failure.
    for (const [phase, action] of [["browser_close", close], ["cleanup", cleanup]]) {
      try { await action(); }
      catch (error) { secondary.push({ phase, code: error.code || "E2E_LIFECYCLE_FAILURE" }); }
    }
  }
  if (primary || secondary.length) {
    const error = new Error(primary?.message || "E2E cleanup or browser close failed", { cause: primary });
    error.primaryCode = primary?.code || (primary ? "E2E_FAILURE" : null);
    // A blocked product run with failed cleanup is a failure, not only blocked.
    error.code = secondary.length ? "E2E_CLEANUP_FAILED" : error.primaryCode;
    error.cleanupErrors = secondary;
    throw error;
  }
}
