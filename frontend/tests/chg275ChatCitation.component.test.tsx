import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { ChatWaitingIndicator } from "@/components/ChatWaitingIndicator";
import { setLocalePreference } from "@/lib/i18nClient";
import type { ProjectChatCitation } from "@/lib/api";


const longExcerpt = `${"字".repeat(23)}👨‍👩‍👧‍👦尾端`;
const citations: ProjectChatCitation[] = [
  {
    chunk_id: "11111111-1111-4111-8111-111111111111",
    chunk_index: 25,
    content_type: "text",
    document_id: "22222222-2222-4222-8222-222222222222",
    document_version_id: "33333333-3333-4333-8333-333333333333",
    excerpt: longExcerpt,
    index_name: "staging-index",
    page: 2,
    score: 0.95,
    title: "Repeated document title #24",
  },
  {
    chunk_id: "44444444-4444-4444-8444-444444444444",
    chunk_index: 2,
    content_type: "text",
    document_id: "22222222-2222-4222-8222-222222222222",
    document_version_id: "33333333-3333-4333-8333-333333333333",
    excerpt: "Second canonical excerpt",
    index_name: "staging-index",
    page: null,
    score: 0.72,
    title: "Repeated document title #2",
  },
];


describe("CHG-275 Chat citation and waiting presentation", () => {
  it("uses content previews, separates source ordinals from canonical Chunk numbers, and opens matching markers", () => {
    setLocalePreference("en", false);
    render(
      <ChatResponseEvidence
        answer="Grounded response [1] with an invalid legacy marker [3]."
        answerFallback="No answer"
        citations={citations}
        citationsLabel="Citations"
        idPrefix="citation-test"
        noCitationsLabel="No citations"
      />,
    );

    expect(screen.queryByText("Repeated document title #24")).not.toBeInTheDocument();
    expect(screen.getByText(`${"字".repeat(23)}👨‍👩‍👧‍👦…`)).toBeInTheDocument();
    expect(screen.getByText(/Chunk #25/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open source \[1\]/ })).toHaveTextContent("[1]");
    expect(screen.getByLabelText("Citation [3] has no matching source")).toHaveClass("invalid");

    fireEvent.click(screen.getByRole("button", { name: "View citation source [1]" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveFocus();
    expect(dialog).toHaveTextContent("[1]");
    expect(dialog).toHaveTextContent("Chunk #25");
    expect(dialog).toHaveTextContent(longExcerpt);
    act(() => setLocalePreference("zh", false));
  });

  it("keeps blank excerpts on the canonical localized fallback", () => {
    setLocalePreference("zh", false);
    render(
      <ChatResponseEvidence
        answer="回答 [1]"
        answerFallback="沒有回答"
        citations={[{ ...citations[0], excerpt: " \n\t " }]}
        citationsLabel="引用來源"
        idPrefix="fallback-test"
        noCitationsLabel="沒有引用"
      />,
    );

    expect(screen.getAllByText("切片 #25").length).toBeGreaterThan(0);
  });

  it("announces one stable busy state with the Lucide loading element", () => {
    render(<ChatWaitingIndicator label="等待 AI 回應" />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status.querySelectorAll(".chat-waiting-spinner")).toHaveLength(1);
    expect(status).toHaveTextContent("等待 AI 回應");
  });
});
