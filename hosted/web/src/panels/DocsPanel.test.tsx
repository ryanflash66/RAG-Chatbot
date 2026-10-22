import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DIVISIONS } from "@/panels/fixtures";

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

// Fresh modules per test: the store, and TEAM, which DocsPanel reads from the URL on load.
async function setup(target?: string) {
  const { DocsPanel } = await import("@/panels/DocsPanel");
  const { useApp } = await import("@/state");
  act(() => {
    useApp.getState().setDivisions(DIVISIONS, 500);
    if (target) useApp.getState().setTarget(target);
  });
  render(<DocsPanel />);
  return useApp;
}

function group(name: RegExp) {
  return screen.getByRole("heading", { name }).closest("section")!;
}

describe("DocsPanel", () => {
  it("puts the asked division first, with checkboxes, and lists the others read-only", async () => {
    await setup("wztc");
    expect(document.querySelector("section")).toBe(group(/Asking Work Zone/));
    const asked = within(group(/Asking Work Zone/));
    expect(asked.getAllByRole("checkbox")).toHaveLength(2);
    expect(asked.getAllByRole("checkbox").every((cb) => (cb as HTMLInputElement).checked)).toBe(true);
    expect(asked.getByText("Searches 120 passages in 2 documents.")).toBeTruthy();
    expect(asked.getByText(/70 passages/)).toBeTruthy();
    const other = within(group(/Not asked Utilities/));
    expect(other.queryAllByRole("checkbox")).toHaveLength(0);
    expect(other.getByText(/90 passages/)).toBeTruthy();
    expect(other.getByRole("link").getAttribute("href")).toBe("https://example.org/uam.pdf");
  });

  it("unticks a document and keeps the last one ticked, saying why", async () => {
    const useApp = await setup("wztc");
    const asked = within(group(/Asking Work Zone/));
    const [tmp, flagger] = asked.getAllByRole("checkbox") as HTMLInputElement[];
    fireEvent.click(tmp);
    expect(tmp.checked).toBe(false);
    expect(useApp.getState().unticked.wztc).toEqual({ "tmp.pdf": true });
    expect(asked.getByText("Searches 50 passages in 1 of 2 documents.")).toBeTruthy();
    // The one left is marked as fixed, with the reason on hover and for screen readers.
    expect(flagger.getAttribute("aria-disabled")).toBe("true");
    expect(flagger.closest("label")!.title).toBe("At least one document has to be searched.");
    expect(document.getElementById(flagger.getAttribute("aria-describedby")!)!.textContent).toBe(
      "Untick a document to leave it out of the search.",
    );
    fireEvent.click(flagger);
    expect(flagger.checked).toBe(true);
    expect(useApp.getState().unticked.wztc).toEqual({ "tmp.pdf": true });
    expect(asked.getByText("At least one document has to be searched.").tagName).toBe("P");
    fireEvent.click(tmp);
    expect(tmp.checked).toBe(true);
    expect(flagger.hasAttribute("aria-disabled")).toBe(false);
    expect(asked.getByText("Untick a document to leave it out of the search.")).toBeTruthy();
  });

  it("explains why a division's only document is always searched", async () => {
    await setup("utilities");
    const asked = within(group(/Asking Utilities/));
    expect(asked.getByText("Utilities has one document for now, so it is always searched.")).toBeTruthy();
    expect(asked.getByRole("checkbox").getAttribute("aria-disabled")).toBe("true");
  });

  it("hides the upload placeholder without ?team=1", async () => {
    await setup();
    expect(screen.queryByRole("button", { name: "Upload documents" })).toBeNull();
  });

  it("shows the team-only upload placeholder with ?team=1, which uploads nothing", async () => {
    window.history.replaceState(null, "", "/?team=1");
    await setup();
    const button = screen.getByRole("button", { name: "Upload documents" });
    const note = document.getElementById(button.getAttribute("aria-controls")!)!;
    expect(note.hidden).toBe(true);
    fireEvent.click(button);
    expect(note.hidden).toBe(false);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(note.textContent).toContain("DAR-621");
  });
});
