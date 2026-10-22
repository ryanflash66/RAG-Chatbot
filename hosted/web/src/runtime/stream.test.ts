// @vitest-environment node
// (The runtime's tests need only Node's fetch, streams and TextDecoder, not a DOM.)
import { afterEach, describe, expect, it, vi } from "vitest";
import { payload } from "./fixtures";
import type { AskEvent } from "./parts";
import { ask, AskError, type AskRequest, CUT_OFF, UNREACHABLE, unexpected } from "./stream";

// api.ts reads document.baseURI, which Node doesn't have.
vi.mock("@/api", () => ({ apiPath: (name: string) => `/api/${name}` }));

const REQUEST: AskRequest = { question: "Who pays for a detour?", asker: "wztc", target: "utilities", history: [], documents: null };

const encoder = new TextEncoder();

function event(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** A text/event-stream reply whose body arrives in these chunks; `open` leaves it unfinished. */
function streamReply(chunks: string[], { open = false, signal }: { open?: boolean; signal?: AbortSignal } = {}) {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!open) controller.close();
      // As fetch does: aborting the request errors its body.
      signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    },
    cancel() {
      cancelled = true;
    },
  });
  const reply = new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  return { reply, wasCancelled: () => cancelled };
}

function jsonReply(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function mockFetch(...replies: (Response | Error | ((init: RequestInit) => Response))[]) {
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    const next = replies.shift();
    if (!next) throw new Error("unexpected request");
    if (next instanceof Error) throw next;
    return typeof next === "function" ? next(init) : next;
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function collect(signal = new AbortController().signal): Promise<AskEvent[]> {
  const events: AskEvent[] = [];
  for await (const e of ask(REQUEST, signal)) events.push(e);
  return events;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const STEP = { id: "read", label: "Reading the question…", status: "start" };
const DONE = payload();
const FULL = event("step", STEP) + event("delta", { text: "Flaggers" }) + event("done", DONE);

describe("ask over api/ask/stream", () => {
  it("posts the request and yields each event in order, however the body is chunked", async () => {
    // "…" is three bytes in UTF-8; splitting every 7 characters cuts through events and lines.
    const chunks = FULL.match(/[\s\S]{1,7}/g)!;
    const fetch = mockFetch(streamReply(chunks).reply);
    expect(await collect()).toEqual([
      { type: "step", step: STEP },
      { type: "delta", text: "Flaggers" },
      { type: "done", payload: DONE },
    ]);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/ask/stream");
    expect(JSON.parse(String(init.body))).toEqual(REQUEST);
  });

  it("throws the server's message from an error event", async () => {
    mockFetch(streamReply([event("step", STEP), event("error", { error: "The free model's daily limit is used up.", status: 429 })]).reply);
    await expect(collect()).rejects.toThrow(new AskError("The free model's daily limit is used up."));
  });

  it("throws, and never asks again, when the stream ends without an answer", async () => {
    const fetch = mockFetch(streamReply([event("step", STEP)]).reply);
    await expect(collect()).rejects.toThrow(CUT_OFF);
    expect(fetch).toHaveBeenCalledTimes(1);

    mockFetch(streamReply([]).reply);
    await expect(collect()).rejects.toThrow(UNREACHABLE);
  });

  it("throws, and never asks again, when the stream breaks", async () => {
    let pulls = 0;
    const broken = new ReadableStream<Uint8Array>({
      // The first read gets a step; the second fails, as a dropped connection does.
      pull(controller) {
        if (pulls++ === 0) controller.enqueue(encoder.encode(event("step", STEP)));
        else controller.error(new TypeError("network error"));
      },
    });
    const fetch = mockFetch(new Response(broken, { headers: { "Content-Type": "text/event-stream" } }));
    await expect(collect()).rejects.toThrow(CUT_OFF);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("throws when the request fails on the way, without a fallback", async () => {
    const fetch = mockFetch(new TypeError("Failed to fetch"));
    await expect(collect()).rejects.toThrow(UNREACHABLE);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("the api/ask fallback", () => {
  it.each([404, 405])("asks api/ask once when the stream answers %i", async (status) => {
    const fetch = mockFetch(new Response("Not Found", { status }), jsonReply(DONE));
    expect(await collect()).toEqual([{ type: "done", payload: DONE }]);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/ask/stream", "/api/ask"]);
  });

  it("asks api/ask when the reply is neither a stream nor JSON", async () => {
    const fetch = mockFetch(new Response("<html>Bad gateway</html>", { status: 502 }), jsonReply(DONE));
    expect(await collect()).toEqual([{ type: "done", payload: DONE }]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("does not fall back on the checks' JSON errors", async () => {
    const fetch = mockFetch(jsonReply({ error: "Too many questions in a short time." }, 429));
    await expect(collect()).rejects.toThrow("Too many questions in a short time.");
    expect(fetch).toHaveBeenCalledTimes(1);

    const again = mockFetch(jsonReply({ detail: [{ msg: "too long" }] }, 422));
    await expect(collect()).rejects.toThrow(unexpected(422));
    expect(again).toHaveBeenCalledTimes(1);
  });

  it("throws api/ask's error", async () => {
    mockFetch(new Response("", { status: 404 }), jsonReply({ error: "The model took too long." }, 504));
    await expect(collect()).rejects.toThrow("The model took too long.");
  });
});

describe("stopping", () => {
  it("throws an AbortError and cancels the stream when the signal aborts mid-answer", async () => {
    const controller = new AbortController();
    let stream: ReturnType<typeof streamReply> | undefined;
    const fetch = mockFetch((init) => {
      stream = streamReply([event("step", STEP)], { open: true, signal: init.signal ?? undefined });
      return stream.reply;
    });
    const events: AskEvent[] = [];
    const run = (async () => {
      for await (const e of ask(REQUEST, controller.signal)) {
        events.push(e);
        controller.abort();
      }
    })();
    await expect(run).rejects.toMatchObject({ name: "AbortError" });
    expect(events).toEqual([{ type: "step", step: STEP }]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it("throws an AbortError when stopped before the reply arrives", async () => {
    const controller = new AbortController();
    controller.abort();
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(collect(controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("cancels the stream when the runtime stops reading", async () => {
    const stream = streamReply([event("step", STEP)], { open: true });
    mockFetch(stream.reply);
    for await (const e of ask(REQUEST, new AbortController().signal)) {
      expect(e.type).toBe("step");
      break;
    }
    expect(stream.wasCancelled()).toBe(true);
  });
});
