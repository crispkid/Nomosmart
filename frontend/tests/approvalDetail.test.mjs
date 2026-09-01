import assert from "node:assert/strict";
import test from "node:test";
import {
  buildApprovalConversationCsv,
  canSubmitApprovalDecision
} from "../src/lib/approvalDetail.ts";

const conversations = [{
  id: "conversation-1",
  title: "Quoted, title",
  turns: [{
    question: "What does \"active\" mean?",
    answer: "Published, searchable",
    time: "09:30:00",
    citation: "policy.pdf|v5.0|C-001|page 3",
    evaluation: "correct",
    suggestion: ""
  }]
}];

test("approval CSV includes BOM, task evidence columns, and escaped values", () => {
  const csv = buildApprovalConversationCsv(conversations);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.match(csv, /conversation_id,conversation_title,question,answer/);
  assert.match(csv, /"Quoted, title"/);
  assert.match(csv, /"What does ""active"" mean\?"/);
  assert.match(csv, /"policy\.pdf\|v5\.0\|C-001\|page 3"/);
});

test("approval comment is optional and rejection reason is required", () => {
  assert.equal(canSubmitApprovalDecision("approve", ""), true);
  assert.equal(canSubmitApprovalDecision("reject", ""), false);
  assert.equal(canSubmitApprovalDecision("reject", "   "), false);
  assert.equal(canSubmitApprovalDecision("reject", "Missing source evidence"), true);
});
