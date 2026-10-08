import { ArrowRightIcon } from "lucide-react";
import { StateBadge } from "@/components/status";
import { hasPage, isPullable, type Server } from "@/lib/site-data";
import { formatDate, shortDigest, url } from "@/lib/site";
import { cn } from "@/lib/utils";

/** Every tag of an image: maintained, pending and frozen. Stacks on small screens instead of scrolling. */
export function VersionTable({ server }: { server: Server }) {
  return (
    <ul className="divide-y overflow-hidden rounded-xl border">
      {server.versions.map((v) => (
        <li
          key={v.minecraft}
          className={cn(
            "grid items-center gap-x-6 gap-y-2 p-4 text-sm md:grid-cols-[7rem_9rem_minmax(0,1fr)_auto]",
            v.maintained && "bg-success/[0.03]",
          )}
        >
          <div className="flex items-center justify-between gap-3 md:contents">
            <span className="font-mono font-medium">{v.minecraft}</span>
            <span>
              <StateBadge version={v} />
            </span>
          </div>
          <div className="min-w-0 space-y-0.5 text-xs">
            {isPullable(v) ? (
              <>
                <code className="font-mono break-all">{`${server.image}:${v.minecraft}`}</code>
                <p className="text-muted-foreground">
                  {v.digest && <span title={v.digest}>{shortDigest(v.digest)}</span>}
                  {v.published_at && <span> · published {formatDate(v.published_at)}</span>}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">{v.reason ?? "Not available"}</p>
            )}
          </div>
          {hasPage(v) ? (
            <a
              href={url(`images/${server.id}/${v.minecraft}/`)}
              className="inline-flex items-center gap-1 text-xs font-medium underline-offset-4 hover:underline md:justify-self-end"
            >
              View contents <ArrowRightIcon className="size-3" />
            </a>
          ) : (
            <span className="hidden md:block" />
          )}
        </li>
      ))}
    </ul>
  );
}
