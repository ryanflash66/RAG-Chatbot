import { create } from "zustand";
import type { Division } from "@/types";

// The page's shared state: the panels, the composer and the runtime adapter all read it,
// in place of the old page's App.state / App.selection() / App.docs.selected().
type AppState = {
  divisions: Division[];
  maxChars: number;
  asker: string | null;
  target: string | null;
  /** Unticked documents per division ({divisionId: {file: true}}); everything else is ticked. */
  unticked: Record<string, Record<string, true>>;
  /** The answer whose sources the right panel shows (its message id). */
  activeAnswerId: string | null;
  /** When activeAnswerId was set (Date.now()): an answer started after that takes the panel back. */
  activeAt: number;
  /** A clicked [n] citation: the right panel scrolls to and highlights that passage. */
  focusedSource: { answerId: string; n: number } | null;
  /** The side panel open as a drawer on a narrow screen. */
  drawer: "docs" | "sources" | null;

  setDivisions: (divisions: Division[], maxChars: number) => void;
  setAsker: (id: string) => void;
  setTarget: (id: string) => void;
  toggleDocument: (divisionId: string, file: string) => void;
  showAnswer: (answerId: string | null) => void;
  focusSource: (answerId: string, n: number) => void;
  setDrawer: (drawer: AppState["drawer"]) => void;
};

function otherThan(divisions: Division[], id: string): string {
  return divisions.find((d) => d.id !== id)?.id ?? id;
}

export const useApp = create<AppState>((set, get) => ({
  divisions: [],
  maxChars: 500,
  asker: null,
  target: null,
  unticked: {},
  activeAnswerId: null,
  activeAt: 0,
  focusedSource: null,
  drawer: null,

  setDivisions: (divisions, maxChars) => {
    const asker = divisions[0]?.id ?? null;
    set({ divisions, maxChars, asker, target: asker ? otherThan(divisions, asker) : null });
  },
  // Asking your own division is allowed, but picking it as "I work in" moves "Ask" to the
  // other one, as the old page did, since the demo is about another division's manuals.
  setAsker: (id) => {
    const { divisions, target } = get();
    set({ asker: id, target: target === id ? otherThan(divisions, id) : target });
  },
  setTarget: (id) => set({ target: id }),
  toggleDocument: (divisionId, file) => {
    const { divisions, unticked } = get();
    const division = divisions.find((d) => d.id === divisionId);
    if (!division) return;
    const off = { ...(unticked[divisionId] ?? {}) };
    if (off[file]) delete off[file];
    else if (division.documents.filter((doc) => !off[doc.file]).length > 1) off[file] = true;
    else return; // a question has to search something, so the last ticked document stays ticked
    set({ unticked: { ...unticked, [divisionId]: off } });
  },
  showAnswer: (answerId) => set({ activeAnswerId: answerId, activeAt: Date.now() }),
  focusSource: (answerId, n) =>
    set({ activeAnswerId: answerId, activeAt: Date.now(), focusedSource: { answerId, n } }),
  setDrawer: (drawer) => set({ drawer }),
}));

/** The document files to search for a division, or null when all of them are ticked. */
export function selectedDocuments(state: Pick<AppState, "divisions" | "unticked">, divisionId: string): string[] | null {
  const division = state.divisions.find((d) => d.id === divisionId);
  if (!division) return null;
  const off = state.unticked[divisionId] ?? {};
  const picked = division.documents.filter((doc) => !off[doc.file]).map((doc) => doc.file);
  return picked.length === division.documents.length ? null : picked;
}
