/** Shared block for one mod or plugin: name, source, description, ID, authors, license and links. */
import { CodeIcon, DownloadIcon, ExternalLinkIcon, FileIcon, HouseIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { SOURCE_LABELS, entryLinks, type CatalogEntry, type EntryLink, type Server } from "@/lib/site-data";

const ICONS: Record<EntryLink["kind"], typeof ExternalLinkIcon> = {
  project: ExternalLinkIcon,
  download: DownloadIcon,
  source: CodeIcon,
  homepage: HouseIcon,
};

export function EntryLinks({ links }: { links: EntryLink[] }) {
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {links.map((l) => {
        const Icon = l.kind === "source" && l.label.startsWith("Prebuilt") ? FileIcon : ICONS[l.kind];
        return (
          <a
            key={l.href}
            href={l.href}
            rel="noopener"
            {...(l.kind === "download" ? { download: "" } : {})}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border bg-background px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {l.label}
          </a>
        );
      })}
    </div>
  );
}

/** Name, badges, description and links of an entry. `release` links the exact bundled release and its file. */
export function EntryInfo({ server, entry, release = true }: { server: Server; entry: CatalogEntry; release?: boolean }) {
  const m = entry.metadata;
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h4 className="font-medium">{m.name ?? entry.id}</h4>
        <Badge variant="secondary" className="font-normal">
          {SOURCE_LABELS[entry.source] ?? entry.source}
        </Badge>
      </div>
      {m.description && <p className="line-clamp-2 text-sm text-muted-foreground">{m.description}</p>}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">{entry.id}</code>
        {m.authors.length > 0 && <span>by {m.authors.join(", ")}</span>}
        {m.license && <span>{m.license}</span>}
      </p>
      <EntryLinks links={entryLinks(server, entry, { release })} />
    </div>
  );
}
