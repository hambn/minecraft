/**
 * Typed access to `src/data/site-data.json`, the export written by
 * `python -m server_images site-data` (see `.github/scripts/server_images/site_data.py`).
 * Every server, version and catalog entry on the site comes from there.
 */
import raw from "@/data/site-data.json";

export type VersionState = "published" | "pending" | "frozen" | "unlisted";
export type EntryStatus = "compatible" | "unsupported_fallback" | "unavailable";

export interface EntryMetadata {
  name: string | null;
  description: string | null;
  authors: string[];
  version: string | null;
  license: string | null;
  homepage: string | null;
}

export interface CatalogEntry {
  id: string;
  declared: boolean;
  source: string;
  status: EntryStatus | string;
  selectable: boolean;
  reason: string | null;
  closure: string[];
  metadata: EntryMetadata;
  supported_minecraft_versions: string[];
  identity: { project_id: string; slug: string | null; version_id: string | null; file_id: string | number | null };
  artifact: { filename: string; url: string | null; size: number | null } | null;
  /** prebuilt: the committed file, relative to the server's manifest_dir. */
  local: { path: string } | null;
  /** custom_build: the source directory, relative to the server's manifest_dir. */
  build: { directory: string } | null;
}

export interface Lock {
  minecraft_version: string;
  inputs_hash: string;
  runtime: { base_image: string | null; base_digest: string | null; java_major: number | null };
  server_build: { status: string; loader_version: string | null; details: Record<string, unknown> };
  entries: CatalogEntry[];
}

export interface ServerVersion {
  minecraft: string;
  state: VersionState;
  /** Published and inside the window, so it is rebuilt automatically. */
  maintained: boolean;
  digest: string | null;
  published_at: string | null;
  reason: string | null;
  lock: Lock | null;
}

export interface Server {
  id: string;
  title: string;
  description: string;
  homepage: string | null;
  image: string;
  loader_label: string;
  catalog: { kind: "mods" | "plugins"; env: string; dir: string };
  manifest_dir: string;
  eula: boolean;
  window: string[];
  upcoming: string[];
  latest: string | null;
  latest_outside_window: boolean;
  updated_at: string | null;
  versions: ServerVersion[];
}

export interface SiteData {
  schema: number;
  repo: string;
  owner: string;
  window_size: number;
  updated_at: string | null;
  servers: Server[];
}

export const data = raw as SiteData;
export const servers = data.servers;

export function getServer(id: string): Server {
  const server = servers.find((s) => s.id === id);
  if (!server) throw new Error(`unknown server ${id}`);
  return server;
}

export const isPullable = (v: ServerVersion) => v.state === "published" || v.state === "frozen";
/** Versions that get their own contents page. */
export const hasPage = (v: ServerVersion): v is ServerVersion & { lock: Lock } => isPullable(v) && v.lock !== null;

/** Java servers take MEMORY / JVM_OPTS; Pumpkin is a native binary. */
export const isJava = (s: Server) => s.versions.some((v) => v.lock?.runtime.java_major != null);

export const maintainedVersions = (s: Server) => s.versions.filter((v) => v.maintained);
export const pendingVersions = (s: Server) => s.versions.filter((v) => v.state === "pending");
export const frozenVersions = (s: Server) => s.versions.filter((v) => v.state === "frozen");

/** The version to show in examples: `latest` when pullable, else the newest maintained one. */
export function featuredVersion(s: Server): ServerVersion | undefined {
  return s.versions.find((v) => v.minecraft === s.latest && isPullable(v)) ?? maintainedVersions(s)[0];
}

export interface EntryGroups {
  selectable: CatalogEntry[];
  blocked: CatalogEntry[];
  fallbacks: CatalogEntry[];
  unavailable: CatalogEntry[];
  other: CatalogEntry[];
  dependencies: CatalogEntry[];
}

