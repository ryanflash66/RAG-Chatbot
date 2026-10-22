import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useAuiState } from "@assistant-ui/react";
import { cn } from "@/lib/utils";
import { pagesText, pickAnswer } from "@/panels/answers";
import { webUrl } from "@/panels/format";
import { useApp } from "@/state";
import type { Source } from "@/types";

// The right panel (public/js/sources.js): the passages the shown answer cites. Clicking
// [n] in an answer (useApp().focusSource) shows that answer's passages, scrolls to
// passage n, flashes it and moves focus there.

const EMPTY = "The passages an answer uses appear here, with a link to each PDF page.";
// Excerpts run up to 700 characters (EXCERPT_CHARS in divrag/answer.py). Longer than this
// they are clamped to five lines with a Show more toggle. 240 characters is about five lines
// of the 300-360 px panel, so a shorter excerpt is never cut off without a toggle to open it.
const CLAMP_CHARS = 240;
const FLASH_MS = 1600;
const FLASH = "rgba(240, 180, 41, .32)";
const FLASH_STILL = "rgba(240, 180, 41, .22)";

// The citation click last acted on. Module-level because on phones the panel mounts only
// when its drawer opens: a click made just before that still has to be handled, while
// reopening the drawer later must not scroll to and flash the same passage again.
let handledFocus: object | null = null;
let lastFlash: Animation | null = null;

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

// The panel's scrolling box: the side column on wide screens, the drawer on phones.
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}

// Scroll the panel itself, not the page: scrollIntoView would also move the window
// and, on phones, the chat behind the drawer.
function scrollToItem(item: HTMLElement) {
  const box = scrollParent(item);
  if (!box) return;
  const top = Math.max(0, box.scrollTop + item.getBoundingClientRect().top - box.getBoundingClientRect().top - 12);
  if (typeof box.scrollTo === "function") box.scrollTo({ top, behavior: reducedMotion() ? "auto" : "smooth" });
  else box.scrollTop = top;
}

// The Web Animations API rather than a CSS class, so a second click on the same passage
// restarts the flash and React's className never fights it. Under reduced motion the
// passage is tinted for the same time instead of fading.
function flash(item: HTMLElement) {
  lastFlash?.cancel();
  if (typeof item.animate !== "function") return;
  const frames = reducedMotion()
    ? [{ backgroundColor: FLASH_STILL }, { backgroundColor: FLASH_STILL }]
    : [
        { backgroundColor: FLASH, offset: 0 },
        { backgroundColor: FLASH, offset: 0.35 },
        { backgroundColor: "transparent", offset: 1 },
      ];
  lastFlash = item.animate(frames, { duration: FLASH_MS, easing: "ease-out" });
}

