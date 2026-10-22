import type { ThreadMessageLike } from "@assistant-ui/react";
import type { AnswerMetadata, AnswerPayload, Division, Source } from "@/types";

// Test data in the shapes the server sends and the runtime adapter (DAR-631) stores, so
// the panels can be checked against assistant-ui's real thread state without the backend.

export const DIVISIONS: Division[] = [
  {
    id: "wztc",
    name: "Work Zone Traffic Control",
    unit: "WZTC",
    examples: [],
    passages: 120,
    documents: [
      { file: "tmp.pdf", title: "Traffic Management Plan Manual", url: "https://example.org/tmp.pdf", passages: 70 },
      { file: "flagger.pdf", title: "Flagger Handbook", url: "https://example.org/flagger.pdf", passages: 50 },
    ],
  },
  {
    id: "utilities",
    name: "Utilities",
    unit: "Utilities",
    examples: [],
    passages: 90,
    documents: [
      { file: "uam.pdf", title: "Utilities Accommodation Manual", url: "https://example.org/uam.pdf", passages: 90 },
    ],
  },
];

export function source(n: number, extra: Partial<Source> = {}): Source {
  return {
    n,
    division: "utilities",
    title: "Utilities Accommodation Manual",
    page: 10 + n,
    page_end: null,
    section: `${n}.1`,
    url: `https://example.org/uam.pdf#page=${10 + n}`,
    excerpt: `Passage ${n} text.`,
    ...extra,
  };
}

export function payload(sources: Source[], extra: Partial<AnswerPayload> = {}): AnswerPayload {
  return {
    answer: sources.length ? "An answer [1]." : "The documents don't cover that.",
    refused: !sources.length,
    uncited: false,
    sources,
    model: "test:free",
    first_model: "test:free",
    retried: false,
    suggest: [],
    asker: { id: "wztc", name: "Work Zone Traffic Control" },
    target: { id: "utilities", name: "Utilities" },
    steps: [],
    timing_ms: {},
    searched: { documents: 1, passages: 90 },
    ...extra,
  };
}

export function question(id: string, text: string, createdAt = new Date(1000)): ThreadMessageLike {
  return { id, role: "user", content: [{ type: "text", text }], createdAt };
}

export function answer(
  id: string,
  body: AnswerPayload | undefined,
  opts: { createdAt?: Date; running?: boolean } = {},
): ThreadMessageLike {
  const custom: AnswerMetadata = body ? { payload: body, targetId: body.target.id } : {};
  return {
    id,
    role: "assistant",
    content: [{ type: "text", text: body?.answer ?? "" }],
    createdAt: opts.createdAt ?? new Date(1000),
    status: opts.running ? { type: "running" } : { type: "complete", reason: "stop" },
    metadata: { custom },
  };
}
