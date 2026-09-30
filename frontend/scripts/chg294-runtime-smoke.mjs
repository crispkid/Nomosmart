// Real installed-runtime checks; benign samples only, never a Provider or exploit.
// Run native checks without arguments. Optional fixtures/HTTP checks are temp-only.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import sharp from "sharp";

const require = createRequire(import.meta.url);
const options = new Map(process.argv.slice(2).map((arg) => {
  const equal = arg.indexOf("=");
  assert.ok(equal > 0, "Options require --name=value");
  const key = arg.slice(0, equal);
  assert.ok(["--fixtures-dir", "--next-origin"].includes(key), "Unknown option");
  return [key, arg.slice(equal + 1)];
}));
assert.equal(options.size, process.argv.length - 2, "Duplicate option");
assert.equal(require("next/package.json").version, "16.3.3");
assert.equal(sharp.versions.sharp, "0.35.4");
assert.equal(sharp.versions.heif, "1.23.2");

const samples = {};
const checks = [];
const source = { create: { width: 64, height: 48, channels: 3,
  background: { r: 60, g: 140, b: 90 } } };
for (const format of ["png", "jpeg", "avif"]) {
  const buffer = await sharp(source).toFormat(format).toBuffer();
  assert.ok(buffer.length > 0 && buffer.length < 65_536);
  const metadata = await sharp(buffer).metadata();
  assert.equal(metadata.width, 64);
  assert.equal(metadata.height, 48);
  if (format !== "avif") {
    const transformed = await sharp(buffer).resize(16, 12).toFormat(format).toBuffer();
    const decoded = await sharp(transformed).raw().toBuffer({ resolveWithObject: true });
    assert.equal(decoded.info.width, 16);
    assert.equal(decoded.info.height, 12);
    assert.ok(decoded.data.length > 0);
    checks.push(`native ${format} encode/resize/decode`);
  } else {
    checks.push("benign AVIF sample encode/header parse with patched libheif");
  }
  samples[format] = buffer;
}

const fixturesDir = options.get("--fixtures-dir");
if (fixturesDir) {
  // Never write samples into the user's actual public assets or an application image.
  const target = resolve(fixturesDir);
  assert.match(target, /^\/(?:private\/)?tmp\/chg294-(?:work|r[12])\.[A-Za-z0-9]+\/frontend\/public\/__chg294-smoke$/);
  await mkdir(target, { recursive: true });
  for (const [format, buffer] of Object.entries(samples)) {
    const path = join(target, `sample.${format}`);
    try { await writeFile(path, buffer, { flag: "wx" }); }
    catch (error) {
      if (error.code !== "EEXIST") throw error;
      assert.deepEqual(await readFile(path), buffer, "Existing sample differs; refuse overwrite");
    }
  }
  checks.push("temporary benign HTTP samples prepared");
}

const nextOrigin = options.get("--next-origin");
if (nextOrigin) {
  const origin = new URL(nextOrigin);
  assert.equal(origin.protocol, "http:");
  assert.equal(origin.hostname, "127.0.0.1");
  assert.equal(origin.origin, nextOrigin, "Only explicit loopback origin accepted");
  assert.ok(origin.port, "Explicit isolated test port required");
  for (const format of ["png", "jpeg", "avif"]) {
    const query = new URLSearchParams({ url: `/__chg294-smoke/sample.${format}`, w: "32", q: "75" });
    const response = await fetch(`${nextOrigin}/_next/image?${query}`, {
      headers: { Accept: "image/avif,image/webp,image/*" },
      redirect: "error", signal: AbortSignal.timeout(10_000),
    });
    assert.equal(response.status, 200, `Next ${format} status`);
    assert.ok(Number(response.headers.get("content-length")) < 65_536);
    const buffer = Buffer.from(await response.arrayBuffer());
    assert.ok(buffer.length > 0 && buffer.length < 65_536);
    const metadata = await sharp(buffer).metadata();
    if (format === "avif") {
      // Next 16.3.3 BYPASS_TYPES returns the original bytes, before optimization.
      assert.equal(response.headers.get("content-type"), "image/avif");
      assert.deepEqual(buffer, samples.avif);
      assert.equal(metadata.width, 64);
      assert.equal(metadata.height, 48);
      checks.push("Next AVIF byte-preserving bypass (no resize/optimization)");
    } else {
      assert.match(response.headers.get("content-type"), /^image\/(?:webp|png|jpeg)$/);
      assert.equal(metadata.width, 32);
      assert.equal(metadata.height, 24);
      checks.push(`Next ${format} actual HTTP optimization`);
    }
  }
}

console.log(JSON.stringify({ scope: "isolated installed-runtime, not final-image or full E2E",
  node: process.version, platform: process.platform, arch: process.arch,
  nodeOpenSSL: process.versions.openssl, next: require("next/package.json").version,
  sharp: sharp.versions.sharp, libvips: sharp.versions.vips, libheif: sharp.versions.heif,
  sampleSha256: Object.fromEntries(Object.entries(samples).map(([format, buffer]) =>
    [format, createHash("sha256").update(buffer).digest("hex")])), checks }, null, 2));
