import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { AssistantRuntimeProvider, useExternalStoreRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { answer, payload, question, source } from "@/panels/fixtures";
import { SourcesPanel } from "@/panels/SourcesPanel";
import { useApp } from "@/state";

// The panel reads assistant-ui's real thread state; an external-store runtime holds the
// fake messages, each carrying an AnswerMetadata payload as the DAR-631 adapter will.
function Harness({ messages }: { messages: ThreadMessageLike[] }) {
  const runtime = useExternalStoreRuntime({ messages, convertMessage: (m) => m, onNew: async () => {} });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div style={{ overflowY: "auto" }}>
        <SourcesPanel />
      </div>
    </AssistantRuntimeProvider>
  );
}

const LONG = "A long passage. ".repeat(20);

const first = [
  question("q1", "Who pays for a detour?"),
  answer("a1", payload([source(1), source(2, { excerpt: LONG, page_end: 14, section: null })])),
];
const second = [
  ...first,
  question("q2", "What about night work?"),
  answer("a2", payload([source(1, { title: "Night Work Policy" })])),
];

function shownQuestion(): string | null {
  return screen.queryByText(/used to answer/)?.querySelector("span")?.textContent ?? null;
}

beforeEach(() => {
  useApp.setState({ activeAnswerId: null, activeAt: 0, focusedSource: null });
});
afterEach(cleanup);

describe("SourcesPanel", () => {
  it("says where passages will appear before any answer", () => {
    render(<Harness messages={[]} />);
    expect(screen.getByText(/The passages an answer uses appear here/)).toBeTruthy();
  });

  it("stays empty for a reply without a payload, such as an error", () => {
    render(<Harness messages={[question("q1", "Hi"), answer("a1", undefined)]} />);
    expect(screen.getByText(/The passages an answer uses appear here/)).toBeTruthy();
  });

  it("shows the newest finished answer's passages", () => {
    render(<Harness messages={second} />);
    expect(shownQuestion()).toBe("What about night work?");
    expect(screen.getByText("1 passage used to answer", { exact: false })).toBeTruthy();
    expect(screen.getByText("Night Work Policy")).toBeTruthy();
  });

  it("ignores an answer that is still streaming", () => {
    const streaming = [...first, question("q2", "Next?"), answer("a2", payload([source(1)]), { running: true })];
    render(<Harness messages={streaming} />);
    expect(shownQuestion()).toBe("Who pays for a detour?");
  });

  it("lists each passage with its number, document, pages, section and PDF link", () => {
    render(<Harness messages={first} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    const one = within(items[0]);
    expect(one.getByText("Utilities Accommodation Manual")).toBeTruthy();
    expect(one.getByText("PDF page 11 · Section 1.1")).toBeTruthy();
    const link = one.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://example.org/uam.pdf#page=11");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    expect(link.textContent).toBe("Open the PDF at this page (source 1, opens in a new tab)");
    expect(within(items[1]).getByText("PDF pages 12–14")).toBeTruthy();
    expect(screen.getByText(/Safari may open the PDF at page 1/)).toBeTruthy();
  });

  it("clamps a long passage with Show more / Show less", () => {
    render(<Harness messages={first} />);
    const toggle = screen.getByRole("button", { name: "Show more" });
    const text = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(text.className).toContain("line-clamp-5");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.textContent).toBe("Show less");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(text.className).not.toContain("line-clamp-5");
    // The short passage has no toggle.
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("links only http(s) URLs and renders markup in the data as text", () => {
    const hostile = [
      question("q1", "<b>bold?</b>"),
      answer("a1", payload([source(1, { url: "javascript:alert(1)", title: '<img src=x onerror="alert(1)">' })])),
    ];
    const { container } = render(<Harness messages={hostile} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeTruthy();
    expect(container.querySelector("img, b")).toBeNull();
    expect(screen.queryByText(/Safari/)).toBeNull();
  });

  it("says no passages were used for a refusal", () => {
    render(<Harness messages={[question("q1", "Where do I park?"), answer("a1", payload([]))]} />);
    expect(screen.getByText(/No passages were used to answer/)).toBeTruthy();
    expect(shownQuestion()).toBe("Where do I park?");
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("switches to a cited older answer and focuses the cited passage", () => {
    render(<Harness messages={second} />);
    act(() => useApp.getState().focusSource("a1", 2));
    expect(shownQuestion()).toBe("Who pays for a detour?");
    const focused = document.activeElement as HTMLElement;
    expect(focused.dataset.n).toBe("2");
    // The cited passage's number is marked as the current one.
    expect(focused.querySelector("span")?.className).toContain("bg-primary");
  });

  it("goes back to the newest answer once one starts after the citation click", () => {
    const { rerender } = render(<Harness messages={second} />);
    act(() => useApp.getState().focusSource("a1", 1));
    expect(shownQuestion()).toBe("Who pays for a detour?");
    const later = new Date(Date.now() + 60_000);
    rerender(
      <Harness
        messages={[...second, question("q3", "And on weekends?", later), answer("a3", payload([source(1)]), { createdAt: later })]}
      />,
    );
    expect(shownQuestion()).toBe("And on weekends?");
  });

  it("keeps the cited answer when an answer that began before the click finishes", () => {
    const { rerender } = render(
      <Harness messages={[...first, question("q2", "Next?"), answer("a2", payload([source(1)]), { running: true })]} />,
    );
    act(() => useApp.getState().focusSource("a1", 1));
    rerender(<Harness messages={[...first, question("q2", "Next?"), answer("a2", payload([source(1)]))]} />);
    expect(shownQuestion()).toBe("Who pays for a detour?");
  });

  it("acts on a citation once, so reopening the panel doesn't refocus it", () => {
    const { unmount } = render(<Harness messages={first} />);
    act(() => useApp.getState().focusSource("a1", 2));
    expect((document.activeElement as HTMLElement).dataset.n).toBe("2");
    unmount();
    (document.activeElement as HTMLElement | null)?.blur();
    render(<Harness messages={first} />);
    expect(document.activeElement).toBe(document.body);
  });

  it("handles a citation clicked before the panel mounted, as on phones", () => {
    act(() => useApp.getState().focusSource("a1", 2));
    render(<Harness messages={first} />);
    expect((document.activeElement as HTMLElement).dataset.n).toBe("2");
  });
});
