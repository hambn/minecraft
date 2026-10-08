/** Sitemap with canonical URLs and lastmod dates taken from the publication data. */
import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import { data, hasPage, servers } from "@/lib/site-data";
import { canonical } from "@/lib/site";

export const GET: APIRoute = async () => {
  const docs = await getCollection("docs");
  const pages: [path: string, lastmod: string | null][] = [
    ["", data.updated_at],
    ["docs/", null],
    ...docs.map((d): [string, null] => [`docs/${d.id}/`, null]),
    ...servers.flatMap((s) => [
      [`images/${s.id}/`, s.updated_at] as [string, string | null],
      ...s.versions.filter(hasPage).map((v): [string, string | null] => [`images/${s.id}/${v.minecraft}/`, v.published_at]),
    ]),
  ];
  const urls = pages
    .map(([path, lastmod]) => `  <url><loc>${canonical(path)}</loc>${lastmod ? `<lastmod>${lastmod}</lastmod>` : ""}</url>`)
    .join("\n");
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
    {
      headers: { "Content-Type": "application/xml; charset=utf-8" },
    },
  );
};
