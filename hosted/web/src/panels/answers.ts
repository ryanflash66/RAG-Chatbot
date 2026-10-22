import type { ThreadMessage } from "@assistant-ui/react";
import type { AnswerMetadata, Source } from "@/types";

// Which answer the right panel shows, read from assistant-ui's thread, where the runtime
// adapter (DAR-631) leaves each answer's payload in its message's metadata.custom.

export type ShownAnswer = {
  id: string;
  question: string;
  sources: Source[];
};

function payloadOf(message: ThreadMessage) {
  return (message.metadata.custom as AnswerMetadata | undefined)?.payload;
}

function isFinished(message: ThreadMessage): boolean {
  return message.role === "assistant" && message.status?.type === "complete" && !!payloadOf(message);
}

/** The text of the question an answer replies to: the user message before it. */
function questionBefore(messages: readonly ThreadMessage[], index: number): string {
  for (let i = index - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "user") continue;
    return m.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .join(" ")
      .trim();
  }
  return "";
}

/**
 * The answer picked with a citation click or showAnswer (activeId, picked at activeAt), or
 * the newest finished answer when none is picked, the picked one has left the thread, or a
 * newer answer started after the pick: the old page switched to each answer as it finished,
 * and this keeps doing that whether or not the adapter calls showAnswer. Only finished
 * answers with a payload count, so a reply still streaming or an error leaves the panel on
 * the last real answer.
 */
export function pickAnswer(
  messages: readonly ThreadMessage[],
  activeId: string | null,
  activeAt: number,
): ShownAnswer | null {
  let newest = -1;
  let picked = -1;
  messages.forEach((m, i) => {
    if (!isFinished(m)) return;
    newest = i;
    if (m.id === activeId) picked = i;
  });
  if (newest < 0) return null;
  const startedAfterPick = +messages[newest].createdAt > activeAt;
  const index = picked >= 0 && !startedAfterPick ? picked : newest;
  const message = messages[index];
  const sources = payloadOf(message)?.sources;
  return {
    id: message.id,
    question: questionBefore(messages, index),
    sources: Array.isArray(sources) ? sources : [],
  };
}

/** "PDF page 12" or "PDF pages 12–13", or null when the page is unknown. */
export function pagesText(source: Source): string | null {
  if (!source.page) return null;
  return source.page_end && source.page_end !== source.page
    ? `PDF pages ${source.page}–${source.page_end}`
    : `PDF page ${source.page}`;
}
