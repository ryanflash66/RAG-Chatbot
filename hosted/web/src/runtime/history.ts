import type { AnswerMetadata } from "@/types";

// The earlier turns a question is sent with, built from the thread's messages with the
// old page's rules (public/js/chat.js history()).

/** A follow-up carries the last few answered turns; the server keeps only 3 as well. */
export const HISTORY_TURNS = 3;
/**
 * An earlier answer only shows what "it" refers to (the facts come from the new
 * passages), so a long one is clipped; the server's limit per answer is 4,000.
 */
export const HISTORY_ANSWER_CHARS = 1500;

export type Turn = { question: string; answer: string };

/**
 * What a user message carries in metadata.custom. A message typed in the composer has
 * neither field. `carry`: these turns are sent instead of the thread's ("Ask … instead"
 * sends the question the refused one was searched with). `standalone`: no earlier turns.
 * Either way the question starts a topic, and later follow-ups look no further back.
 * `refusedBy`: the divisions that refused this question before an "Ask … instead";
 * the server won't suggest them again.
 */
export type QuestionMetadata = { carry?: Turn[]; standalone?: boolean; refusedBy?: string[] };

/** The parts of a thread message the history reads; assistant-ui's ThreadMessage fits it. */
export type HistoryMessage = {
  readonly role: string;
  readonly content: readonly { readonly type: string; readonly text?: string }[];
  readonly status?: { readonly type: string } | undefined;
  readonly metadata: { readonly custom: Record<string, unknown> };
};

export function messageText(message: HistoryMessage): string {
  return message.content
    .map((part) => (part.type === "text" ? (part.text ?? "") : ""))
    .join("\n")
    .trim();
}

/** [n] markers number the old answer's sources, not the new passages, so they go. */
export function stripCitations(text: string): string {
  return String(text).replace(/\s*\[\d+\]/g, "");
}

export function clip(text: string, max: number): string {
  text = text.replace(/[ \t]+/g, " ").trim();
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return (space > max * 0.8 ? cut.slice(0, space) : cut) + " …";
}

function questionMeta(message: HistoryMessage): QuestionMetadata {
  return message.metadata.custom as QuestionMetadata;
}

function startsTopic(message: HistoryMessage): boolean {
  const meta = questionMeta(message);
  return meta.standalone === true || Array.isArray(meta.carry);
}

/**
 * The finished exchanges before a question that it is sent with, oldest first. Only
 * answered turns with the division being asked count: a refusal or an error holds
 * nothing to refer back to, and another division's answer came from documents this
 * question won't search. A question that started a topic (an "Ask … instead") ends
 * the look back, whichever division it asked.
 */
export function buildHistory(previous: readonly HistoryMessage[], target: string): Turn[] {
  const turns: Turn[] = [];
  for (let i = previous.length - 1; i >= 0 && turns.length < HISTORY_TURNS; i--) {
    const question = previous[i];
    if (question.role !== "user") continue;
    const reply = previous[i + 1];
    const meta = reply?.role === "assistant" ? (reply.metadata.custom as AnswerMetadata) : undefined;
    const payload = meta?.payload;
    if (reply?.status?.type === "complete" && meta?.targetId === target && payload && !payload.refused) {
      turns.unshift({
        question: messageText(question),
        answer: clip(stripCitations(payload.answer), HISTORY_ANSWER_CHARS),
      });
    }
    if (startsTopic(question)) break;
  }
  return turns;
}

/** The turns to send with the newest question, the last of `messages` (the run's messages). */
export function turnsFor(messages: readonly HistoryMessage[], target: string): Turn[] {
  const last = messages.at(-1);
  if (!last || last.role !== "user") return [];
  const meta = questionMeta(last);
  if (Array.isArray(meta.carry)) return meta.carry;
  if (meta.standalone) return [];
  return buildHistory(messages.slice(0, -1), target);
}

/**
 * The server suggests another division after searching it with the same text as the
 * refused question: the previous question plus this one. Asking there sends that
 * previous question again, without its answer (which came from the first division's
 * documents), so the new search keeps the topic. `index` is the refused answer's.
 */
export function carryForSuggestion(messages: readonly HistoryMessage[], index: number): Turn[] {
  const answer = messages[index];
  const target = (answer?.metadata.custom as AnswerMetadata | undefined)?.targetId;
  if (!target || index < 1) return [];
  const turns = turnsFor(messages.slice(0, index), target);
  const prior = turns.at(-1)?.question ?? "";
  return prior ? [{ question: prior, answer: "" }] : [];
}

/**
 * The divisions to send as refused_by when the refused answer at `index` is asked
 * somewhere else: the ones its own question carried, plus the division that refused it.
 */
export function refusedBySoFar(messages: readonly HistoryMessage[], index: number): string[] {
  const target = (messages[index]?.metadata.custom as AnswerMetadata | undefined)?.targetId;
  const earlier = refusedByOf(index >= 1 ? messages[index - 1] : undefined);
  return target && !earlier.includes(target) ? [...earlier, target] : earlier;
}

/** The refused_by a question is sent with: what its metadata carries, else none. */
export function refusedByOf(message: HistoryMessage | undefined): string[] {
  const refused = message?.role === "user" ? questionMeta(message).refusedBy : undefined;
  return Array.isArray(refused) ? refused : [];
}
