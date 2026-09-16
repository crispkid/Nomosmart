import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { operationalErrorMessage } from "../src/lib/operationalMessages.ts";

// Pure formatter inputs and real locale dictionaries; no API/Provider adapter.
for (const locale of ["zh", "en"]) {
  test(`CHG-295 deletion conflict is safe and localized (${locale})`, async () => {
    const dictionary = JSON.parse(await readFile(new URL(`../src/i18n/locales/${locale}.json`, import.meta.url), "utf8"));
    const t = (key) => dictionary[key];
    const format = (key, parameters) => Object.entries(parameters).reduce(
      (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)), t(key));
    const error = Object.assign(new Error("PRIVATE RAW SERVER DETAIL"), {
      status: 409, code: "chunk_delete_reference_conflict", requestId: "chg295-request",
    });
    const message = operationalErrorMessage(error, t, format, "knowledgeDetailDeleteChunkFailed");
    assert.ok(dictionary.knowledgeDetailDeleteChunkReferenceConflict);
    assert.ok(message.includes(dictionary.knowledgeDetailDeleteChunkReferenceConflict));
    assert.ok(message.includes("chg295-request"));
    assert.ok(!message.includes(error.message));
    delete error.requestId;
    assert.equal(operationalErrorMessage(error, t, format), dictionary.knowledgeDetailDeleteChunkReferenceConflict);
    error.code = "unknown_server_code";
    assert.equal(operationalErrorMessage(error, t, format), dictionary.apiConflict);
    error.status = 503;
    assert.equal(operationalErrorMessage(error, t, format), dictionary.apiServiceUnavailable);
  });
}
