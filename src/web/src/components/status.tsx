/** Version state vocabulary shared by every page: maintained versions are highlighted. */
import { Badge } from "@/components/ui/badge";
import type { ServerVersion } from "@/lib/site-data";
import { cn } from "@/lib/utils";

/** Pulsing dot marking versions that are rebuilt automatically. */
export function LiveDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex size-2 shrink-0", className)} aria-hidden="true">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60 motion-reduce:animate-none" />
      <span className="relative inline-flex size-2 rounded-full bg-success" />
    </span>
  );
}

const STATE_LABELS = {
  maintained: "Auto-updated",
  published: "Published",
  pending: "Pending",
  frozen: "Frozen",
  unlisted: "Unlisted",
} as const;

export function StateBadge({ version }: { version: Pick<ServerVersion, "state" | "maintained"> }) {
  if (version.maintained) {
    return (
      <Badge variant="outline" className="gap-1.5 border-success/30 bg-success/10 text-success-foreground">
        <LiveDot className="size-1.5 [&>span]:size-1.5" />
        {STATE_LABELS.maintained}
      </Badge>
    );
  }
  if (version.state === "pending") {
    return (
      <Badge variant="outline" className="border-dashed text-muted-foreground">
        {STATE_LABELS.pending}
      </Badge>
    );
  }
  return <Badge variant="secondary">{STATE_LABELS[version.state]}</Badge>;
}

/** A Minecraft version as a compact pill, linked when it has a contents page. */
export function VersionPill({ version, href }: { version: ServerVersion; href?: string }) {
  const Tag = href ? "a" : "span";
  const title = version.maintained
    ? `Minecraft ${version.minecraft}: published and updated automatically`
    : version.state === "pending"
      ? `Minecraft ${version.minecraft}: ${version.reason ?? "no stable server build yet"}`
      : `Minecraft ${version.minecraft}: ${STATE_LABELS[version.state].toLowerCase()}`;
  return (
    <Tag
      href={href}
      title={title}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 font-mono text-xs font-medium transition-colors",
        version.maintained
          ? "border-success/30 bg-success/10 text-success-foreground hover:bg-success/15"
          : version.state === "pending"
            ? "border-dashed text-muted-foreground"
            : "bg-muted text-muted-foreground",
        href && "hover:border-success/50",
      )}
    >
      {version.maintained && <LiveDot className="size-1.5 [&>span]:size-1.5" />}
      {version.minecraft}
      {version.state === "pending" && <span className="font-sans text-[10px] tracking-wide uppercase">soon</span>}
    </Tag>
  );
}
