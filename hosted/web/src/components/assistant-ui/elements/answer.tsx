import { type TextMessagePartComponent, useAui, useAuiState } from "@assistant-ui/react";
import { type ComponentProps, useCallback } from "react";
import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";
import { Button } from "@/components/ui/button";
import { carryForSuggestion, messageText, type QuestionMetadata } from "@/runtime/history";
import { useApp } from "@/state";
import type { AnswerMetadata, AnswerPayload } from "@/types";
import { CITE_PREFIX, linkCitations, searchedText } from "./format";

// An answer's text with clickable [n] citations, a refusal with its "Ask … instead"
// buttons, and the lines under each answer. Everything comes from the message's
// metadata.custom (AnswerMetadata, written by runtime/adapter.ts).

// The same breakpoint as App.tsx: narrower than this, the sources panel is a drawer.
const WIDE = "(min-width: 900px)";

const usePayload = () => useAuiState((s) => (s.message.metadata.custom as AnswerMetadata).payload);

type LinkProps = ComponentProps<"a"> & { node?: unknown };

/** Markdown links: a citation (#cite-n, from linkCitations) is a button that shows its source. */
function AnswerLink({ href, className, children, node: _node, ...props }: LinkProps) {
  const messageId = useAuiState((s) => s.message.id);
  if (href?.startsWith(CITE_PREFIX)) {
    const n = Number(href.slice(CITE_PREFIX.length));
    return (
      <button
        type="button"
        className="aui-cite text-primary hover:bg-accent focus-visible:ring-ring/50 mx-px cursor-pointer rounded-sm px-px align-super text-[0.75em] leading-none font-bold outline-none focus-visible:ring-2"
        aria-label={`Source ${n}`}
        onClick={() => {
          const app = useApp.getState();
          app.focusSource(messageId, n);
          if (!window.matchMedia(WIDE).matches) app.setDrawer("sources");
        }}
      >
        [{n}]
      </button>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`aui-md-a text-primary hover:text-primary/80 underline underline-offset-2 ${className ?? ""}`}
      {...props}
    >
      {children}
    </a>
  );
}

const ANSWER_COMPONENTS = { a: AnswerLink };

export const AnswerText: TextMessagePartComponent = ({ text }) => {
  const payload = usePayload();
  const sources = payload?.sources?.length ?? 0;
  const preprocess = useCallback((markdown: string) => linkCitations(markdown, sources), [sources]);
  if (payload?.refused) return <Refusal text={text} payload={payload} />;
  return <MarkdownText components={ANSWER_COMPONENTS} preprocess={preprocess} />;
};

/**
 * "Ask … instead" asks the refused question again in the suggested division. The
 * server searched that division with the previous question plus this one, so the
 * previous question goes along (carryForSuggestion) and the new exchange starts a topic.
 */
function Refusal({ text, payload }: { text: string; payload: AnswerPayload }) {
  const aui = useAui();
  const index = useAuiState((s) => s.message.index);
  const running = useAuiState((s) => s.thread.isRunning);

  const askInstead = (targetId: string) => {
    const thread = aui.thread();
    // Never a second question while one is being answered.
    if (thread.getState().isRunning) return;
    const messages = thread.getState().messages;
    const question = messages[index - 1];
    if (!question || question.role !== "user") return;
    const custom: QuestionMetadata = { carry: carryForSuggestion(messages, index) };
    useApp.getState().setTarget(targetId);
    thread.append({ role: "user", content: [{ type: "text", text: messageText(question) }], metadata: { custom } });
  };

  return (
    <div className="aui-refusal rounded-md border border-amber-300 bg-amber-50 px-3 py-2 dark:border-amber-800 dark:bg-amber-950/40">
      <p className="m-0">{text}</p>
      {(payload.suggest ?? []).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {payload.suggest.map((s) => (
            <Button key={s.id} type="button" variant="outline" size="sm" disabled={running} onClick={() => askInstead(s.id)}>
              Ask {s.name} instead
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Under each finished answer: the "No source cited" flag and what was searched. */
export function AnswerFooter() {
  const payload = usePayload();
  const divisions = useApp((s) => s.divisions);
  if (!payload) return null;
  const searched = payload.searched;
  const shown = searched && typeof searched.passages === "number" && typeof searched.documents === "number";
  const total = divisions.find((d) => d.id === payload.target?.id)?.documents.length ?? searched?.documents ?? 0;
  return (
    <>
      {payload.uncited && !payload.refused && (
        <p className="aui-uncited mt-2 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-2 text-sm dark:border-amber-800 dark:bg-amber-950/40">
          <strong>No source cited.</strong> This answer doesn't point to a page of the documents, so check it there
          before relying on it.
        </p>
      )}
      {shown && <p className="aui-searched text-muted-foreground mt-2 text-xs">{searchedText(searched, total)}</p>}
    </>
  );
}
