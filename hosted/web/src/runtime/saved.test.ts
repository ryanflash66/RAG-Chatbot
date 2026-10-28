// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { answer, payload, question } from "./fixtures";
import { INTERRUPTED, load, save, STORE_KEY, STORE_MESSAGES, toStored } from "./saved";

const withId = <T extends object>(m: T, id: string) => ({ ...m, id });

describe("saved thread", () => {
  beforeEach(() => sessionStorage.clear());

  it("comes back after a reload with the divisions it was asked of", () => {
    const messages = [withId(question("q1"), "u1"), withId(answer({ targetId: "wztc", payload: payload() }), "a1")];
    save({ messages, asker: "utilities", target: "wztc" });

    const saved = load();
    expect(saved.asker).toBe("utilities");
    expect(saved.target).toBe("wztc");
    expect(saved.messages.map((m) => [m.id, m.role])).toEqual([["u1", "user"], ["a1", "assistant"]]);
    expect(saved.messages[1].metadata?.custom).toMatchObject({ targetId: "wztc" });
  });

  it("brings an answer that was still running back as interrupted", () => {
    const running = withId(answer({ targetId: "wztc", steps: [] }, "running"), "a1");
    const [, stored] = toStored([withId(question("q1"), "u1"), running]);
    expect(stored.status).toEqual({ type: "incomplete", reason: "error", error: INTERRUPTED });
  });

  it("keeps the last messages, starting at a question", () => {
    const many = Array.from({ length: STORE_MESSAGES + 3 }, (_, i) =>
      i % 2 ? withId(answer({ targetId: "wztc", payload: payload() }), `a${i}`) : withId(question(`q${i}`), `u${i}`),
    );
    const stored = toStored(many);
    expect(stored[0].role).toBe("user");
    expect(stored.length).toBeLessThanOrEqual(STORE_MESSAGES);
  });

  it("is empty after New chat and when what was stored can't be read", () => {
    save({ messages: [], asker: null, target: null });
    expect(sessionStorage.getItem(STORE_KEY)).toBeNull();
    sessionStorage.setItem(STORE_KEY, "{not json");
    expect(load().messages).toEqual([]);
  });
});
