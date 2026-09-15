import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Static packaging guards only. Actual native/Next/image/security checks are separate.
const frontend = new URL("../", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("package.json", frontend), "utf8"));
const lock = JSON.parse(await readFile(new URL("package-lock.json", frontend), "utf8"));
const dockerfile = await readFile(new URL("Dockerfile", frontend), "utf8");

test("CHG-294 locks only the approved top-level framework/codec targets", () => {
  assert.equal(manifest.dependencies.next, "16.3.3");
  assert.equal(manifest.devDependencies["eslint-config-next"], "16.3.3");
  assert.equal(manifest.overrides.sharp, "0.35.4");
  assert.equal(manifest.dependencies.react, "19.2.3");
  assert.equal(manifest.dependencies["react-dom"], "19.2.3");
  assert.equal(manifest.overrides.browserslist, "4.28.7");
  assert.equal(manifest.overrides["js-yaml"], "4.3.2");
  assert.equal(manifest.overrides["baseline-browser-mapping"], "2.11.0");
  assert.equal(manifest.devDependencies.vitest, "4.1.11");
  assert.equal(manifest.devDependencies["@vitest/coverage-v8"], "4.1.11");
  assert.deepEqual(lock.packages[""].dependencies, manifest.dependencies);
  assert.deepEqual(lock.packages[""].devDependencies, manifest.devDependencies);
});

test("CHG-294 has coherent Next, sharp and native lock entries with integrity", () => {
  for (const [path, pkg] of Object.entries(lock.packages)) {
    const name = path.split("node_modules/").at(-1);
    let expected;
    if (["next", "eslint-config-next", "@next/env", "@next/eslint-plugin-next"].includes(name)
      || name.startsWith("@next/swc-")) expected = "16.3.3";
    if (name === "sharp" || name.startsWith("@img/sharp-")) {
      expected = name.startsWith("@img/sharp-libvips-") ? "1.3.3" : "0.35.4";
    }
    if (expected) {
      assert.equal(pkg.version, expected, path);
      assert.match(pkg.integrity, /^sha512-/, path);
      assert.match(pkg.resolved, /^https:\/\/registry\.npmjs\.org\//, path);
    }
  }
  for (const name of ["next", "sharp", "eslint-config-next", "@next/env",
    "@next/eslint-plugin-next", "@next/swc-linux-arm64-musl",
    "@img/sharp-linuxmusl-arm64", "@img/sharp-libvips-linuxmusl-arm64"]) {
    assert.ok(lock.packages[`node_modules/${name}`], name);
  }
});

test("CHG-294 R1 locks all repaired toolchain and shared dependency copies", () => {
  const targets = { browserslist: "4.28.7", "js-yaml": "4.3.2",
    "baseline-browser-mapping": "2.11.0", vitest: "4.1.11",
    "@vitest/coverage-v8": "4.1.11", "@vitest/mocker": "4.1.11" };
  for (const name of Object.keys(targets)) assert.ok(lock.packages[`node_modules/${name}`]);
  for (const [path, pkg] of Object.entries(lock.packages)) {
    const name = path.split("node_modules/").at(-1);
    const expected = targets[name] ?? (name.startsWith("@vitest/") ? "4.1.11" : undefined);
    if (!expected) continue;
    assert.equal(pkg.version, expected, path);
    assert.match(pkg.integrity, /^sha512-/, path);
  }
});

test("CHG-294 shares one pinned base and bounded crypto repair across all stages", () => {
  const from = dockerfile.split("\n").filter((line) => /^FROM /i.test(line));
  assert.equal(from.length, 5);
  assert.equal(from[0], "FROM node:24.21.0-alpine3.24@sha256:be80f76cf40ec8e42b9bec49f60a55e0660f30af58d3e5a25530785b30ea67e2 AS base");
  assert.deepEqual(from.slice(1), ["FROM base AS deps", "FROM base AS builder",
    "FROM base AS prod-deps", "FROM base AS runner"]);
  for (const name of ["openssl", "libssl3", "libcrypto3"]) {
    assert.ok(dockerfile.includes(`${name}=3.5.8-r0`), name);
  }
  assert.doesNotMatch(dockerfile, /apk upgrade|--allow-untrusted|--no-check-certificate/);
  assert.match(dockerfile, /adduser -S -u 10001 nomosmart/);
  assert.match(dockerfile, /USER nomosmart/);
  assert.match(dockerfile, /CMD \["node", "node_modules\/next\/dist\/bin\/next", "start"\]/);
});
