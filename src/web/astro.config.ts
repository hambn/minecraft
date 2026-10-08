import { readFileSync } from "node:fs";
import { satteri } from "@astrojs/markdown-satteri";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";
import { siteMarkdownPlugin } from "./src/lib/markdown-site";
import type { SiteData } from "./src/lib/site-data";

const dataFile = new URL("./src/data/site-data.json", import.meta.url);
let data: SiteData;
try {
  data = JSON.parse(readFileSync(dataFile, "utf8"));
} catch {
  throw new Error("src/data/site-data.json is missing: run `pnpm site-data` first.");
}

const [owner, name] = data.repo.split("/");
// SITE_URL: public URL of the canonical deployment, used for canonical links, the
// sitemap and social cards. BASE_PATH: where this build is served ("/" in the web image).
const site = process.env.SITE_URL || `https://${owner.toLowerCase()}.github.io/${name}/`;
const base = process.env.BASE_PATH || new URL(site).pathname;

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  integrations: [react()],
  markdown: {
    processor: satteri({ mdastPlugins: [siteMarkdownPlugin({ data, base })] }),
    shikiConfig: { themes: { light: "github-light", dark: "github-dark" } },
  },
  vite: { plugins: [tailwindcss()] },
});
