// @vitest-environment node
import type { ChatModelRunOptions, ChatModelRunResult, ThreadMessage } from "@assistant-ui/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useApp } from "@/state";
import type { Division } from "@/types";
import { answerAdapter } from "./adapter";
import { answer, payload, question } from "./fixtures";

vi.mock("@/api", () => ({ apiPath: (name: string) => `/api/${name}` }));

const DIVISIONS: Division[] = [
  { id: "wztc", name: "Work Zone Traffic Control", unit: "", examples: [], passages: 500, documents: [
    { file: "wztc/a.pdf", title: "A", url: "", passages: 300 },
    { file: "wztc/b.pdf", title: "B", url: "", passages: 200 },
  ] },
  { id: "utilities", name: "Utilities", unit: "", examples: [], passages: 400, documents: [
    { file: "utilities/manual.pdf", title: "Manual", url: "", passages: 400 },
  ] },
];

function sse(...events: [string, unknown][]): Response {
  const text = events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(text, { headers: { "Content-Type": "text/event-stream" } });
}

async function run(messages: unknown[]): Promise<ChatModelRunResult[]> {
  const results: ChatModelRunResult[] = [];
  // run() reads only these two of its options.
  const options = { messages: messages as ThreadMessage[], abortSignal: new AbortController().signal } as unknown as ChatModelRunOptions;
  const generator = answerAdapter.run(options) as AsyncGenerator<ChatModelRunResult, void>;
  for await (const result of generator) results.push(result);
  return results;
}

afterEach(() => vi.unstubAllGlobals());

describe("answerAdapter", () => {
  it("asks the store's divisions with the thread's history and ticked documents", async () => {
    useApp.getState().setDivisions(DIVISIONS, 500);
    useApp.getState().setTarget("wztc");
    useApp.getState().toggleDocument("wztc", "wztc/b.pdf");
    useApp.getState().showAnswer("older-answer");
    const done = payload();
    const fetch = vi.fn(async () => sse(["step", { id: "read", label: "Reading", status: "start" }], ["delta", { text: "Flag" }], ["done", done]));
    vi.stubGlobal("fetch", fetch);

    const results = await run([
      question("Where do flaggers stand?"),
      answer({ targetId: "wztc", payload: payload({ answer: "Ahead of the work [1]." }) }),
      question("And at night?"),
    ]);

    expect(useApp.getState().activeAnswerId).toBeNull();
    expect(JSON.parse(String((fetch.mock.calls[0] as unknown as [string, RequestInit])[1].body))).toEqual({
      question: "And at night?",
      asker: "wztc",
      target: "wztc",
      history: [{ question: "Where do flaggers stand?", answer: "Ahead of the work." }],
      documents: ["wztc/a.pdf"],
      refused_by: [], // a typed question; only an "Ask … instead" carries divisions
    });
    // One yield before the first event, then one per event.
    expect(results).toHaveLength(4);
    expect(results[0].metadata?.custom).toEqual({ steps: [], targetId: "wztc" });
    expect(results[2].content?.find((p) => p.type === "text")).toEqual({ type: "text", text: "Flag" });
    const last = results[3];
    expect(last.content?.find((p) => p.type === "text")).toEqual({ type: "text", text: done.answer });
    expect(last.metadata?.custom).toMatchObject({ payload: done, targetId: "wztc" });
  });
});
