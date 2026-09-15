// CHG-294 R2 only. Real Docker isolation/negative checks; no application deployment.
// Run with NOMOSMART_IMAGE_SMOKE_SCOPE=CHG-294-R2 and no arguments.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

assert.equal(process.argv.length, 2, "No options accepted");
assert.equal(process.env.NOMOSMART_IMAGE_SMOKE_SCOPE, "CHG-294-R2");
const image = "sha256:2c65c3eab7f7601612297a6c1ec11f8445ac0b2c174c18f4076cf98c2a70eb9d";
const oldImage = "sha256:5281abacf6c0ba6fc07c757325aebf9ba9b964ca2eb8ce4f68bd664c36683655";
const script = readFileSync(new URL("./chg294-image-smoke.mjs", import.meta.url), "utf8");
const run = `chg294-r2-verify-${randomUUID().slice(0, 8)}`;
const label = "nomosmart.chg294-verification-run";
const containers = [];
let network;
const results = [];
const tmpfs = {
  "/tmp": "rw,nosuid,nodev,mode=1777,size=64m",
  "/app/public/__chg294-smoke": "rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=16m",
  "/app/.next/cache": "rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=64m",
};

function docker(args, input) {
  const result = spawnSync("docker", ["--context", "desktop-linux", ...args], {
    encoding: "utf8", input, timeout: 60000, maxBuffer: 2 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  return result;
}
function checked(args, input) {
  const result = docker(args, input);
  assert.equal(result.status, 0, `${args[0]} failed: ${result.stderr.slice(-3000)}`);
  return result.stdout.trim();
}
function inspect(kind, id) {
  return JSON.parse(checked([kind, "inspect", id]))[0];
}
function verifyConfig(config, paths, expectedNetwork = "none") {
  assert.equal(config.Image, image);
  assert.equal(config.Config.Labels[label], run);
  assert.equal(config.Config.User, "10001:10001");
  assert.equal(config.Config.WorkingDir, "/app");
  assert.equal(config.HostConfig.NetworkMode, expectedNetwork, "Docker network must be none");
  assert.equal(config.HostConfig.ReadonlyRootfs, true);
  assert.equal(config.HostConfig.Privileged, false);
  assert.deepEqual(config.HostConfig.CapDrop, ["ALL"]);
  assert.equal((config.HostConfig.CapAdd ?? []).length, 0);
  assert.ok(config.HostConfig.SecurityOpt.includes("no-new-privileges"));
  assert.equal(config.HostConfig.PublishAllPorts, false);
  assert.equal(Object.keys(config.HostConfig.PortBindings ?? {}).length, 0);
  assert.equal((config.HostConfig.Binds ?? []).length, 0);
  assert.equal((config.HostConfig.Mounts ?? []).length, 0);
  assert.equal(config.Mounts.length, 0);
  assert.deepEqual(config.HostConfig.Tmpfs, paths);
  assert.equal(config.State.Status, "created", "Inspect before application start");
}
function runCase(name, { expectedError, scope = "CHG-294-R2", extraArgs = [],
  missingTmpfs = false, internalNetwork = false } = {}) {
  const paths = { ...tmpfs };
  if (missingTmpfs) delete paths["/app/public/__chg294-smoke"];
  const args = ["container", "create", "--interactive", "--pull=never", "--platform", "linux/arm64",
    "--name", `${run}-${name}`, "--label", `${label}=${run}`,
    "--network", internalNetwork ? network : "none", "--read-only", "--cap-drop=ALL",
    "--security-opt=no-new-privileges", "--user", "10001:10001", "--workdir", "/app",
    "--env", `NOMOSMART_IMAGE_SMOKE_SCOPE=${scope}`, "--entrypoint", "node"];
  for (const [path, options] of Object.entries(paths)) args.push("--tmpfs", `${path}:${options}`);
  args.push(image, "--input-type=module", "-", ...extraArgs);
  const id = checked(args);
  assert.match(id, /^[a-f0-9]{64}$/);
  containers.push(id);
  const config = inspect("container", id);
  if (internalNetwork) {
    assert.throws(() => verifyConfig(config, paths), /Docker network must be none/);
    const actualNetwork = inspect("network", network);
    assert.equal(actualNetwork.Internal, true, "Negative probe must not have external egress");
    assert.equal(actualNetwork.Labels[label], run);
    // Explicit negative test only, never the ordinary positive-smoke path.
    verifyConfig(config, paths, network);
  } else verifyConfig(config, paths);
  const outcome = docker(["container", "start", "--attach", "--interactive", id], script);
  const state = inspect("container", id).State;
  assert.equal(state.Status, "exited");
  if (expectedError) {
    assert.equal(outcome.status, 1, `${name} must fail before native/Next checks`);
    assert.equal(state.ExitCode, 1);
    assert.match(outcome.stderr, expectedError);
    assert.equal(outcome.stdout.trim(), "", "Rejected case must not emit success evidence");
    results.push({ name, pass: true, expectedRejection: true, exitCode: state.ExitCode,
      hostInspectorRejected: internalNetwork });
  } else {
    assert.equal(outcome.status, 0, outcome.stderr);
    assert.equal(state.ExitCode, 0);
    const actual = JSON.parse(outcome.stdout);
    assert.equal(actual.loginHttp, 200);
    assert.equal(actual.nodeOpenSSL, "3.5.8");
    assert.equal(actual.nativePngJpegEncodeResizeDecode, true);
    results.push({ name, pass: true, hostNetworkMode: config.HostConfig.NetworkMode,
      exitCode: state.ExitCode, actual });
  }
  console.log(JSON.stringify(results.at(-1)));
}

try {
  assert.equal(inspect("image", "nomosmart/frontend:0.1.0-chg294-r2").Id, image);
  assert.equal(inspect("image", "nomosmart/frontend:0.1.0-chg294").Id, oldImage);
  assert.equal(inspect("image", image).Architecture, "arm64");
  network = checked(["network", "create", "--driver", "bridge", "--internal",
    "--label", `${label}=${run}`, `${run}-internal`]);
  assert.match(network, /^[a-f0-9]{64}$/);
  runCase("active-interface", { internalNetwork: true,
    expectedError: /Non-loopback interface must be administratively down/ });
  runCase("scope", { scope: "REJECT", expectedError: /Explicit isolated image verification scope required/ });
  runCase("options", { extraArgs: ["unexpected"], expectedError: /No options accepted/ });
  runCase("tmpfs", { missingTmpfs: true, expectedError: /ENOENT.*__chg294-smoke/ });
  runCase("positive");
  assert.equal(inspect("image", "nomosmart/frontend:0.1.0-chg294-r2").Id, image);
  assert.equal(inspect("image", "nomosmart/frontend:0.1.0-chg294").Id, oldImage);
} finally {
  const errors = [];
  for (const id of containers) {
    try {
      assert.equal(inspect("container", id).Config.Labels[label], run);
      checked(["container", "rm", "--force", id]);
    } catch (error) { errors.push(error.message); }
  }
  if (network) {
    try {
      assert.equal(inspect("network", network).Labels[label], run);
      checked(["network", "rm", network]);
    } catch (error) { errors.push(error.message); }
  }
  assert.deepEqual(errors, [], "Exact owned test resource cleanup failed");
  console.log(JSON.stringify({ cleanup: "complete", run, casesCompleted: results.length,
    image, helperSha256: createHash("sha256").update(script).digest("hex") }));
}
