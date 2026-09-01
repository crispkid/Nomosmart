import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  emptyIdentitySettings,
  validateIdentitySettings
} from "../src/lib/systemManagement.ts";

const validSettings = {
  ...emptyIdentitySettings,
  issuer: "https://nomosmart.local/identity/realms/nomosmart",
  realm: "nomosmart",
  clientId: "nomosmart-frontend",
  audience: "nomosmart-backend",
  discoveryUrl: "https://nomosmart.local/identity/realms/nomosmart/.well-known/openid-configuration",
  keycloakEnabled: true,
  syncEnabled: true,
  schedule: "0 2 * * *",
  timezone: "Asia/Taipei"
};

test("CHG-245 keeps unloaded validation neutral and revalidates the live configuration", async () => {
  const workspace = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");

  assert.match(workspace, /useState<ReturnType<typeof validateIdentitySettings>>\(\{\}\)/);
  assert.match(workspace, /const identityFromApi = identitySettingsFromConfiguration\(identityPayload\.configuration\);[\s\S]*setIdentityErrors\(validateIdentitySettings\(identityFromApi\)\)/);
  assert.match(workspace, /const saved = identitySettingsFromConfiguration\(response\.configuration\);[\s\S]*setIdentityErrors\(validateIdentitySettings\(saved\)\)/);
  assert.deepEqual(validateIdentitySettings(validSettings), {});
});

test("CHG-245 exposes every existing identity validation field with localized accessible feedback", async () => {
  const [workspace, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  const fields = ["issuer", "realm", "clientId", "audience", "discoveryUrl", "schedule", "timezone"];
  const translationKeys = [
    "identityValidationIssuerHttps",
    "identityValidationRealmRequired",
    "identityValidationClientIdRequired",
    "identityValidationAudienceRequired",
    "identityValidationDiscoveryHttps",
    "identityValidationScheduleCron",
    "identityValidationTimezoneIana"
  ];

  for (const field of fields) {
    assert.match(workspace, new RegExp(`identityErrors\\.${field}`));
    assert.match(workspace, new RegExp(`identityErrorMessage\\(\"${field}\"\\)`));
  }
  for (const key of translationKeys) {
    assert.ok(zh[key], `missing zh translation ${key}`);
    assert.ok(en[key], `missing en translation ${key}`);
  }
  assert.equal((workspace.match(/aria-invalid=\{Boolean\(identityErrors\./g) ?? []).length, 7);
  assert.equal((workspace.match(/className="identity-field-error"/g) ?? []).length, 7);
  assert.equal((workspace.match(/role="alert"/g) ?? []).length >= 7, true);
});

test("CHG-245 scopes stable geometry and responsive stacking to Identity Settings", async () => {
  const [workspace, css] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8")
  ]);

  assert.match(workspace, /identity-form-grid identity-oidc-form-grid/);
  assert.match(workspace, /identity-oidc-meta identity-wide-field/);
  assert.match(workspace, /identity-sync-action/);
  assert.match(css, /\.identity-oidc-form-grid \{ align-items: start; column-gap: 16px; row-gap: 14px; \}/);
  assert.match(css, /\.identity-oidc-form-grid \.identity-field > input, \.identity-schedule-row \.identity-field > input \{ height: 40px; min-height: 40px; max-height: 40px; \}/);
  assert.match(css, /\.identity-field-error \{ display: inline-flex;/);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*\.identity-oidc-form-grid,[\s\S]*\.identity-schedule-row \{ grid-template-columns: 1fr; \}/);
  assert.doesNotMatch(css, /\.identity-form-grid \{[^}]*align-items: start/);
});

test("CHG-245 preserves identity validation predicates while covering required fields", () => {
  const errors = validateIdentitySettings({
    ...validSettings,
    issuer: "http://insecure.example.test/realms/nomosmart",
    realm: "",
    clientId: "",
    audience: "",
    discoveryUrl: "not-a-url",
    schedule: "daily",
    timezone: "Taipei"
  });

  assert.deepEqual(Object.keys(errors).sort(), [
    "audience",
    "clientId",
    "discoveryUrl",
    "issuer",
    "realm",
    "schedule",
    "timezone"
  ]);
});
