import type { ThreadMessageLike } from "@assistant-ui/react";
import type { HistoryMessage } from "./history";

// The conversation kept in sessionStorage, so a reload (or a phone switching apps)
// doesn't lose it, as the old page's chat.js did: per tab, gone when the tab closes.

export const STORE_KEY = "ncdot-qa-thread-v2";
/** The old page kept the last 40 exchanges; a message here is half of one. */
export const STORE_MESSAGES = 80;
export const INTERRUPTED = "The page was reloaded before this answer finished. Please ask again.";

export type SavedThread = { messages: ThreadMessageLike[]; asker: string | null; target: string | null };

type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  content: unknown;
  metadata: { custom: Record<string, unknown> };
  status?: { type: string; reason?: string; error?: unknown };
};

/** The thread as it can be stored: finished messages, a running answer marked interrupted. */
export function toStored(messages: readonly HistoryMessage[]): StoredMessage[] {
  const kept = messages.slice(-STORE_MESSAGES);
  // Start at a question, so the first stored answer still has the question it answers.
  const start = kept[0]?.role === "assistant" ? 1 : 0;
  return kept.slice(start).map((m) => {
    const message = m as HistoryMessage & { id: string; role: "user" | "assistant"; status?: StoredMessage["status"] };
    const stored: StoredMessage = { id: message.id, role: message.role, content: message.content, metadata: { custom: message.metadata.custom } };
    if (message.role === "assistant") {
      const running = message.status?.type === "running" || message.status?.type === "requires-action";
      // A question still being answered when the page was reloaded comes back as a failed
      // answer with Try again, where it was asked (the old page's INTERRUPTED).
      stored.status = running ? { type: "incomplete", reason: "error", error: INTERRUPTED } : message.status;
    }
    return stored;
  });
}

export function save(state: { messages: readonly HistoryMessage[]; asker: string | null; target: string | null }): void {
  // Storage can be full, blocked or disabled (private windows); the thread then works
  // as usual and just isn't there after a reload.
  try {
    if (!state.messages.length) {
      sessionStorage.removeItem(STORE_KEY);
      return;
    }
    sessionStorage.setItem(STORE_KEY, JSON.stringify({ ...state, messages: toStored(state.messages) }));
  } catch {
    try {
      sessionStorage.removeItem(STORE_KEY);
    } catch {
      /* blocked: nothing was kept */
    }
  }
}

/** The saved thread, or an empty one when there is none or it can't be read. */
export function load(): SavedThread {
  const empty: SavedThread = { messages: [], asker: null, target: null };
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) ?? "null");
    if (!saved || !Array.isArray(saved.messages)) return empty;
    const messages = saved.messages.filter(usable) as ThreadMessageLike[];
    return {
      messages,
      asker: typeof saved.asker === "string" ? saved.asker : null,
      target: typeof saved.target === "string" ? saved.target : null,
    };
  } catch {
    return empty;
  }
}

function usable(m: unknown): boolean {
  const message = m as Partial<StoredMessage> | null;
  return (
    !!message &&
    typeof message.id === "string" &&
    (message.role === "user" || message.role === "assistant") &&
    Array.isArray(message.content) &&
    !!message.metadata &&
    typeof message.metadata.custom === "object"
  );
}
