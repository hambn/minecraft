import { CheckIcon, CircleAlertIcon, MinusIcon } from "lucide-react";
import { EntryInfo } from "@/components/catalog-entry";
import { LiveDot } from "@/components/status";
import { catalogMatrix, type CatalogEntry, type Server, type ServerVersion } from "@/lib/site-data";
import { url } from "@/lib/site";
import { cn } from "@/lib/utils";

function describe(entry: CatalogEntry | null): { icon: typeof CheckIcon; text: string; tone: string; title: string } {
  if (!entry) return { icon: MinusIcon, text: "Not in catalog", tone: "text-muted-foreground", title: "Not in this version's catalog" };
  if (entry.status === "compatible" && entry.selectable) {
    return { icon: CheckIcon, text: entry.metadata.version ?? "bundled", tone: "text-success", title: "Selectable" };
  }
  const text = entry.status === "unsupported_fallback" ? "Fallback" : entry.status === "unavailable" ? "Unavailable" : "Not selectable";
  const tone = entry.status === "unsupported_fallback" ? "text-warning" : "text-muted-foreground";
  return { icon: CircleAlertIcon, text, tone, title: entry.reason ?? text };
}

function VersionCell({ server, version, entry }: { server: Server; version: ServerVersion; entry: CatalogEntry | null }) {
  const { icon: Icon, text, tone, title } = describe(entry);
  const ok = entry?.status === "compatible" && entry.selectable;
  return (
    <li title={title} className={cn("flex min-w-0 items-start gap-2 rounded-md border px-2.5 py-1.5 text-xs", ok && "bg-success/[0.04]")}>
      <a
        href={url(`images/${server.id}/${version.minecraft}/`)}
        className="w-14 shrink-0 font-mono font-medium text-muted-foreground hover:text-foreground hover:underline"
      >
        {version.minecraft}
      </a>
      <Icon className={cn("mt-px size-3.5 shrink-0", tone)} aria-hidden="true" />
      <span className={cn("min-w-0 break-all", ok ? "font-mono" : "text-muted-foreground")}>{text}</span>
    </li>
  );
}

/** Every declared mod or plugin, with what each auto-updated version bundles. */
export function CatalogMatrix({ server }: { server: Server }) {
  const { versions, rows } = catalogMatrix(server);
  if (!rows.length) {
    return (
      <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
        This image has no {server.catalog.kind} in its catalog yet.
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-muted/40 px-4 py-2.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {rows.length} {server.catalog.kind}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <LiveDot className="size-1.5 [&>span]:size-1.5" /> {versions.map((v) => v.minecraft).join(", ")}
        </span>
        <span className="inline-flex items-center gap-1">
          <CheckIcon className="size-3.5 text-success" /> selectable, with the bundled version
        </span>
      </div>
      <ul className="divide-y">
        {rows.map((row) => (
          <li key={row.id} className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-8">
            <EntryInfo server={server} entry={row.entry} release={false} />
            <ul className="grid content-start gap-1.5" aria-label={`${row.name} by Minecraft version`}>
              {versions.map((v, i) => (
                <VersionCell key={v.minecraft} server={server} version={v} entry={row.cells[i]} />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
