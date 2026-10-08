import type { ReactNode } from "react";
import { EntryInfo } from "@/components/catalog-entry";
import type { CatalogEntry, Server } from "@/lib/site-data";

type Column = "requires" | "reason" | "supported" | "status";

const IdList = ({ ids }: { ids: string[] }) => (
  <span className="flex flex-wrap gap-1">
    {ids.map((id) => (
      <code key={id} className="rounded bg-muted px-1.5 py-0.5 font-mono">
        {id}
      </code>
    ))}
  </span>
);

const COLUMNS: Record<Column, { title: string; render: (e: CatalogEntry) => ReactNode | null }> = {
  requires: {
    title: "Requires",
    render: (e) => {
      const deps = e.closure.filter((d) => d !== e.id);
      return deps.length ? <IdList ids={deps} /> : null;
    },
  },
  reason: { title: "Reason", render: (e) => e.reason },
  supported: {
    title: "Supports Minecraft",
    render: (e) =>
      e.supported_minecraft_versions.length ? <span className="font-mono">{e.supported_minecraft_versions.join(", ")}</span> : null,
  },
  status: { title: "Status", render: (e) => e.status.replaceAll("_", " ") },
};

/** One group of a version's catalog (selectable, fallbacks, ...) as a list. */
export function CatalogTable({ server, entries, columns = [] }: { server: Server; entries: CatalogEntry[]; columns?: Column[] }) {
  return (
    <ul className="divide-y overflow-hidden rounded-xl border">
      {entries.map((e) => {
        const facts: [string, ReactNode][] = [
          ["Version", e.metadata.version ? <span className="font-mono break-all">{e.metadata.version}</span> : null],
          ...columns.map((c): [string, ReactNode] => [COLUMNS[c].title, COLUMNS[c].render(e)]),
        ];
        return (
          <li key={e.id} className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_18rem] lg:gap-8">
            <EntryInfo server={server} entry={e} />
            <dl className="grid content-start gap-x-4 gap-y-2 text-xs sm:grid-cols-[7rem_minmax(0,1fr)] lg:grid-cols-[6.5rem_minmax(0,1fr)]">
              {facts
                .filter(([, value]) => value !== null && value !== undefined && value !== "")
                .map(([label, value]) => (
                  <div key={label} className="contents">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="min-w-0 break-words">{value}</dd>
                  </div>
                ))}
            </dl>
          </li>
        );
      })}
    </ul>
  );
}
