import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import tsParser from "@typescript-eslint/parser";
import { Linter } from "eslint";

import noUntranslatedVisibleText from "../eslint-rules/no-untranslated-visible-text.mjs";
import { visibleTextAllowlist } from "../src/i18n/visibleTextAllowlist.mjs";

const linter = new Linter({ configType: "flat" });
const config = [
  {
    files: ["**/*.tsx"],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaFeatures: { jsx: true }, ecmaVersion: "latest", sourceType: "module" }
    },
    plugins: {
      nomosmart: {
        rules: { "no-untranslated-visible-text": noUntranslatedVisibleText }
      }
    },
    rules: {
      "nomosmart/no-untranslated-visible-text": [
        "error",
        { allowlist: visibleTextAllowlist }
      ]
    }
  }
];

async function verifyFixture(name) {
  const source = await readFile(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
  return linter.verify(source, config, { filename: name.replace(".txt", "") });
}

test("I18N-004 AST guard rejects visible English, Chinese attributes and fixed locales", async () => {
  const messages = await verifyFixture("i18n-invalid.fixture.tsx.txt");
  assert.deepEqual(
    new Set(messages.map((message) => message.messageId)),
    new Set(["fixedLocale", "runtimeMessage", "visibleAttribute", "visibleText"])
  );
  assert.equal(messages.filter((message) => message.messageId === "visibleAttribute").length, 2);
  assert.ok(messages.filter((message) => message.messageId === "visibleText").length >= 3);
  assert.equal(messages.filter((message) => message.messageId === "runtimeMessage").length, 3);
});

test("I18N-004 AST guard accepts translations, runtime locale and reviewed protocol literals", async () => {
  assert.deepEqual(await verifyFixture("i18n-valid.fixture.tsx.txt"), []);
});

test("I18N-004 allowlist rejects wildcards and untyped categories", () => {
  const source = "export const Component = () => <span>Anything</span>;";
  const wildcardMessages = linter.verify(
    source,
    [
      {
        ...config[0],
        rules: {
          "nomosmart/no-untranslated-visible-text": [
            "error",
            { allowlist: { protocol: ["*"] } }
          ]
        }
      }
    ],
    { filename: "invalid-allowlist.tsx" }
  );
  assert.ok(wildcardMessages.some((message) => message.messageId === "invalidAllowlist"));
  assert.throws(() =>
    linter.verify(
      source,
      [
        {
          ...config[0],
          rules: {
            "nomosmart/no-untranslated-visible-text": [
              "error",
              { allowlist: { generalCopy: ["Anything"] } }
            ]
          }
        }
      ],
      { filename: "untyped-allowlist.tsx" }
    )
  );
});

test("I18N-004 zh/en keys and interpolation parameters stay aligned", async () => {
  const [zh, en] = await Promise.all([
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort());
  for (const key of Object.keys(zh)) {
    const placeholders = (value) => [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map((match) => match[1]).sort();
    assert.deepEqual(placeholders(zh[key]), placeholders(en[key]), `placeholder mismatch for ${key}`);
  }
});
