import assert from "node:assert/strict";
import test from "node:test";
import { settingsSections, parseSettingsPosition, settingsPositionUrl, legacySettingsPositions, systemTabIds } from "../src/lib/systemRouteState.ts";

test("CHG-422 defaults to people and preserves all nine legacy destinations", () => {
  assert.deepEqual(parseSettingsPosition({}), { section: "people", panel: "users" });
  for (const tab of systemTabIds) assert.deepEqual(parseSettingsPosition({ tab }), legacySettingsPositions[tab]);
  assert.deepEqual(settingsSections.map(item => item.id), ["people", "identity", "ai", "documents", "apiKeys", "general", "status"]);
});
test("CHG-422 each valid panel is a scroll destination in its category", () => {
  for (const section of settingsSections) for (const panel of section.panels) {
    assert.deepEqual(parseSettingsPosition({ section: section.id, panel, tab: "users" }), { section: section.id, panel });
  }
});
test("CHG-422 invalid and duplicate positions cannot select another category's panel", () => {
  for (const panel of ["permissions", "https://example.com", ["ocr", "ocr"], undefined]) {
    assert.deepEqual(parseSettingsPosition({ section: "documents", panel }), { section: "documents", panel: "upload" });
  }
  assert.deepEqual(parseSettingsPosition({ section: ["documents", "ai"], tab: "roles" }), legacySettingsPositions.roles);
});
test("CHG-422 authentication return wins until the existing identity handler consumes it", () => {
  assert.deepEqual(parseSettingsPosition({ tab: "identity", reauth: "success", section: "documents", panel: "ocr" }), legacySettingsPositions.identity);
});
test("CHG-422 normalized links contain only canonical navigation metadata", () => {
  assert.equal(settingsPositionUrl("https://localhost/system?tab=parameters&search=person&reauth=success#old", { section: "documents", panel: "ocr" }), "/system?section=documents&panel=ocr");
});
