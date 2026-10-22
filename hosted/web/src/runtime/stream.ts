import { apiPath } from "@/api";
import type { AnswerPayload, StepEvent } from "@/types";
import type { Turn } from "./history";
import type { AskEvent } from "./parts";
import { sseParser } from "./sse";

// The answer to one question from POST api/ask/stream (server-sent events: step, delta,
// replace, done, error), ported from public/js/api.js. It falls back to POST api/ask
// only when the server answers that it has no stream (404 or 405, or a reply that is
// neither a stream nor JSON). A stream that breaks, or a request that fails on the way,
// throws: the server may already be answering it, and asking again would spend a second
// answer of the free model's daily quota. The thread shows the error and its Reload
// asks again only when the visitor chooses to.

export type AskRequest = {
  question: string;
  asker: string;
  target: string;
  history: Turn[];
  /** The target's ticked document files, or null when all of them are ticked. */
  documents: string[] | null;
};

export const UNREACHABLE = "Couldn't reach the server. Check your connection and try again.";
export const CUT_OFF = "The answer was cut off before it finished. Please ask again.";

/** A failed answer; its message is fit to show (the server's own, or one of the above). */
export class AskError extends Error {
  name = "AskError";
}

export function unexpected(status: number): string {
  return `The server returned an unexpected response (${status}).`;
}

// The local runtime treats an AbortError as the visitor's Stop, not as a failure.
function stopIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException("The question was stopped.", "AbortError");
}

async function post(name: string, request: AskRequest, signal: AbortSignal): Promise<Response> {
  try {
    return await fetch(apiPath(name), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
  } catch {
    stopIfAborted(signal);
    throw new AskError(UNREACHABLE);
  }
}

async function jsonOrNull(res: Response): Promise<Record<string, unknown> | null> {
  try {
    const data: unknown = await res.json();
    return data && typeof data === "object" ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function errorOf(data: Record<string, unknown> | null): string | null {
  return data && typeof data.error === "string" ? data.error : null;
}

/** The answer from POST api/ask: the fallback when the stream can't be read. */
async function askOnce(request: AskRequest, signal: AbortSignal): Promise<AnswerPayload> {
  const res = await post("ask", request, signal);
  const data = await jsonOrNull(res);
  stopIfAborted(signal);
  const error = errorOf(data);
  if (error) throw new AskError(error);
  // A 422 from request validation is JSON too ({detail}), but not an answer.
  if (!res.ok || !data) throw new AskError(unexpected(res.status));
  return data as unknown as AnswerPayload;
}

/**
 * The events of one answer, ending with `done`; any failure throws AskError (or an
 * AbortError once `signal` aborts). Breaking out of the loop cancels the stream.
 */
export async function* ask(request: AskRequest, signal: AbortSignal): AsyncGenerator<AskEvent, void> {
  const res = await post("ask/stream", request, signal);
  const type = res.headers.get("Content-Type") ?? "";
  if (!type.includes("text/event-stream")) {
    const data = await jsonOrNull(res);
    stopIfAborted(signal);
    // The checks (a bad question, the rate limit) answer with JSON, as api/ask does: no fallback.
    const error = errorOf(data);
    if (error) throw new AskError(error);
    // No stream here (an older server: 404 or 405, or a page that isn't JSON): ask api/ask instead.
    if (!data || res.ok || res.status === 404 || res.status === 405) {
      yield { type: "done", payload: await askOnce(request, signal) };
      return;
    }
    throw new AskError(unexpected(res.status)); // e.g. 422: api/ask would refuse the same request
  }

  const queue: AskEvent[] = [];
  let events = 0;
  let settled = false;
  let failure: string | null = null;
  const parser = sseParser((name, text) => {
    if (settled) return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text);
    } catch {
      return;
    }
    events++;
    if (name === "step") queue.push({ type: "step", step: data as unknown as StepEvent });
    else if (name === "delta") queue.push({ type: "delta", text: String(data.text ?? "") });
    else if (name === "replace") queue.push({ type: "replace", text: String(data.text ?? "") });
    else if (name === "done") {
      settled = true;
      queue.push({ type: "done", payload: data as unknown as AnswerPayload });
    } else if (name === "error") {
      settled = true;
      failure = errorOf(data) ?? unexpected(Number(data.status) || 500);
    }
  });
  // Once the stream request may have reached the server it is never sent again to api/ask:
  // the server could already be answering it, and a second copy would spend another model
  // call and rate-limit slot.
  const broken = () => new AskError(events ? CUT_OFF : UNREACHABLE);

  if (!res.body) {
    // No readable stream in this browser: the events all arrive at the end, still from this one request.
    let text: string;
    try {
      text = await res.text();
    } catch {
      stopIfAborted(signal);
      throw broken();
    }
    parser.push(text);
    parser.end();
    yield* queue;
    if (failure !== null) throw new AskError(failure);
    if (!settled) throw broken();
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  try {
    for (;;) {
      let part: ReadableStreamReadResult<Uint8Array>;
      try {
        part = await reader.read();
      } catch {
        stopIfAborted(signal);
        throw broken();
      }
      if (part.done) {
        parser.push(decoder.decode());
        parser.end();
      } else {
        // stream: true keeps a multi-byte character split across chunks (the "…" in a label) whole.
        parser.push(decoder.decode(part.value, { stream: true }));
      }
      while (queue.length) yield queue.shift()!;
      if (failure !== null) throw new AskError(failure);
      if (settled) return;
      if (part.done) throw broken();
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
