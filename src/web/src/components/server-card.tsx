import { ArrowRightIcon, PackageIcon } from "lucide-react";
import { VersionPill } from "@/components/status";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { catalogMatrix, hasPage, maintainedVersions, pendingVersions, type Server } from "@/lib/site-data";
import { url } from "@/lib/site";

export function ServerCard({ server }: { server: Server }) {
  const maintained = maintainedVersions(server);
  const pending = pendingVersions(server);
  const catalogSize = catalogMatrix(server).rows.length;
  const href = url(`images/${server.id}/`);
  return (
    <Card className="group relative transition-shadow hover:shadow-md hover:ring-foreground/20">
      <CardHeader>
        <CardTitle className="text-lg font-semibold">
          <a href={href} className="after:absolute after:inset-0 focus-visible:outline-none">
            {server.title}
          </a>
        </CardTitle>
        <CardDescription className="line-clamp-2">{server.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <code className="truncate rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">{server.image}</code>
        <div className="relative z-10 flex flex-wrap gap-1.5">
          {maintained.map((v) => (
            <VersionPill key={v.minecraft} version={v} href={hasPage(v) ? url(`images/${server.id}/${v.minecraft}/`) : undefined} />
          ))}
          {pending.map((v) => (
            <VersionPill key={v.minecraft} version={v} />
          ))}
          {maintained.length === 0 && pending.length === 0 && (
            <span className="text-sm text-muted-foreground">No published images yet</span>
          )}
        </div>
      </CardContent>
      <CardFooter className="justify-between border-t bg-muted/30 py-3 text-muted-foreground">
        <span className="inline-flex items-center gap-1.5 text-xs">
          <PackageIcon className="size-3.5" />
          {catalogSize} {server.catalog.kind} · <code className="font-mono">{server.catalog.env}</code>
        </span>
        <ArrowRightIcon className="size-4 transition-transform group-hover:translate-x-0.5" />
      </CardFooter>
    </Card>
  );
}
