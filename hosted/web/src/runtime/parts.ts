import type { ChatModelRunResult, ThreadAssistantMessagePart } from "@assistant-ui/react";
import type { AnswerMetadata, AnswerPayload, StepEvent } from "@/types";

// How the stream's events become the assistant message: each event folds into the
// answer so far, and the whole of it is yielded again (the local runtime replaces the
// message's content with every yield).

/** One event of /api/ask/stream, or the /api/ask reply as `done` when it fell back. */
export type AskEvent =
  | { type: "step"; step: StepEvent }
  | { type: "delta"; text: string }
  | { type: "replace"; text: string }
  | { type: "done"; payload: AnswerPayload };

export type AnswerSoFar = {
  /** One entry per step id, in the order the steps started, with its latest status. */
  steps: StepEvent[];
  text: string;
  payload?: AnswerPayload;
};

export const STEPS_PART = "steps";

export const NOTHING_YET: AnswerSoFar = { steps: [], text: "" };

function withStep(steps: StepEvent[], step: StepEvent): StepEvent[] {
  if (!step || !step.id) return steps;
  const at = steps.findIndex((s) => s.id === step.id);
  if (at < 0) return [...steps, step];
  const merged = { ...steps[at], ...step, label: step.label ?? steps[at].label };
  return steps.map((s, i) => (i === at ? merged : s));
}

/**
 * The steps once the answer is complete. Without any step events (the /api/ask
 * fallback) they come from the payload, the same steps the stream sends; a step
 * that never reported done is shown done.
 */
function finishedSteps(steps: StepEvent[], payload: AnswerPayload): StepEvent[] {
  if (!steps.length) {
    return (payload.steps ?? []).map((s) => ({ id: s.id, label: s.label, status: "done", ms: s.ms }));
  }
  return steps.map((s) => (s.status === "done" ? s : { ...s, status: "done", ms: s.ms ?? 0 }));
}

export function applyEvent(answer: AnswerSoFar, event: AskEvent): AnswerSoFar {
  switch (event.type) {
    case "step":
      return { ...answer, steps: withStep(answer.steps, event.step) };
    case "delta":
      return { ...answer, text: answer.text + (event.text ?? "") };
    case "replace":
      return { ...answer, text: event.text ?? "" };
    case "done":
      // The streamed text had no citations; the checked answer, renumbered 1..n, replaces it.
      return { steps: finishedSteps(answer.steps, event.payload), text: event.payload.answer, payload: event.payload };
  }
}

/**
 * The message for the answer so far: the steps (a data part), the text, and on `done`
 * a source part per cited passage. metadata.custom is the AnswerMetadata the panels
 * read (DAR-632); targetId is on it from the start, so history can filter by division.
 */
export function toResult(answer: AnswerSoFar, targetId: string): ChatModelRunResult {
  const content: ThreadAssistantMessagePart[] = [{ type: "data", name: STEPS_PART, data: answer.steps }];
  if (answer.text) content.push({ type: "text", text: answer.text });
  for (const source of answer.payload?.sources ?? []) {
    content.push({ type: "source", sourceType: "url", id: `source-${source.n}`, url: source.url, title: source.title });
  }
  const custom: AnswerMetadata = { steps: answer.steps, targetId };
  if (answer.payload) custom.payload = answer.payload;
  return { content, metadata: { custom } };
}
