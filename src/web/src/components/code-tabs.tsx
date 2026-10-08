import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Snippet } from "@/lib/highlight";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={copied ? "Copied" : "Copy to clipboard"}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <CheckIcon className="text-success" /> : <CopyIcon />}
    </Button>
  );
}

/** Highlighted snippets (Docker run, Compose, ...) in shadcn tabs with a copy button. */
export function CodeTabs({ snippets }: { snippets: Snippet[] }) {
  const [active, setActive] = useState(snippets[0]?.value);
  const current = snippets.find((s) => s.value === active) ?? snippets[0];
  return (
    <Tabs value={active} onValueChange={setActive} className="gap-0 overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-2 py-1.5">
        <TabsList variant="line">
          {snippets.map((s) => (
            <TabsTrigger
              key={s.value}
              value={s.value}
              className="px-2.5 focus-visible:border-transparent focus-visible:bg-muted focus-visible:ring-0 focus-visible:outline-none"
            >
              {s.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {current && <CopyButton text={current.code} />}
      </div>
      {snippets.map((s) => (
        <TabsContent key={s.value} value={s.value} className="min-w-0">
          <div className="overflow-x-auto text-[13px] leading-relaxed [&_pre]:p-4" dangerouslySetInnerHTML={{ __html: s.html }} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
