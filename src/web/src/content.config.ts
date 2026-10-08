import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { z } from "astro/zod";

const docs = defineCollection({
  loader: glob({ pattern: "*.md", base: "./src/content/docs" }),
  schema: z.object({
    title: z.string(),
    /** Meta description and the summary on the docs index (aim for 120-160 characters). */
    description: z.string(),
    /** Position in the sidebar, ascending. */
    order: z.number(),
  }),
});

export const collections = { docs };
