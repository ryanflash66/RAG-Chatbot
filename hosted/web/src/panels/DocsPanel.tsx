import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { count, documentsText, webUrl } from "@/panels/format";
import { useApp } from "@/state";
import type { Division, DivisionDocument } from "@/types";
import { warmUp } from "@/warm";

// The left panel (public/js/docs.js): who is asking and whom, then the documents grouped
// by division. The division being asked comes first, and its documents have checkboxes that
// choose which of them the next question searches; the other divisions' documents are
// listed read-only, because answers come only from the asked division's documents.

// Shows the Upload button only. It is not access control: there are no accounts or roles
// yet (per Dr. Namian), so the team opens the page with ?team=1.
const TEAM = new URLSearchParams(window.location.search).get("team") === "1";

export function DocsPanel() {
  const divisions = useApp((s) => s.divisions);
  const asker = useApp((s) => s.asker);
  const target = useApp((s) => s.target);
  const setAsker = useApp((s) => s.setAsker);
  const setTarget = useApp((s) => s.setTarget);
  const items = divisions.map((d) => ({ value: d.id, label: d.name }));
  const asked = divisions.find((d) => d.id === target);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <Picker
          label="I work in"
          value={asker}
          items={items}
          onChange={(id) => {
            setAsker(id);
            warmUp();
          }}
        />
        <Picker
          label="Ask"
          value={target}
          items={items}
          onChange={(id) => {
            setTarget(id);
            warmUp();
          }}
        />
      </div>
      <div className="flex flex-col gap-3">
        {/* Keyed by division, so switching "Ask" forgets the last-document warning. */}
        {asked && <AskedGroup key={asked.id} division={asked} />}
        {divisions
          .filter((d) => d !== asked)
          .map((d) => (
            <OtherGroup key={d.id} division={d} />
          ))}
      </div>
      {TEAM && <UploadPlaceholder />}
    </div>
  );
}

// Why the last ticked document can't be unticked: a question has to search something
// (the server answers an empty list with "Pick at least one document to search.").
function keptReason(d: Division): string {
  return d.documents.length === 1
    ? `${d.name} has one document for now, so it is always searched.`
    : "At least one document has to be searched.";
}

function summaryText(d: Division, picks: DivisionDocument[]): string {
  // All ticked sends no list, and the server then searches every passage of the division.
  const passages =
    picks.length === d.documents.length ? d.passages : picks.reduce((n, doc) => n + doc.passages, 0);
  if (!Number.isFinite(passages)) return "";
  return `Searches ${count(passages, "passage")} in ${documentsText(picks.length, d.documents.length)}.`;
}

function AskedGroup({ division: d }: { division: Division }) {
  const off = useApp((s) => s.unticked[d.id]);
  const toggleDocument = useApp((s) => s.toggleDocument);
  // The visitor tried to untick the last ticked document; the hint says why it stayed ticked.
  const [keptLast, setKeptLast] = useState(false);
  const headingId = useId();
  const hintId = useId();
  const picks = d.documents.filter((doc) => !off?.[doc.file]);
  const sole = picks.length === 1;
  const reason = keptReason(d);
  const summary = summaryText(d, picks);

  function toggle(file: string) {
    const kept = sole && !off?.[file];
    setKeptLast(kept);
    if (!kept) toggleDocument(d.id, file);
  }

  return (
    // The group role sits on the section, not the list, so the <li>s stay a list for screen readers.
    <section role="group" aria-labelledby={headingId} className="rounded-lg border border-primary/40 bg-muted/60 px-3 py-2.5">
      <h3 id={headingId} className="text-sm font-semibold">
        <StateBadge active>Asking</StateBadge> {d.name}
      </h3>
      {summary && <p className="mt-0.5 text-[0.85rem] text-muted-foreground">{summary}</p>}
      <ul className="mt-1.5">
        {d.documents.map((doc) => {
          const ticked = !off?.[doc.file];
          // The last ticked box is aria-disabled rather than disabled: it looks fixed, but stays
          // focusable and keeps its hover title, so keyboard and mouse users can still find out why.
          const kept = sole && ticked;
          return (
            <li key={doc.file} className="border-t py-1.5 text-sm first:border-t-0">
              <label
                title={kept ? reason : undefined}
                className={cn("flex min-h-11 items-start gap-2.5", kept ? "cursor-not-allowed" : "cursor-pointer")}
              >
                <input
                  type="checkbox"
                  checked={ticked}
                  onChange={() => toggle(doc.file)}
                  aria-disabled={kept || undefined}
                  aria-describedby={kept ? hintId : undefined}
                  className="mt-px size-5 shrink-0 cursor-pointer accent-primary aria-disabled:cursor-not-allowed aria-disabled:opacity-65"
                />
                <span className="font-semibold">{doc.title}</span>
              </label>
              <DocMeta doc={doc} className="pl-7.5" />
            </li>
          );
        })}
      </ul>
      <p id={hintId} className={cn("mt-1.5 text-[0.85rem]", keptLast ? "font-semibold" : "text-muted-foreground")}>
        {keptLast || d.documents.length === 1 ? reason : "Untick a document to leave it out of the search."}
      </p>
    </section>
  );
}

