import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// /finds — curated reading guides authored from specific cards/pages.
// See .paircoder/plans/curated-finds.md for the editorial standards
// these entries must meet before publish.
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
  }),
});

export const collections = { finds };
