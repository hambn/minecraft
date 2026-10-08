import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { Resvg } from "@resvg/resvg-js";
import type { APIRoute } from "astro";

/** 180x180 PNG of public/favicon.svg on a light tile, for iOS home screens. */
export const GET: APIRoute = async () => {
  const icon = (await readFile(join(process.cwd(), "public/favicon.svg"), "utf8")).replace(/<svg[^>]*>|<\/svg>/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="180" height="180"><rect width="32" height="32" fill="#fafafa"/><g transform="translate(4 4) scale(0.75)">${icon}</g></svg>`;
  const png = new Resvg(svg).render().asPng();
  return new Response(Buffer.from(png), { headers: { "Content-Type": "image/png" } });
};
