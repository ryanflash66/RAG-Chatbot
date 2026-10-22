import { useEffect, useState, type ReactNode } from "react";
import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { BookOpenIcon, FileTextIcon } from "lucide-react";
import { fetchDivisions } from "@/api";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { DocsPanel } from "@/panels/DocsPanel";
import { SourcesPanel } from "@/panels/SourcesPanel";
import { placeholderAdapter } from "@/runtime/placeholder";
import { useApp } from "@/state";

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
  const runtime = useLocalRuntime(placeholderAdapter);
  const wide = useMedia(WIDE);
  const { drawer, setDrawer, setDivisions } = useApp();
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    fetchDivisions()
      .then((reply) => setDivisions(reply.divisions, reply.max_question_chars))
      .catch(() => setLoadError(true));
  }, [setDivisions]);

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
    <aside
      aria-label={props.label}
      className={`min-h-0 overflow-y-auto bg-card p-4 ${props.side === "left" ? "border-r" : "border-l"}`}
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
