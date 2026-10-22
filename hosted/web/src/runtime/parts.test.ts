// @vitest-environment node
import { describe, expect, it } from "vitest";
import { payload } from "./fixtures";
import { type AnswerSoFar, applyEvent, type AskEvent, NOTHING_YET, STEPS_PART, toResult } from "./parts";

function fold(events: AskEvent[]): AnswerSoFar {
  return events.reduce(applyEvent, NOTHING_YET);
}

describe("applyEvent", () => {
  it("keeps one entry per step, with its label from the start and its time from done", () => {
    const answer = fold([
      { type: "step", step: { id: "read", label: "Reading the question", status: "start" } },
      { type: "step", step: { id: "search", label: "Searching 412 passages", status: "start" } },
      { type: "step", step: { id: "read", status: "done", ms: 40 } },
    ]);
    expect(answer.steps).toEqual([
      { id: "read", label: "Reading the question", status: "done", ms: 40 },
      { id: "search", label: "Searching 412 passages", status: "start" },
    ]);
  });

  it("adds deltas and starts over on replace", () => {
    expect(fold([{ type: "delta", text: "Flag" }, { type: "delta", text: "gers" }]).text).toBe("Flaggers");
    expect(fold([{ type: "delta", text: "first try" }, { type: "replace", text: "" }, { type: "delta", text: "second" }]).text).toBe(
      "second",
    );
  });

  it("replaces the streamed text with the checked answer on done and finishes every step", () => {
    const done = payload();
    const answer = fold([
      { type: "step", step: { id: "read", label: "Reading", status: "start" } },
      { type: "delta", text: "Flaggers stand 100 ft ahead of the work." },
      { type: "done", payload: done },
    ]);
    expect(answer.text).toBe(done.answer);
    expect(answer.payload).toBe(done);
    expect(answer.steps).toEqual([{ id: "read", label: "Reading", status: "done", ms: 0 }]);
  });

  it("takes the steps from the payload when none were streamed (the api/ask fallback)", () => {
    const answer = fold([{ type: "done", payload: payload() }]);
    expect(answer.steps).toEqual([
      { id: "read", label: "Reading the question", status: "done", ms: 40 },
      { id: "write", label: "Writing the answer", status: "done", ms: 3200 },
    ]);
  });
});

describe("toResult", () => {
  it("is the steps part alone, with the division, before anything arrived", () => {
    expect(toResult(NOTHING_YET, "wztc")).toEqual({
      content: [{ type: "data", name: STEPS_PART, data: [] }],
      metadata: { custom: { steps: [], targetId: "wztc" } },
    });
  });

  it("gives the steps, the text and a url source per cited passage, with the payload in metadata", () => {
    const done = payload();
    const answer = fold([{ type: "done", payload: done }]);
    const result = toResult(answer, "wztc");
    expect(result.content).toEqual([
      { type: "data", name: STEPS_PART, data: answer.steps },
      { type: "text", text: done.answer },
      {
        type: "source",
        sourceType: "url",
        id: "source-1",
        url: "https://example.org/wztc.pdf#page=12",
        title: "Work Zone Manual",
      },
    ]);
    expect(result.metadata?.custom).toEqual({ payload: done, steps: answer.steps, targetId: "wztc" });
  });

  it("gives a refusal no sources", () => {
    const answer = fold([{ type: "done", payload: payload({ refused: true, answer: "Not covered.", sources: [] }) }]);
    expect(toResult(answer, "wztc").content?.map((part) => part.type)).toEqual(["data", "text"]);
  });
});
