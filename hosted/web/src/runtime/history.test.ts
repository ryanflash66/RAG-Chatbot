// @vitest-environment node
import { describe, expect, it } from "vitest";
import { answer, payload, question } from "./fixtures";
import { buildHistory, carryForSuggestion, clip, HISTORY_ANSWER_CHARS, turnsFor } from "./history";

const wztc = (text: string) => answer({ targetId: "wztc", payload: payload({ answer: text }) });

describe("buildHistory", () => {
  it("sends the last 3 answered turns to the same division, oldest first, without [n]", () => {
    const messages = [
      question("q1"),
      wztc("a1 [1]"),
      question("q2"),
      wztc("a2 [1] [2]"),
      question("q3"),
      wztc("a3"),
      question("q4"),
      wztc("a4 [3]."),
    ];
    expect(buildHistory(messages, "wztc")).toEqual([
      { question: "q2", answer: "a2" },
      { question: "q3", answer: "a3" },
      { question: "q4", answer: "a4." },
    ]);
  });

  it("skips refusals, failed or stopped answers and other divisions' answers", () => {
    const messages = [
      question("kept"),
      wztc("kept answer"),
      question("refused"),
      answer({ targetId: "wztc", payload: payload({ refused: true, answer: "Not in the documents." }) }),
      question("failed"),
      answer({ targetId: "wztc", steps: [] }, "incomplete"),
      question("stopped"),
      answer({ targetId: "wztc", payload: payload({ answer: "partial" }) }, "incomplete"),
      question("other division"),
      answer({ targetId: "utilities", payload: payload({ answer: "utilities answer" }) }),
    ];
    expect(buildHistory(messages, "wztc")).toEqual([{ question: "kept", answer: "kept answer" }]);
  });

  it("looks no further back than a question that started a topic", () => {
    const messages = [
      question("before"),
      wztc("before answer"),
      question("asked instead", { carry: [{ question: "before", answer: "" }] }),
      wztc("instead answer"),
      question("follow-up"),
      wztc("follow-up answer"),
    ];
    expect(buildHistory(messages, "wztc")).toEqual([
      { question: "asked instead", answer: "instead answer" },
      { question: "follow-up", answer: "follow-up answer" },
    ]);
  });

  it("clips a long answer to about 1,500 characters at a word", () => {
    const long = "word ".repeat(600);
    const [turn] = buildHistory([question("q"), wztc(long)], "wztc");
    expect(turn.answer.length).toBeLessThanOrEqual(HISTORY_ANSWER_CHARS + 2);
    expect(turn.answer.endsWith("word …")).toBe(true);
  });
});

describe("clip", () => {
  it("leaves short text alone and squeezes spaces", () => {
    expect(clip("  a   b\tc ", 10)).toBe("a b c");
  });

  it("cuts mid-word when no space is near the end", () => {
    expect(clip("x".repeat(20), 10)).toBe("xxxxxxxxxx …");
  });
});

describe("turnsFor", () => {
  const thread = [question("q1"), wztc("a1")];

  it("sends the thread's turns with a typed question", () => {
    expect(turnsFor([...thread, question("q2")], "wztc")).toEqual([{ question: "q1", answer: "a1" }]);
  });

  it("filters by the division being asked now", () => {
    expect(turnsFor([...thread, question("q2")], "utilities")).toEqual([]);
  });

  it("sends a carried turn instead, or nothing for a standalone question", () => {
    const carry = [{ question: "earlier", answer: "" }];
    expect(turnsFor([...thread, question("q2", { carry })], "wztc")).toEqual(carry);
    expect(turnsFor([...thread, question("q2", { standalone: true })], "wztc")).toEqual([]);
  });
});

describe("carryForSuggestion", () => {
  it("carries the previous question the refused one was searched with", () => {
    const messages = [
      question("Who pays for a detour?"),
      wztc("The contractor [1]."),
      question("And for the signs?"),
      answer({ targetId: "wztc", payload: payload({ refused: true, answer: "Not covered." }) }),
    ];
    expect(carryForSuggestion(messages, 3)).toEqual([{ question: "Who pays for a detour?", answer: "" }]);
  });

  it("carries nothing for a refused first question", () => {
    const messages = [question("Who pays?"), answer({ targetId: "wztc", payload: payload({ refused: true }) })];
    expect(carryForSuggestion(messages, 1)).toEqual([]);
  });
});
