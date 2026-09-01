import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test("wires the shared citation presenter to every required Chat evidence surface", async () => {
  const [documentChat, projectChat, submitReview, approval, presenter, api] = await Promise.all([
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/submit-review/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/approve/[approvalTaskId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ChatResponseEvidence.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
  ]);

  for (const surface of [documentChat, projectChat, submitReview, approval]) {
    assert.match(surface, /ChatResponseEvidence/);
  }
  assert.match(presenter, /chunkContentPreview\(citation\.excerpt\)/);
  assert.doesNotMatch(presenter, /citation\.title/);
  assert.match(presenter, /chat-citation-ordinal/);
  assert.match(presenter, /onCitationSelect=\{openCitation\}/);
  assert.match(api, /chunk_index\?: number \| null/);
});


test("counts persisted question-answer records as turns and blocks duplicate submits", async () => {
  const [documentChat, projectChat, english, chinese] = await Promise.all([
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(documentChat, /conversationEntries\.length \* 2/);
  assert.doesNotMatch(projectChat, /conversation\.entries\.length \* 2/);
  assert.match(documentChat, /entry\.recordId && !entry\.loading && !entry\.error/);
  assert.match(projectChat, /entry\.recordId && !entry\.loading && !entry\.error/);
  assert.match(documentChat, /\|\| queryBusy/);
  assert.match(projectChat, /\|\| queryBusy/);
  assert.match(english, /conversation turn/);
  assert.match(chinese, /輪對話/);
});


test("keeps waiting feedback accessible and stops motion when requested", async () => {
  const [waiting, css] = await Promise.all([
    readFile(new URL("../src/components/ChatWaitingIndicator.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(waiting, /LoaderCircle/);
  assert.match(waiting, /aria-busy="true"/);
  assert.match(waiting, /aria-live="polite"/);
  assert.match(waiting, /role="status"/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.chat-waiting-spinner\s*\{\s*animation: none/);
});
