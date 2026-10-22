import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApp } from "@/state";

// The left panel: who is asking and whom, then each division's documents.
// DAR-632 adds the passage counts, the checkboxes, warm-up and the team-only upload.
export function DocsPanel() {
  const { divisions, asker, target, setAsker, setTarget } = useApp();
  const items = divisions.map((d) => ({ value: d.id, label: d.name }));

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <Picker label="I work in" value={asker} items={items} onChange={setAsker} />
        <Picker label="Ask" value={target} items={items} onChange={setTarget} />
      </div>
      {divisions.map((d) => (
        <section key={d.id} aria-labelledby={`docs-${d.id}`}>
          <h3 id={`docs-${d.id}`} className="mb-1 text-sm font-medium text-muted-foreground">
            {d.id === target ? `Asking ${d.name}` : d.name}
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {d.documents.map((doc) => (
              <li key={doc.file}>
                <a className="text-primary underline-offset-4 hover:underline" href={doc.url} target="_blank" rel="noopener">
                  {doc.title}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
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
