/**
 * Dynamic /robots.txt endpoint.
 *
 * Replaces the static `web/public/robots.txt` with a generated body
 * that names every AI crawler explicitly. Content generation lives in
 * `../lib/robots.ts` so it can be unit-tested. Implements the explicit
 * AI-bot allowlist policy.
 */

import type { APIRoute } from "astro";
import { buildRobotsTxt } from "../lib/robots";

const SITE_ORIGIN = "https://pursueindex.com";

export const GET: APIRoute = () => {
  const body = buildRobotsTxt({ siteOrigin: SITE_ORIGIN });
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      // Match the prevailing edge-cache stance for static text
      // resources — long-lived, revalidate on deploy.
      "Cache-Control": "public, max-age=3600",
    },
  });
};
