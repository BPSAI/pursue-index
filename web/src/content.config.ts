import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// /finds — curated reading guides authored from specific cards/pages.
// Entries must meet the /finds editorial standards before publish.
const finds = defineCollection({
  loader: glob({ pattern: "**/*.{md,mdx}", base: "./src/content/finds" }),
  schema: z.object({
    title: z.string(),
    subtitle: z.string().optional(),
    summary: z.string(),
    tags: z.array(z.string()).default([]),
    /** card_ids drawn upon — used to render a "sources" rail in the detail page. */
    cards: z.array(z.string()).default([]),
    published: z.coerce.date(),
    updated: z.coerce.date().optional(),
    draft: z.boolean().default(false),
    /**
     * Optional author byline. When set,
     * `articleJsonLd()` surfaces it as the schema:Person author; when
     * absent, the builder falls back to the default "pursue-index"
     * publisher attribution. Add this to a `/finds` frontmatter when
     * a non-default author should appear in the AI Overviews byline.
     */
    author: z.string().optional(),
  }),
});

export const collections = { finds };
