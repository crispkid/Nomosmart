// CHG-294 R2 final-image check. Requires separately approved isolated image run.
// Invoke from /app via stdin, with network none/read-only root and only the named
// test directories as tmpfs. No app configuration, host mounts or Provider.
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, realpath, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";

assert.equal(process.argv.length, 2, "No options accepted");
assert.equal(process.env.NOMOSMART_IMAGE_SMOKE_SCOPE, "CHG-294-R2",
  "Explicit isolated image verification scope required");
assert.equal(process.platform, "linux", "Host checks are not final-image evidence");
assert.equal(process.arch, "arm64");
assert.equal(process.getuid(), 10001);
assert.equal(process.cwd(), "/app");
assert.equal(process.version, "v24.21.0");
assert.equal(process.versions.openssl, "3.5.8", "Node bundled OpenSSL must be repaired independently");

// Refuse network access or persistent writes if the caller omitted isolation.
const mounts = (await readFile("/proc/mounts", "utf8")).trim().split("\n")
  .map((line) => line.split(" "));
assert.ok(mounts.find((row) => row[1] === "/" && row[3].split(",").includes("ro")),
  "Read-only container root required");
const interfaces = (await readFile("/proc/net/dev", "utf8")).split("\n")
  .filter((line) => line.includes(":" )).map((line) => line.split(":")[0].trim());
assert.ok(interfaces.includes("lo"), "Loopback interface required");
assert.equal(new Set(interfaces).size, interfaces.length, "Unique kernel interface names required");
const interfaceState = [];
for (const name of interfaces) {
  assert.match(name, /^[a-zA-Z0-9_.:-]+$/, "Invalid kernel interface name");
  const flagsText = (await readFile(`/sys/class/net/${name}/flags`, "utf8")).trim();
  assert.match(flagsText, /^0x[0-9a-f]+$/i, "Valid kernel interface flags required");
  const flags = Number.parseInt(flagsText, 16);
  const state = (await readFile(`/sys/class/net/${name}/operstate`, "utf8")).trim();
  if (name === "lo") {
    assert.ok((flags & 0x9) === 0x9, "Loopback must be up and loopback-flagged");
  } else {
    // Kernels may expose inactive tunnel devices even in Docker network=none.
    assert.ok((flags & 0x41) === 0, "Non-loopback interface must be administratively down");
    assert.equal(state, "down", "Non-loopback interface must be down");
  }
  interfaceState.push({ name, flags: flagsText, state });
}
// Unlike os.networkInterfaces(), netlink also includes addresses on down devices.
// Use the image's existing BusyBox; missing tools or malformed output fail closed.
const addressLines = execFileSync("/bin/busybox", ["ip", "-o", "address", "show"],
  { encoding: "utf8", timeout: 10000 }).trim().split("\n").filter(Boolean);
for (const line of addressLines) {
  const address = line.match(/^\d+:\s+(\S+)\s+inet6?\s+(\S+)/);
  assert.ok(address, "Malformed kernel address listing");
  assert.equal(address[1], "lo", "No non-loopback address allowed");
}
const ipv4Lines = (await readFile("/proc/net/route", "utf8")).trim().split("\n");
assert.match(ipv4Lines.shift(), /^Iface\s+Destination\s+Gateway/);
for (const line of ipv4Lines) {
  const fields = line.trim().split(/\s+/);
  assert.ok(fields.length >= 11, "Malformed IPv4 route");
  assert.equal(fields[0], "lo", "No non-loopback IPv4 route allowed");
}
const ipv6Lines = (await readFile("/proc/net/ipv6_route", "utf8"))
  .trim().split("\n").filter(Boolean);
for (const line of ipv6Lines) {
  const fields = line.trim().split(/\s+/);
  assert.equal(fields.length, 10, "Malformed IPv6 route");
  assert.equal(fields[9], "lo", "No non-loopback IPv6 route allowed");
}
for (const path of ["/tmp", "/app/public/__chg294-smoke", "/app/.next/cache"]) {
  assert.equal(await realpath(path), path, "No symlink test directories");
  assert.ok((await stat(path)).isDirectory());
  assert.ok(mounts.find((row) => row[1] === path && row[2] === "tmpfs"),
    "Only explicit tmpfs test writes allowed");
}

const require = createRequire(import.meta.url);
const { default: sharp } = await import("sharp");
assert.equal(require("next/package.json").version, "16.3.3");
assert.equal(sharp.versions.sharp, "0.35.4");
assert.equal(sharp.versions.heif, "1.23.2");
for (const [file, expected] of [
  ["package.json", "76cf6331e73990bc2598aa5dd94728a1dfb58cdfb2c86cd37229be9debbfa404"],
  ["package-lock.json", "0c00961b9a9baa799788c85cb6fdeff573d34ca8605b685fcaad17671e9ac025"],
]) assert.equal(createHash("sha256").update(await readFile(file)).digest("hex"), expected);

