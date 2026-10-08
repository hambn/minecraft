/** Social card (Open Graph) images rendered at build time with satori + resvg. */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { Resvg } from "@resvg/resvg-js";
import satori from "satori";
import { SITE_NAME } from "@/lib/site";

const FONT_DIR = join(process.cwd(), "node_modules/@fontsource/geist-sans/files");
const fonts = Promise.all(
  ([400, 600] as const).map(async (weight) => ({
    name: "Geist",
    weight,
    style: "normal" as const,
    data: await readFile(join(FONT_DIR, `geist-sans-latin-${weight}-normal.woff`)),
  })),
);

const LOGO = `data:image/svg+xml;base64,${Buffer.from(
  `<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg"><path d="M16 2.5 28.5 9.5 16 16.5 3.5 9.5z" fill="#4caf50"/><path d="M3.5 9.5 16 16.5v13L3.5 22.5z" fill="#7a5230"/><path d="M28.5 9.5 16 16.5v13l12.5-7z" fill="#5e3e24"/><path d="M3.5 9.5 16 16.5v3.2L3.5 12.7z" fill="#3e8e41"/><path d="M28.5 9.5 16 16.5v3.2l12.5-7z" fill="#2f7a33"/></svg>`,
).toString("base64")}`;

type Node = { type: string; props: Record<string, unknown> & { children?: unknown } };
const h = (type: string, style: Record<string, unknown>, children?: unknown, extra: Record<string, unknown> = {}): Node => ({
  type,
  props: { style, children, ...extra },
});

export interface OgCard {
  eyebrow: string;
  title: string;
  description: string;
  /** Highlighted chips at the bottom, e.g. auto-updated versions. */
  pills?: string[];
}

export async function renderOg({ eyebrow, title, description, pills = [] }: OgCard): Promise<Uint8Array> {
  // satori sizes boxes as content-box, so the padding lives on an inner element.
  const content = h("div", { display: "flex", flexDirection: "column", justifyContent: "space-between", flexGrow: 1, margin: 72 }, [
    h("div", { display: "flex", alignItems: "center", gap: 16, fontSize: 28, color: "#a3a3a3" }, [
      h("img", { width: 44, height: 44 }, undefined, { src: LOGO }),
      SITE_NAME,
    ]),
    h("div", { display: "flex", flexDirection: "column", gap: 20 }, [
      h("div", { fontSize: 26, fontWeight: 600, color: "#4caf50", textTransform: "uppercase", letterSpacing: 2 }, eyebrow),
      h("div", { fontSize: title.length > 32 ? 64 : 76, fontWeight: 600, lineHeight: 1.05, letterSpacing: -2 }, title),
      h("div", { fontSize: 30, color: "#a3a3a3", lineHeight: 1.4, maxWidth: 1000 }, description),
    ]),
    h(
      "div",
      { display: "flex", gap: 12 },
      pills.map((p) =>
        h(
          "div",
          {
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 18px",
            borderRadius: 10,
            border: "1px solid rgba(76,175,80,0.4)",
            backgroundColor: "rgba(76,175,80,0.12)",
            color: "#86efac",
            fontSize: 26,
          },
          [h("div", { width: 10, height: 10, borderRadius: 10, backgroundColor: "#4caf50" }), p],
        ),
      ),
    ),
  ]);
  const tree = h(
    "div",
    {
      width: "100%",
      height: "100%",
      display: "flex",
      backgroundColor: "#0a0a0a",
      backgroundImage: "radial-gradient(circle at 85% 0%, rgba(76,175,80,0.22), transparent 55%)",
      color: "#fafafa",
      fontFamily: "Geist",
    },
    [content],
  );
  // satori accepts plain element objects as well as JSX.
  const svg = await satori(tree as unknown as Parameters<typeof satori>[0], { width: 1200, height: 630, fonts: await fonts });
  return new Resvg(svg, { fitTo: { mode: "width", value: 1200 } }).render().asPng();
}