export function SourcesPanel() {
  const messages = useAuiState((s) => s.thread.messages);
  const activeAnswerId = useApp((s) => s.activeAnswerId);
  const activeAt = useApp((s) => s.activeAt);
  const focusedSource = useApp((s) => s.focusedSource);
  const answer = useMemo(
    () => pickAnswer(messages, activeAnswerId, activeAt),
    [messages, activeAnswerId, activeAt],
  );
  const answerId = answer?.id ?? null;
  const root = useRef<HTMLDivElement>(null);

  // Another answer's passages start at the top, as on the old page.
  useEffect(() => {
    const box = root.current && scrollParent(root.current);
    if (box) box.scrollTop = 0;
  }, [answerId]);

  useEffect(() => {
    if (!focusedSource || focusedSource === handledFocus || focusedSource.answerId !== answerId) return;
    const item = root.current?.querySelector<HTMLElement>(`[data-n="${Number(focusedSource.n)}"]`);
    if (!item) return;
    handledFocus = focusedSource;
    item.focus({ preventScroll: true });
    scrollToItem(item);
    flash(item);
  }, [focusedSource, answerId]);

  if (!answer) {
    return (
      <div ref={root}>
        <p className="text-sm text-muted-foreground">{EMPTY}</p>
      </div>
    );
  }

  const { sources, question } = answer;
  const current = focusedSource?.answerId === answer.id ? Number(focusedSource.n) : null;
  const label = !sources.length
    ? "No passages were used to answer"
    : sources.length === 1
      ? "1 passage used to answer"
      : `${sources.length} passages used to answer`;

  return (
    <div ref={root}>
      {question ? (
        <p className="mb-3 text-sm text-muted-foreground">
          {label} <span className="mt-0.5 line-clamp-3 font-semibold text-foreground">{question}</span>
        </p>
      ) : (
        !sources.length && <p className="text-sm text-muted-foreground">This answer has no sources.</p>
      )}
      {sources.length > 0 && (
        <ol>
          {sources.map((s) => (
            <SourceItem key={`${answer.id}-${s.n}`} source={s} current={Number(s.n) === current} />
          ))}
        </ol>
      )}
      {sources.some((s) => /#page=\d+$/.test(s.url || "")) && (
        <p className="mt-3.5 text-xs text-muted-foreground">
          Safari may open the PDF at page 1. If it does, go to the page shown above.
        </p>
      )}
    </div>
  );
}

function SourceItem({ source: s, current }: { source: Source; current: boolean }) {
  const n = Number(s.n);
  const text = s.excerpt ? String(s.excerpt) : "";
  const long = text.length > CLAMP_CHARS;
  const [open, setOpen] = useState(false);
  const textId = useId();
  const meta = [pagesText(s), s.section ? `Section ${s.section}` : null].filter(Boolean).join(" · ");
  const href = webUrl(s.url);

  return (
    // tabIndex -1: a clicked citation moves focus here, so a screen reader reads the passage.
    // relative keeps the sr-only text inside the scrolling panel; placed against the page
    // instead, it made the whole page as tall as the list of passages.
    <li
      id={`src-${n}`}
      data-n={n}
      tabIndex={-1}
      className="relative -mx-2.5 rounded-md border-t px-2.5 py-3 text-sm first:border-t-0 first:pt-1"
    >
      <div className="flex items-baseline gap-2">
        <span
          className={cn(
            "inline-flex h-[1.7em] min-w-[1.7em] shrink-0 items-center justify-center rounded-full px-1 text-xs font-bold",
            current ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
          )}
        >
          <span className="sr-only">Source </span>
          {n}
        </span>
        <span className="leading-snug font-semibold">{String(s.title || "")}</span>
      </div>
      {meta && <div className="mt-0.5 text-[0.85rem] text-muted-foreground">{meta}</div>}
      {text && (
        // The clamp is on the inner <p>: on the padded box, the sixth line would show in the padding.
        <div className="mt-2 rounded-r border-l-[3px] bg-muted/60 px-2.5 py-2 text-[0.9rem] leading-relaxed">
          <p id={textId} className={cn(long && !open && "line-clamp-5")}>
            {text}
          </p>
        </div>
      )}
      {(long || href) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5">
          {long && (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={textId}
              onClick={() => setOpen(!open)}
              className="inline-flex items-center py-1 text-[0.85rem] font-semibold text-primary underline-offset-4 hover:underline pointer-coarse:min-h-11"
            >
              {open ? "Show less" : "Show more"}
            </button>
          )}
          {href && (
            // url ends in #page=N when the page is known. Identical link texts get a hidden
            // source number so a screen reader's list of links tells them apart.
            <a
              href={href}
              target="_blank"
              rel="noopener"
              className="inline-flex items-center py-1 text-primary underline underline-offset-4 pointer-coarse:min-h-11"
            >
              {s.page ? "Open the PDF at this page" : "Open the PDF"}
              <span className="sr-only"> (source {n}, opens in a new tab)</span>
            </a>
          )}
        </div>
      )}
    </li>
  );
}
