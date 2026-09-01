import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/app/reports/page.tsx", import.meta.url);
const cssPath = new URL("../src/app/globals.css", import.meta.url);

test("REPORT-012 uses the scoped NomoSmart export control and stable state icons", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(page, /className="action-button secondary report-export-button"/);
  assert.match(page, /aria-busy=\{table\.exporting\}/);
  assert.match(page, /table\.exporting \? <LoaderCircle[^>]*className="spin"/);
  assert.match(page, /: <Download aria-hidden="true" size=\{16\}/);
  assert.match(page, /disabled=\{table\.exporting \|\| table\.loading\}/);
  assert.doesNotMatch(page, /secondary-button compact/);
});

test("REPORT-012 keeps hover, focus and disabled styling scoped and layout-stable", async () => {
  const css = await readFile(cssPath, "utf8");

  assert.match(css, /\.report-panel-actions \.report-export-button \{[\s\S]*width: 132px;[\s\S]*min-height: 36px;/);
  assert.match(css, /\.report-panel-actions \.report-export-button:hover:not\(:disabled\)/);
  assert.match(css, /\.report-panel-actions \.report-export-button:focus-visible/);
  assert.match(css, /\.report-panel-actions \.report-export-button:disabled \{[\s\S]*cursor: not-allowed;/);
  assert.match(css, /transform: none;/);
  assert.match(css, /\.report-results \.content-grid > \.panel \{[\s\S]*min-width: 0;/);
  assert.match(css, /\.report-results \.content-grid\.two \{[\s\S]*grid-template-columns: minmax\(0, 1fr\);/);
  assert.doesNotMatch(css, /^\.report-export-button \{/m);
});
