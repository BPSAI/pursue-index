// @ts-check
import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

// https://astro.build/config
//
// Live custom domain via Cloudflare Workers + Static Assets.
// pursueindex.ai → 301 → pursueindex.com (Single Redirect rule on the .ai zone).
export default defineConfig({
  site: "https://pursueindex.com",
  base: "/",
  trailingSlash: "ignore",
  integrations: [preact(), sitemap()],
  vite: {
    plugins: [tailwindcss()],
  },
});
