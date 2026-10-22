// The right panel: the passages the active answer cites. DAR-632 fills it from the
// active answer's metadata (useApp().activeAnswerId) and handles [n] citation clicks.
export function SourcesPanel() {
  return (
    <p className="text-sm text-muted-foreground">
      The passages an answer uses appear here, with a link to each PDF page.
    </p>
  );
}
