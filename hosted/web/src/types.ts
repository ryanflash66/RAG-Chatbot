// The shapes the server sends (hosted/index.py). They are the contract between the
// runtime adapter (DAR-631), which stores each answer's payload in its message
// metadata, and the panels (DAR-632), which read it.

export type DivisionDocument = {
  file: string;
  title: string;
  url: string;
  passages: number;
};

export type Division = {
  id: string;
  name: string;
  unit: string;
  documents: DivisionDocument[];
  examples: string[];
  passages: number;
};

/** GET /api/divisions */
export type DivisionsReply = {
  divisions: Division[];
  max_question_chars: number;
};

export type Source = {
  n: number;
  division: string;
  title: string;
  page: number | null;
  page_end: number | null;
  section: string | null;
  url: string;
  excerpt: string;
};

export type StepEvent = {
  id: "read" | "search" | "rerank" | "write" | "check" | "retry" | "suggest" | string;
  label?: string;
  /** "pending": listed at the start of the stream, not started yet (DAR-636). */
  status: "pending" | "start" | "done";
  ms?: number;
};

/** POST /api/ask's reply, and the stream's `done` event. */
export type AnswerPayload = {
  answer: string;
  refused: boolean;
  uncited: boolean;
  sources: Source[];
  model: string | null;
  first_model: string | null;
  retried: boolean;
  suggest: { id: string; name: string }[];
  asker: { id: string; name: string };
  target: { id: string; name: string };
  steps: { id: string; label: string; ms: number }[];
  timing_ms: Record<string, number>;
  searched: { documents: number; passages: number };
};

/** What an assistant message carries in metadata.custom (written by the adapter, DAR-631). */
export type AnswerMetadata = {
  payload?: AnswerPayload;
  steps?: StepEvent[];
  targetId?: string;
  /** The asker's division when the question was sent, for "for a colleague in …". */
  askerId?: string;
};
