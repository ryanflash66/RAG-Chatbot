import type { AnswerMetadata, AnswerPayload } from "@/types";
import type { HistoryMessage, QuestionMetadata } from "./history";

// Test data for the runtime's tests (*.test.ts); nothing in the page imports it.

export function payload(overrides: Partial<AnswerPayload> = {}): AnswerPayload {
  return {
    answer: "Flaggers stand 100 ft ahead of the work [1].",
    refused: false,
    uncited: false,
    sources: [
      {
        n: 1,
        division: "wztc",
        title: "Work Zone Manual",
        page: 12,
        page_end: null,
        section: "6E.02",
        url: "https://example.org/wztc.pdf#page=12",
        excerpt: "Flaggers…",
      },
    ],
    model: "nvidia/nemotron-3-ultra-550b-a55b:free",
    first_model: "nvidia/nemotron-3-ultra-550b-a55b:free",
    retried: false,
    suggest: [],
    asker: { id: "utilities", name: "Utilities" },
    target: { id: "wztc", name: "Work Zone Traffic Control" },
    steps: [
      { id: "read", label: "Reading the question", ms: 40 },
      { id: "write", label: "Writing the answer", ms: 3200 },
    ],
    timing_ms: { total: 4100 },
    searched: { documents: 1, passages: 412 },
    ...overrides,
  };
}

export function question(text: string, custom: QuestionMetadata = {}): HistoryMessage {
  return { role: "user", content: [{ type: "text", text }], metadata: { custom } };
}

export function answer(meta: AnswerMetadata, status = "complete"): HistoryMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text: meta.payload?.answer ?? "" }],
    status: { type: status },
    metadata: { custom: meta },
  };
}
