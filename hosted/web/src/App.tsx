import { useEffect, useState, type ReactNode } from "react";
import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { BookOpenIcon, FileTextIcon } from "lucide-react";
import { fetchDivisions } from "@/api";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { DocsPanel } from "@/panels/DocsPanel";
import { SourcesPanel } from "@/panels/SourcesPanel";
import { answerAdapter } from "@/runtime/adapter";
import { load, save } from "@/runtime/saved";
import { useApp } from "@/state";

// Read once, before the first render: the runtime takes it as its initial messages.
const saved = load();

// The same breakpoint as the old page (public/css/base.css): narrower than this, the
// documents and sources panels become drawers over the chat.
const WIDE = "(min-width: 900px)";

function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}

export default function App() {
  const runtime = useLocalRuntime(answerAdapter, { initialMessages: saved.messages });
  const wide = useMedia(WIDE);
  const { drawer, setDrawer, setDivisions, setAsker, setTarget } = useApp();
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    fetchDivisions()
      .then((reply) => {
        setDivisions(reply.divisions, reply.max_question_chars);
        // Back to the restored conversation's divisions, so a follow-up after a reload
        // goes to the same documents with its history.
        const known = (id: string | null) => !!id && reply.divisions.some((d) => d.id === id);
        if (saved.messages.length && known(saved.asker) && known(saved.target)) {
          setAsker(saved.asker!);
          setTarget(saved.target!);
        }
      })
      .catch(() => setLoadError(true));
  }, [setDivisions, setAsker, setTarget]);

  // Saved after every change of the thread or of the divisions; a running answer is
  // saved as interrupted, so a reload mid-answer brings back Try again.
  useEffect(() => {
    const store = () => {
      const { asker, target } = useApp.getState();
      save({ messages: runtime.thread.getState().messages, asker, target });
    };
    const unsubscribeThread = runtime.thread.subscribe(store);
    const unsubscribeApp = useApp.subscribe((s, before) => {
      if (s.asker !== before.asker || s.target !== before.target) store();
    });
    return () => {
      unsubscribeThread();
      unsubscribeApp();
    };
  }, [runtime]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-dvh flex-col bg-background text-foreground">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
          {!wide && (
            <Button variant="outline" size="sm" onClick={() => setDrawer("docs")} aria-label="Open documents">
              <FileTextIcon /> Documents
            </Button>
          )}
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="rounded border px-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Prototype
            </span>
            <h1 className="truncate text-base font-semibold">Ask another division's manuals</h1>
          </div>
          {!wide && (
            <Button variant="outline" size="sm" onClick={() => setDrawer("sources")} aria-label="Open sources">
              <BookOpenIcon /> Sources
            </Button>
          )}
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 min-[900px]:grid-cols-[260px_minmax(0,1fr)_320px] min-[1100px]:grid-cols-[280px_minmax(0,1fr)_340px]">
          {wide && (
            <Panel label="Documents" side="left">
              <DocsPanel />
            </Panel>
          )}
          <main className="min-h-0 min-w-0">
            {loadError ? (
              <p className="p-4 text-sm text-destructive">Couldn't load the demo. Please refresh the page.</p>
            ) : (
              <Thread />
            )}
          </main>
          {wide && (
            <Panel label="Sources" side="right">
              <SourcesPanel />
            </Panel>
          )}
        </div>
      </div>

      {!wide && (
        <>
          <Drawer title="Documents" side="left" open={drawer === "docs"} onClose={() => setDrawer(null)}>
            <DocsPanel />
          </Drawer>
          <Drawer title="Sources" side="right" open={drawer === "sources"} onClose={() => setDrawer(null)}>
            <SourcesPanel />
          </Drawer>
        </>
      )}
    </AssistantRuntimeProvider>
  );
}

function Panel(props: { label: string; side: "left" | "right"; children: ReactNode }) {
  return (
    // relative: the links' visually hidden "(opens in a new tab)" text is absolutely
    // positioned, and without a positioned panel it escaped the panel's scroll box and
    // made the whole page about 7,000 px tall with 58 documents (DAR-621), so the page
    // itself scrolled under the header when an answer arrived.
    <aside
      aria-label={props.label}
      className={`relative min-h-0 overflow-y-auto bg-card p-4 ${props.side === "left" ? "border-r" : "border-l"}`}
    >
      <h2 className="mb-3 text-sm font-semibold">{props.label}</h2>
      {props.children}
    </aside>
  );
}

function Drawer(props: { title: string; side: "left" | "right"; open: boolean; onClose: () => void; children: ReactNode }) {
  return (
    <Sheet open={props.open} onOpenChange={(open) => !open && props.onClose()}>
      <SheetContent side={props.side} className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{props.title}</SheetTitle>
        </SheetHeader>
        <div className="px-4 pb-4">{props.children}</div>
      </SheetContent>
    </Sheet>
  );
}