export function groupEntries(lock: Lock): EntryGroups {
  const entries = [...lock.entries].sort((a, b) => a.id.localeCompare(b.id));
  const declared = entries.filter((x) => x.declared);
  return {
    selectable: declared.filter((x) => x.status === "compatible" && x.selectable),
    blocked: declared.filter((x) => x.status === "compatible" && !x.selectable),
    fallbacks: declared.filter((x) => x.status === "unsupported_fallback"),
    unavailable: declared.filter((x) => x.status === "unavailable"),
    other: declared.filter((x) => !["compatible", "unsupported_fallback", "unavailable"].includes(x.status)),
    dependencies: entries.filter((x) => !x.declared),
  };
}

export const selectableCount = (v: ServerVersion) => (v.lock ? groupEntries(v.lock).selectable.length : 0);

export interface MatrixRow {
  id: string;
  name: string;
  description: string | null;
  homepage: string | null;
  /** The entry in the newest version that has it, for links and metadata. */
  entry: CatalogEntry;
  cells: (CatalogEntry | null)[];
}

/** Declared entries (rows) across the maintained versions (columns). */
export function catalogMatrix(s: Server): { versions: ServerVersion[]; rows: MatrixRow[] } {
  const versions = maintainedVersions(s).filter(hasPage);
  const ids = new Map<string, CatalogEntry>();
  for (const v of versions) for (const e of v.lock!.entries) if (e.declared && !ids.has(e.id)) ids.set(e.id, e);
  const rows = [...ids.values()]
    .map((first) => ({
      id: first.id,
      name: first.metadata.name ?? first.id,
      description: first.metadata.description,
      homepage: first.metadata.homepage,
      entry: first,
      cells: versions.map((v) => v.lock!.entries.find((e) => e.id === first.id && e.declared) ?? null),
    }))
    .sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }));
  return { versions, rows };
}

export interface EntryLink {
  label: string;
  href: string;
  kind: "project" | "download" | "source" | "homepage";
}

/** Where an entry comes from: its Modrinth/CurseForge page, source directory or committed file, plus the bundled file. */
export function entryLinks(s: Server, e: CatalogEntry, { release = true } = {}): EntryLink[] {
  const repo = `https://github.com/${data.repo}`;
  const links: EntryLink[] = [];
  const { slug, project_id, version_id } = e.identity;
  if (e.source === "modrinth") {
    const project = `https://modrinth.com/project/${slug ?? project_id}`;
    links.push({ label: "Modrinth", href: release && version_id ? `${project}/version/${version_id}` : project, kind: "project" });
  } else if (e.source === "curseforge") {
    links.push({ label: "CurseForge", href: `https://www.curseforge.com/projects/${project_id}`, kind: "project" });
  } else if (e.source === "custom_build" && e.build) {
    links.push({ label: "Source", href: `${repo}/tree/main/${s.manifest_dir}/${e.build.directory}`, kind: "source" });
  } else if (e.source === "prebuilt" && e.local) {
    links.push({ label: "Prebuilt file", href: `${repo}/blob/main/${s.manifest_dir}/${e.local.path}`, kind: "source" });
  }
  const home = e.metadata.homepage;
  if (home && /^https?:\/\//i.test(home) && !/modrinth\.com|curseforge\.com/i.test(home)) {
    links.push({ label: "Homepage", href: home, kind: "homepage" });
  }
  if (release && e.artifact?.url) {
    const ext = e.artifact.filename.split(".").pop();
    links.push({ label: `Download .${ext}`, href: e.artifact.url, kind: "download" });
  }
  return links;
}

export const SOURCE_LABELS: Record<string, string> = {
  modrinth: "Modrinth",
  curseforge: "CurseForge",
  custom_build: "Custom build",
  prebuilt: "Prebuilt",
};

export const totalMaintained = servers.reduce((n, s) => n + maintainedVersions(s).length, 0);
/** Distinct declared catalog IDs per server, summed. */
export const totalCatalog = servers.reduce((n, s) => n + catalogMatrix(s).rows.length, 0);
