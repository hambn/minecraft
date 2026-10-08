import type { APIRoute, GetStaticPaths } from "astro";
import { getCollection } from "astro:content";
import { renderOg, type OgCard } from "@/lib/og";
import { placeholderValue } from "@/lib/markdown-site";
import { data, maintainedVersions, servers } from "@/lib/site-data";

export const getStaticPaths = (async () => {
  const docs = await getCollection("docs");
  const cards: { slug: string; card: OgCard }[] = [
    {
      slug: "home",
      card: {
        eyebrow: "Docker images",
        title: "Minecraft servers, ready to run",
        description: `Prebuilt ${placeholderValue(data, "servers")} images with mods and plugins baked in.`,
        pills: servers.map((s) => s.title),
      },
    },
    ...servers.map((s) => ({
      slug: s.id,
      card: {
        eyebrow: "Minecraft server image",
        title: `${s.title} for Docker`,
        description: s.description,
        pills: maintainedVersions(s).map((v) => v.minecraft),
      },
    })),
    ...docs.map((d) => ({
      slug: `docs-${d.id}`,
      card: { eyebrow: "Documentation", title: d.data.title, description: d.data.description },
    })),
  ];
  return cards.map(({ slug, card }) => ({ params: { slug }, props: { card } }));
}) satisfies GetStaticPaths;

export const GET: APIRoute = async ({ props }) =>
  new Response(Buffer.from(await renderOg((props as { card: OgCard }).card)), { headers: { "Content-Type": "image/png" } });