// "Not asked" rather than "Not searched": after a refusal the server does look through
// the other divisions, but only to suggest asking one of them instead (answer.py).
function OtherGroup({ division: d }: { division: Division }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="rounded-lg border px-3 py-2.5">
      <h3 id={headingId} className="text-sm font-medium text-muted-foreground">
        <StateBadge>Not asked</StateBadge> {d.name}
      </h3>
      <ul className="mt-1.5">
        {d.documents.map((doc) => (
          <li key={doc.file} className="border-t py-1.5 text-sm first:border-t-0">
            <span className="font-semibold">{doc.title}</span>
            <DocMeta doc={doc} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function DocMeta({ doc, className }: { doc: DivisionDocument; className?: string }) {
  const href = webUrl(doc.url);
  const passages = typeof doc.passages === "number" ? count(doc.passages, "passage") : null;
  if (!passages && !href) return null;
  return (
    <div className={cn("text-[0.85rem] text-muted-foreground", className)}>
      {passages}
      {passages && href && " · "}
      {href && (
        <a className="text-primary underline underline-offset-4" href={href} target="_blank" rel="noopener">
          Open the PDF<span className="sr-only"> of {doc.title} (opens in a new tab)</span>
        </a>
      )}
    </div>
  );
}

function StateBadge({ active, children }: { active?: boolean; children: ReactNode }) {
  return (
    <span
      className={cn(
        "mr-0.5 inline-block rounded border px-1.5 align-[1px] text-[11px] font-semibold tracking-wide uppercase",
        active ? "border-primary bg-primary text-primary-foreground" : "text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

// Team only, and it uploads nothing: documents are fixed in divisions.py until the
// document database (DAR-621) lets the team add them.
function UploadPlaceholder() {
  const [open, setOpen] = useState(false);
  const noteId = useId();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" aria-expanded={open} aria-controls={noteId} onClick={() => setOpen(!open)}>
        Upload documents
      </Button>
      <StateBadge>Team only</StateBadge>
      <p id={noteId} hidden={!open} className="basis-full text-[0.85rem] text-muted-foreground">
        Uploading comes with the document database (DAR-621). Nothing is uploaded from here yet.
      </p>
    </div>
  );
}

function Picker(props: {
  label: string;
  value: string | null;
  items: { value: string; label: string }[];
  onChange: (id: string) => void;
}) {
  const id = `picker-${props.label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label id={id} className="text-sm font-medium">
        {props.label}
      </label>
      <Select items={props.items} value={props.value} onValueChange={(v) => v && props.onChange(String(v))}>
        <SelectTrigger aria-labelledby={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {props.items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
