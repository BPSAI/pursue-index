// @ts-check
import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import tailwindcss from "@tailwindcss/vite";

// https://astro.build/config
//
// Private repo → GitHub assigns a random pages.github.io subdomain that
// serves at root (e.g., fantastic-bassoon-XXXX.pages.github.io/). If the
// repo flips to public later, update site → "https://bpsai.github.io" and
// base → "/pursue-index".
export default defineConfig({
  site: "https://fantastic-bassoon-k5j8o45.pages.github.io",
  base: "/",
  trailingSlash: "ignore",
  integrations: [preact()],
  vite: {
    plugins: [tailwindcss()],
  },
});
