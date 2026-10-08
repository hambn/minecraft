/** Copy-paste commands generated for a server image and Minecraft version. */
import { isJava, type Server } from "@/lib/site-data";

interface Options {
  /** Catalog IDs to activate. */
  selection?: string[];
  digest?: string | null;
}

const ref = (s: Server, version: string, digest?: string | null) => `${s.image}:${version}${digest ? `@${digest}` : ""}`;

export function dockerRun(s: Server, version: string, { selection = [], digest }: Options = {}): string {
  const lines = [
    `docker run -d --name minecraft`,
    `  -p 25565:25565`,
    `  -v minecraft-data:/data`,
    ...(s.eula ? [`  -e EULA=TRUE`] : []),
    ...(selection.length ? [`  -e ${s.catalog.env}=${selection.join(",")}`] : []),
    `  ${ref(s, version, digest)}`,
  ];
  return lines.join(" \\\n");
}

export function composeFile(s: Server, version: string, { selection = [], digest }: Options = {}): string {
  const env = [
    ...(s.eula ? [`      EULA: "TRUE"`] : []),
    ...(isJava(s) ? [`      MEMORY: "4G"`] : []),
    `      ${s.catalog.env}: "${selection.join(",")}"`,
    `      PROP_MOTD: "My ${s.title} server"`,
  ];
  return [
    `services:`,
    `  minecraft:`,
    `    image: ${ref(s, version, digest)}`,
    `    ports:`,
    `      - "25565:25565"`,
    `    environment:`,
    ...env,
    `    volumes:`,
    `      - minecraft-data:/data`,
    `    stop_grace_period: 2m`,
    `    restart: unless-stopped`,
    ``,
    `volumes:`,
    `  minecraft-data:`,
  ].join("\n");
}

export function pullCommands(s: Server, version: string, digest?: string | null): string {
  const lines = [`docker pull ${ref(s, version)}`];
  if (digest) lines.push(`# pin this exact build`, `docker pull ${ref(s, version, digest)}`);
  return lines.join("\n");
}
