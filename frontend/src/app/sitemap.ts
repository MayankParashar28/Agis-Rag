import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * Only publicly reachable pages belong in a sitemap. The authenticated routes
 * that used to be listed here all redirect to /login for an anonymous crawler,
 * and the per-locale alternates pointed at paths that do not exist because the
 * app has no i18n routing.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return [
    { url: SITE_URL, lastModified, changeFrequency: "daily", priority: 1.0 },
    { url: `${SITE_URL}/login`, lastModified, changeFrequency: "monthly", priority: 0.5 },
    { url: `${SITE_URL}/register`, lastModified, changeFrequency: "monthly", priority: 0.5 },
  ];
}
