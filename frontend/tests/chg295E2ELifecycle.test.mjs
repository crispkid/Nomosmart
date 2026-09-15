import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createRunManifestPath, runWithCleanup } from "./e2eRunLifecycle.mjs";

const exec = promisify(execFile);
const helper = fileURLToPath(new URL("../../backend/scripts/e2e_governance_fixture.py", import.meta.url));
const python = process.env.E2E_PYTHON || fileURLToPath(new URL("../../backend/.venv/bin/python", import.meta.url));
const baseEnv = { PATH: process.env.PATH, HOME: process.env.HOME, PYTHONDONTWRITEBYTECODE: "1",
  E2E_ISOLATION: "fresh-disposable", E2E_WRITERS_QUIESCED: "1" };

async function command(path, action, env = baseEnv) {
  let stdout;
  try { ({ stdout } = await exec(python, [helper, action, "--manifest", path], { env, timeout: 30_000 })); }
  catch (error) {
    const result = JSON.parse(error.stdout.trim());
    const failure = new Error(result.reason || result.code);
    failure.code = result.code;
    throw failure;
  }
  return JSON.parse(stdout.trim());
}

test("real blocked setup still cleans its receipt without fabricating generation", async () => {
  const path = await createRunManifestPath();
  await assert.rejects(runWithCleanup({
    setup: async () => { await command(path, "init"); return command(path, "setup"); },
    execute: async () => { await exec("/missing-chg295-execution-must-not-start", []); },
    close: async () => {},
    cleanup: () => command(path, "cleanup")
  }), error => error.code === "E2E_BLOCKED" && error.cleanupErrors.length === 0);
  const receipt = JSON.parse(await readFile(path));
  assert.equal(receipt.state, "cleanup_complete");
  assert.equal(receipt.resources.length, 0);
});

test("real helper refusal preserves both original blocked setup and cleanup failure", async () => {
  const path = await createRunManifestPath();
  await assert.rejects(runWithCleanup({
    setup: async () => { await command(path, "init"); return command(path, "setup"); },
    execute: async () => { await exec("/missing-chg295-execution-must-not-start", []); },
    close: async () => {},
    cleanup: () => command(path, "cleanup", { ...baseEnv, E2E_WRITERS_QUIESCED: "0" })
  }), error => error.code === "E2E_CLEANUP_FAILED" && error.primaryCode === "E2E_BLOCKED"
      && error.cleanupErrors[0].code === "exclusive_disposable_writers_required");
  assert.equal(JSON.parse(await readFile(path)).state, "preparing");
  assert.equal((await command(path, "cleanup")).status, "cleanup_complete");
});

test("real process launch and close failures do not suppress cleanup (not browser acceptance)", async () => {
  const path = await createRunManifestPath();
  await assert.rejects(runWithCleanup({
    setup: () => command(path, "init"),
    execute: () => exec("/nonexistent-chg295-launch", []),
    close: () => exec("/nonexistent-chg295-close", []),
    cleanup: () => command(path, "cleanup")
  }), error => error.primaryCode === "ENOENT" && error.cleanupErrors[0].phase === "browser_close");
  assert.equal(JSON.parse(await readFile(path)).state, "cleanup_complete");
});

test("legacy cleanup with project ID but no receipt is denied by the actual CLI", async () => {
  await assert.rejects(exec(python, [helper, "cleanup", "--project-id", "00000000-0000-0000-0000-000000000001"],
    { env: baseEnv, timeout: 30_000 }), error => error.code === 2 && /--manifest/.test(error.stderr));
});
