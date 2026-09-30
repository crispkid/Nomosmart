export type ApprovalDecision = "approve" | "reject";

export type ApprovalConversation = {
  id: string;
  title: string;
  turns: Array<{
    question: string;
    answer: string;
    time: string;
    citation: string;
    evaluation: string;
    suggestion: string;
  }>;
};

function escapeCsv(value: string) {
  return `"${value.replaceAll('"', '""')}"`;
}

export function buildApprovalConversationCsv(conversations: ApprovalConversation[]) {
  const headers = ["conversation_id", "conversation_title", "question", "answer", "time", "citation", "evaluation", "suggested_correction"];
  const rows = conversations.flatMap((conversation) => conversation.turns.map((turn) => [
    conversation.id,
    conversation.title,
    turn.question,
    turn.answer,
    turn.time,
    turn.citation,
    turn.evaluation,
    turn.suggestion
  ].map(escapeCsv).join(",")));

  return `\uFEFF${headers.join(",")}\n${rows.join("\n")}`;
}

export function canSubmitApprovalDecision(decision: ApprovalDecision, comment: string) {
  return decision === "approve" || comment.trim().length > 0;
}