const packages = execFileSync("apk", ["info", "-v"], { encoding: "utf8", timeout: 10000 })
  .split("\n").filter((line) => /^(openssl|libssl3|libcrypto3)-/.test(line)).sort();
assert.deepEqual(packages, ["libcrypto3-3.5.8-r0", "libssl3-3.5.8-r0", "openssl-3.5.8-r0"]);
const linkage = execFileSync("ldd", [process.execPath], { encoding: "utf8", timeout: 10000 });
assert.match(linkage, /musl/);
const systemOpenSSL = execFileSync("openssl", ["version"], { encoding: "utf8", timeout: 10000 }).trim();
assert.match(systemOpenSSL, /^OpenSSL 3\.5\.8 /);

const samples = {};
for (const format of ["png", "jpeg", "avif"]) {
  samples[format] = await sharp({ create: { width: 64, height: 48, channels: 3,
    background: { r: 60, g: 140, b: 90 } } }).toFormat(format).toBuffer();
  assert.ok(samples[format].length > 0 && samples[format].length < 65536);
  const metadata = await sharp(samples[format]).metadata();
  assert.equal(metadata.width, 64);
  assert.equal(metadata.height, 48);
  if (format !== "avif") {
    const transformed = await sharp(samples[format]).resize(16, 12).toFormat(format).toBuffer();
    const decoded = await sharp(transformed).raw().toBuffer({ resolveWithObject: true });
    assert.equal(decoded.info.width, 16);
    assert.equal(decoded.info.height, 12);
    assert.ok(decoded.data.length > 0);
  }
  await writeFile(`/app/public/__chg294-smoke/sample.${format}`, samples[format], { flag: "wx" });
}

const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start",
  "--hostname", "127.0.0.1", "--port", "13094"], { stdio: ["ignore", "ignore", "ignore"] });
const exited = new Promise((resolve) => {
  child.once("exit", resolve);
  child.once("error", resolve);
});
let spawnError;
child.once("error", (error) => { spawnError = error; });
const imageHttp = [];
try {
  let login;
  for (let attempt = 0; attempt < 40; attempt++) {
    if (spawnError) throw spawnError;
    if (child.exitCode !== null) throw new Error("Next exited before readiness");
    try {
      login = await fetch("http://127.0.0.1:13094/login", {
        redirect: "error", signal: AbortSignal.timeout(1000),
      });
    } catch { /* Real startup may not yet be listening; bounded retry only. */ }
    if (login?.status === 200) break;
    if (login?.body) await login.body.cancel();
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.equal(login?.status, 200, "Actual Next login HTTP");
  assert.match(await login.text(), /NomoSmart/i);
  for (const format of ["png", "jpeg", "avif"]) {
    const query = new URLSearchParams({ url: `/__chg294-smoke/sample.${format}`, w: "32", q: "75" });
    const response = await fetch(`http://127.0.0.1:13094/_next/image?${query}`, {
      headers: { Accept: "image/avif,image/webp,image/*" }, redirect: "error",
      signal: AbortSignal.timeout(10000),
    });
    assert.equal(response.status, 200);
    const buffer = Buffer.from(await response.arrayBuffer());
    assert.ok(buffer.length > 0 && buffer.length < 65536);
    const metadata = await sharp(buffer).metadata();
    if (format === "avif") {
      assert.equal(response.headers.get("content-type"), "image/avif");
      assert.deepEqual(buffer, samples.avif);
      assert.equal(metadata.width, 64);
      assert.equal(metadata.height, 48);
    } else {
      assert.match(response.headers.get("content-type"), /^image\/(webp|png|jpeg)$/);
      assert.equal(metadata.width, 32);
      assert.equal(metadata.height, 24);
      assert.ok((await sharp(buffer).raw().toBuffer()).length > 0);
    }
    imageHttp.push({ format, status: response.status, mime: response.headers.get("content-type"),
      width: metadata.width, height: metadata.height, originalBytes: format === "avif" });
  }
  console.log(JSON.stringify({ scope: "CHG-294 R2 final image; not full E2E or release approval",
    uid: process.getuid(), platform: process.platform, arch: process.arch, node: process.version,
    networkIsolation: { interfaceState, addressLines,
      ipv4RouteCount: ipv4Lines.length, ipv6RouteCount: ipv6Lines.length },
    nodeOpenSSL: process.versions.openssl, systemOpenSSL, packages,
    nodeLinkage: linkage.trim().split("\n"),
    nodeDynamicallyLinksSystemCrypto: /lib(?:ssl|crypto)\.so/.test(linkage),
    next: require("next/package.json").version, sharp: sharp.versions.sharp,
    libvips: sharp.versions.vips, libheif: sharp.versions.heif,
    nativePngJpegEncodeResizeDecode: true, loginHttp: 200, imageHttp }, null, 2));
} finally {
  child.kill("SIGTERM");
  const killTimeout = setTimeout(() => child.kill("SIGKILL"), 5000);
  await exited;
  clearTimeout(killTimeout);
}
