/**
 * Markdown (Sätteri mdast) plugin for the docs collection, so the Markdown stays
 * readable on GitHub while the site shows live values from site-data.json:
 *
 * - `{{owner}}`, `{{repo}}`, `{{windowsize}}`, `{{servers}}`, and per server
 *   `{{image:paper}}`, `{{latest:paper}}`, `{{latestregex:paper}}`, `{{window:paper}}`,
 *   `{{upcoming:paper}}` are replaced in text, inline code and code blocks.
 * - A paragraph that is only `{{images-table}}` becomes a table of every image.
 * - Links to sibling docs (`configuration.md#memory`) and root-relative links
 *   (`/images/paper/`) are rewritten below the site's base path.
 *
 * Imported by astro.config.ts, so it uses relative imports only.
 */
import { defineMdastPlugin } from "satteri";
import type { SiteData } from "./site-data";

const PLACEHOLDER = /\{\{\s*([a-z]+)(?::([0-9A-Za-z._-]+))?\s*\}\}/g;
const DOC_LINK = /^(?:\.\/)?([A-Za-z0-9_-]+)\.md(#.*)?$/;
const IMAGES_TABLE = "{{images-table}}";

export function placeholderValue(data: SiteData, kind: string, server?: string): string | undefined {
  if (!server) {
    const titles = data.servers.map((s) => s.title);
    const servers = titles.length > 1 ? `${titles.slice(0, -1).join(", ")} and ${titles.at(-1)}` : (titles[0] ?? "");
    return { owner: data.owner, repo: data.repo, windowsize: String(data.window_size), servers }[kind];
  }
  const s = data.servers.find((x) => x.id === server);
  if (!s) return undefined;
  const pullable = (v: string) => s.versions.some((x) => x.minecraft === v && ["published", "frozen"].includes(x.state));
  const latest = (s.latest && pullable(s.latest) ? s.latest : s.window[0]) ?? "<minecraft-version>";
  return {
    image: s.image,
    latest,
    latestregex: latest.replaceAll(".", "\\."),
    window: s.window.join(", ") || "none",
    upcoming: s.upcoming.join(", ") || "none",
  }[kind];
}

function imagesTable(data: SiteData, root: string) {
  const text = (value: string) => ({ type: "text" as const, value });
  const code = (value: string) => ({ type: "inlineCode" as const, value });
  const row = (cells: object[]) => ({
    type: "tableRow" as const,
    children: cells.map((c) => ({ type: "tableCell" as const, children: [c] })),
  });
  return {
    type: "table" as const,
    align: [],
    children: [
      row(["Server", "Image", "Newest tag", "Selection variable"].map(text)),
      ...data.servers.map((s) =>
        row([
          { type: "link", url: `${root}images/${s.id}/`, children: [text(s.title)] },
          code(s.image),
          code(placeholderValue(data, "latest", s.id)!),
          code(s.catalog.env),
        ]),
      ),
    ],
  };
}

export function siteMarkdownPlugin({ data, base }: { data: SiteData; base: string }) {
  const root = base.replace(/\/?$/, "/");
  const expand = (value: string, file: URL | undefined) =>
    value.replace(PLACEHOLDER, (match, kind: string, server?: string) => {
      const result = placeholderValue(data, kind, server);
      if (result === undefined) console.warn(`warning: ${file?.pathname ?? "markdown"}: unknown placeholder ${match}`);
      return result ?? match;
    });

  type ValueNode = { value: string };
  type Ctx = { fileURL: URL | undefined; setProperty(node: never, key: "value", value: string): void };
  const replaceValue = (node: ValueNode, ctx: Ctx) => {
    const value = expand(node.value, ctx.fileURL);
    if (value !== node.value) ctx.setProperty(node as never, "value", value);
  };

  return defineMdastPlugin({
    name: "site-data",
    paragraph(node, ctx) {
      const [only] = node.children;
      if (node.children.length === 1 && only.type === "text" && only.value.trim() === IMAGES_TABLE) {
        ctx.replaceNode(node, imagesTable(data, root) as never);
      }
    },
    text: replaceValue,
    inlineCode: replaceValue,
    code: replaceValue,
    link(node, ctx) {
      const doc = DOC_LINK.exec(node.url);
      if (doc) ctx.setProperty(node, "url", `${root}docs/${doc[1]}/${doc[2] ?? ""}`);
      else if (node.url.startsWith("/") && !node.url.startsWith("//")) ctx.setProperty(node, "url", root + node.url.slice(1));
    },
  });
}
