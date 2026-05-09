// @ts-check
import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import sitemap from "@astrojs/sitemap";
import mdx from "@astrojs/mdx";
import tailwindcss from "@tailwindcss/vite";

// https://astro.build/config
//
// Live custom domain via Cloudflare Workers + Static Assets.
// pursueindex.ai → 301 → pursueindex.com (Single Redirect rule on the .ai zone).
export default defineConfig({
  site: "https://pursueindex.com",
  base: "/",
  trailingSlash: "ignore",
  // mdx() registers `.mdx` as a renderable Markdown variant so Astro
  // components (e.g. <Cite>) can be embedded directly inside finds entries.
  // Plain `.md` content (about, methodology, etc.) keeps working unchanged.
  integrations: [preact(), sitemap(), mdx()],
  vite: {
    plugins: [tailwindcss()],
  },
});
