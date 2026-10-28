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
  /** One entry per step id, in the order the steps were listed or started, with its latest status. */
  steps: StepEvent[];
  text: string;
  payload?: AnswerPayload;
};

export const STEPS_PART = "steps";

export const NOTHING_YET: AnswerSoFar = { steps: [], text: "" };

function withStep(steps: StepEvent[], step: StepEvent): StepEvent[] {
  if (!step || !step.id) return steps;
  const at = steps.findIndex((s) => s.id === step.id);
  if (at >= 0 && step.status === "pending") return steps; // a step never goes back from running or done
  const listed = at < 0 ? [...steps, step] : steps.map((s, i) => (i === at ? { ...s, ...step, label: step.label ?? s.label } : s));
  if (step.status === "pending") return listed;
  // The steps run in the order listed, so one still pending before a step that started
  // was skipped (the reranker skips a single passage): it leaves the list (DAR-636).
  const index = at < 0 ? listed.length - 1 : at;
  return listed.filter((s, i) => i >= index || s.status !== "pending");
}

/**
 * The steps once the answer is complete. Without any step events (the /api/ask
 * fallback) they come from the payload, the same steps the stream sends. A step
 * that started but never reported done is shown done; one still pending never ran
 * (the reranker skips a single passage) and is dropped, as the old page does (DAR-636).
 */
function finishedSteps(steps: StepEvent[], payload: AnswerPayload): StepEvent[] {
  const finished = new Map((payload.steps ?? []).map((s) => [s.id, s]));
  if (!steps.length) {
    return (payload.steps ?? []).map((s) => ({ id: s.id, label: s.label, status: "done", ms: s.ms }));
  }
  return steps
    .filter((s) => s.status !== "pending" || finished.has(s.id))
    .map((s) => (s.status === "done" ? s : { ...s, status: "done", ms: finished.get(s.id)?.ms ?? s.ms ?? 0 }));
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
export function toResult(answer: AnswerSoFar, targetId: string, askerId?: string): ChatModelRunResult {
  const content: ThreadAssistantMessagePart[] = [{ type: "data", name: STEPS_PART, data: answer.steps }];
  if (answer.text) content.push({ type: "text", text: answer.text });
  for (const source of answer.payload?.sources ?? []) {
    content.push({ type: "source", sourceType: "url", id: `source-${source.n}`, url: source.url, title: source.title });
  }
  const custom: AnswerMetadata = { steps: answer.steps, targetId };
  if (askerId) custom.askerId = askerId;
  if (answer.payload) custom.payload = answer.payload;
  return { content, metadata: { custom } };
}
