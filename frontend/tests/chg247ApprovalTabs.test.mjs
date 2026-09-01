import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

test("REVIEW-023 approval tabs match the compact NomoSmart navigation pattern", () => {
  const page = read("frontend/src/app/approve/page.tsx");
  const css = read("frontend/src/app/globals.css");

  assert.match(page, /<nav aria-label=\{t\("approval"\)\} className="tab-strip">/);
  assert.equal(page.match(/role="tab"/g)?.length, 4);
  assert.match(css, /\.tab-strip \{[^}]*overflow-x: auto;[^}]*border: 1px solid var\(--cool-gray\);[^}]*border-radius: 8px;[^}]*background: #f8faf9;/);
  assert.match(css, /\.tab-strip button \{[^}]*min-height: 40px;[^}]*border: 1px solid transparent;[^}]*border-radius: 6px;[^}]*cursor: pointer;/);
  assert.match(css, /\.tab-strip button\.active,[\s\S]*?background: var\(--fresh-mint\);[\s\S]*?box-shadow:[^;]*inset 0 -2px 0 var\(--calm-green\);/);
  assert.match(css, /\.tab-strip button:focus-visible \{[^}]*outline: 3px solid rgba\(95, 174, 136, \.25\);[^}]*outline-offset: 2px;/);
  assert.match(css, /\.tab-strip button span \{[^}]*min-width: 22px;[^}]*height: 22px;[^}]*border-radius: 999px;/);
});
