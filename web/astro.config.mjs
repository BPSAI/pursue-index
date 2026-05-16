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
    build: {
      // Sprint 2 perf-pass — Astro's default Vite target is "modules"
      // (≈ES2017). Every browser in our supported matrix handles ES2022
      // natively, so bumping the target lets Vite skip transpiling
      // `??`, `?.`, top-level await, class fields, etc. into helper-
      // function polyfills. Materially reduces island JS chunk size.
      // Preact, Astro 6, MiniSearch, regl-scatterplot all ship ES2022+
      // in their distributed bundles already; this just stops us from
      // re-down-leveling them on our side.
      target: "es2022",
    },
  },
});
