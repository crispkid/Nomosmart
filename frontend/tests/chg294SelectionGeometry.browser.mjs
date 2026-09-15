// Required real-browser replacement for the former CHG-285 geometry mock.
// This is a component geometry test, not OIDC/API/OCR/Provider acceptance.
import assert from "node:assert/strict";
import { mkdir, readFile, realpath, stat, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { createServer } from "vite";

const root = await realpath(fileURLToPath(new URL("..", import.meta.url)));
const integrated = /^\/private\/tmp\/chg291-release-[a-z0-9_]+\/source\/frontend$/.test(root);
if (integrated) {
  // Approved cumulative verification: require an actual private, source-bound
  // run, not just an environment flag or a lookalike directory name.
  const run = resolve(root, "../..");
  assert.equal((await stat(run)).mode & 0o077, 0, "Private integrated workspace required");
  const manifest = JSON.parse(await readFile(resolve(run, "source-manifest.json"), "utf8"));
  assert.equal(manifest.root, run);
  assert.equal(manifest.scope, "CHG-291 integrated preparation A-C; no deployment or Provider");
  const names = Object.keys(manifest.files).filter((name) => name.startsWith("frontend/src/")
    || name.startsWith("frontend/tests/chg294SelectionGeometry.") || name === "frontend/package-lock.json");
  assert.ok(names.length > 10, "Full component/source binding required");
  for (const name of names) {
    assert.ok(!name.split("/").includes(".."));
    const path = resolve(run, "source", name);
    assert.equal(await realpath(path), path, "No symlink source binding");
    assert.equal(createHash("sha256").update(await readFile(path)).digest("hex"), manifest.files[name]);
  }
} else {
  assert.match(root, /^\/private\/tmp\/chg294-r[12]\.[A-Za-z0-9]+\/frontend$/,
    "Run only from a disposable approved source-bound workspace");
}
const output = integrated ? resolve(root, "../../output/playwright/chg291-integrated")
  : resolve(root, "../output/playwright", root.includes("/chg294-r2.") ? "chg294-r2" : "chg294-r1");
await mkdir(output, { recursive: true });
const server = await createServer({ configFile: false, root,
  resolve: { alias: { "@": resolve(root, "src") } },
  server: { host: "127.0.0.1", port: 0, strictPort: true, fs: { strict: true, allow: [root] } },
});
let browser;
const evidence = { scope: "real production component/CSS geometry; not full product E2E", measurements: [], checks: [] };
try {
  await server.listen();
  const address = server.httpServer.address();
  assert.equal(typeof address, "object");
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${address.port}/tests/chg294SelectionGeometry.html`);
  await page.locator("#markdown-case .is-positioned").waitFor();

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    for (const scrollTop of [0, 85]) {
      await page.locator("#markdown-case").evaluate((el, offset) => { el.scrollTop = offset; }, scrollTop);
      await page.waitForFunction(() => {
        const box = document.querySelector("#markdown-case .canonical-markdown-selection-group");
        const range = document.querySelector("#markdown-case .canonical-markdown-range");
        if (!box || !range) return false;
        const a = box.getBoundingClientRect(), b = range.getBoundingClientRect();
        return a.width > 0 && a.height > 0 && ["left", "top", "right", "bottom"].every((key) => Math.abs(a[key] - b[key]) < 1.5);
      });
      const measured = await page.locator("#markdown-case").evaluate((section) => {
        const source = section.querySelector(".canonical-markdown-source");
        const boxes = section.querySelectorAll(".canonical-markdown-selection-group");
        const mapped = section.querySelector(".canonical-markdown-range");
        if (!source || !mapped || boxes.length !== 1) throw new Error("One exact-range enclosure required");
        const selection = document.createRange();
        selection.selectNodeContents(mapped);
        const rects = [...selection.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
        const box = boxes[0].getBoundingClientRect();
        const contained = rects.every((r) => r.left >= box.left - 1.5 && r.right <= box.right + 1.5
          && r.top >= box.top - 1.5 && r.bottom <= box.bottom + 1.5);
        return { source: source.textContent, selection: mapped.textContent,
          start: Number(mapped.getAttribute("data-markdown-start")), end: Number(mapped.getAttribute("data-markdown-end")),
          chunk: boxes[0].getAttribute("data-chunk-id"), rectCount: rects.length,
          contained, scrollTop: section.scrollTop, box: box.toJSON() };
      });
      assert.equal(measured.chunk, "measured");
      assert.equal(measured.start, 7);
      assert.equal(measured.source.slice(measured.start, measured.end), measured.selection);
      assert.equal(measured.source, `Before\n${measured.selection}\nAfter`);
      assert.ok(measured.rectCount > 1 && measured.contained);
      const maximumScroll = await page.locator("#markdown-case").evaluate((el) => el.scrollHeight - el.clientHeight);
      assert.equal(measured.scrollTop, Math.min(scrollTop, maximumScroll));
      if (scrollTop > 0) assert.ok(measured.scrollTop > 0, "Exercise actual internal scrolling");
      evidence.measurements.push({ width, requestedScrollTop: scrollTop, actualScrollTop: measured.scrollTop,
        rectCount: measured.rectCount, box: measured.box });
    }
    await page.screenshot({ path: resolve(output, `geometry-${width}.png`), fullPage: true });
  }
  assert.deepEqual(await page.locator("#different-case .canonical-markdown-selection-group").evaluateAll(
    (elements) => elements.map((el) => el.getAttribute("data-chunk-id"))), ["alpha", "gamma"]);
  assert.equal(await page.locator("#different-case .canonical-markdown-source").textContent(), "Alpha Beta Gamma");
  const originals = await page.locator("#original-case").evaluate((section) => {
    const boxes = section.querySelectorAll(".layout-selection-group");
    const blocks = [...section.querySelectorAll(".layout-block.source-active")];
    if (boxes.length !== 1 || blocks.length !== 2) throw new Error("Expected one group for paragraph plus list");
    const rect = boxes[0].getBoundingClientRect();
    return { width: rect.width, height: rect.height, contained: blocks.every((block) => {
      const b = block.getBoundingClientRect();
      return b.left >= rect.left - 1.5 && b.right <= rect.right + 1.5 && b.top >= rect.top - 1.5 && b.bottom <= rect.bottom + 1.5;
    }) };
  });
  assert.ok(originals.width > 0 && originals.height > 0 && originals.contained);
  assert.deepEqual(await page.locator("#cross-page-case .layout-selection-group").evaluateAll(
    (elements) => elements.map((el) => [el.getAttribute("data-chunk-id"), el.getAttribute("data-page-number")])), [["cross", "1"], ["cross", "2"]]);
  assert.equal(await page.locator("#noncontiguous-case .layout-selection-group").count(), 2);
  assert.equal(await page.locator('#noncontiguous-case [data-source-anchor="unrelated"]').getAttribute("data-selected-chunk-ids"), null);
  const selected = page.locator("#markdown-case .canonical-markdown-range");
  await selected.focus();
  await selected.press("Enter");
  assert.equal(await page.locator("#selection-event").textContent(), "measured");
  await page.locator('#original-case [data-source-anchor="l"]').click();
  assert.equal(await page.locator("#selection-event").textContent(), "l");
  assert.deepEqual(errors, []);
  evidence.checks = ["multiline exact enclosure", "resize", "internal scroll", "text/offset preservation",
    "different Chunks", "one Original group for two anchors", "cross-page identity", "non-contiguous safety", "keyboard/click callbacks"];
  await writeFile(resolve(output, "geometry.json"), JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
} finally {
  await browser?.close();
  await server.close();
}
