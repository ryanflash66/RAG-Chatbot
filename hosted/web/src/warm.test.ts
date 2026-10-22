import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DIVISIONS } from "@/panels/fixtures";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers({ toFake: ["Date"] });
  fetchMock = vi.fn(() => Promise.resolve(new Response(null)));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("warmUp", () => {
  it("posts api/warm at most once per 30 s", async () => {
    const { warmUp } = await import("@/warm");
    warmUp();
    warmUp(); // still in flight
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]).toEqual(["/api/warm", { method: "POST" }]);
    await settle();
    vi.advanceTimersByTime(29_000);
    warmUp();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1_000);
    warmUp();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("waits out the cooldown after a failed attempt too", async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new Error("offline")));
    const { warmUp } = await import("@/warm");
    warmUp();
    await settle();
    warmUp();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("starts once the divisions load", async () => {
    await import("@/warm");
    const { useApp } = await import("@/state");
    useApp.getState().setTarget("utilities");
    expect(fetchMock).not.toHaveBeenCalled();
    useApp.getState().setDivisions(DIVISIONS, 500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
