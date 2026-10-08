import { data } from "@/lib/site-data";

export const SITE_NAME = "Minecraft Server Images";
export const SITE_TAGLINE = "Prebuilt Minecraft server Docker images with mods and plugins baked in";
export const REPO_URL = `https://github.com/${data.repo}`;

/** Public URL of the canonical deployment (always the GitHub Pages site, also for self-hosted copies). */
export const SITE_URL = import.meta.env.SITE;

/** Path below the base this build is served from: `url("docs/")` -> `/minecraft/docs/`. */
export function url(path = ""): string {
  return import.meta.env.BASE_URL.replace(/\/?$/, "/") + path.replace(/^\//, "");
}

/** Absolute canonical URL for a path relative to the site root. */
export function canonical(path = ""): string {
  return new URL(path.replace(/^\//, ""), SITE_URL.replace(/\/?$/, "/")).href;
}

/** Strip this build's base path, giving the path relative to the site root. */
export function sitePath(pathname: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/?$/, "/");
  return pathname.startsWith(base) ? pathname.slice(base.length) : pathname.replace(/^\//, "");
}

export const formatDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("en", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : null;

export const shortDigest = (digest: string) => digest.replace(/^sha256:/, "").slice(0, 12);
