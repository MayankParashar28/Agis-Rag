import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Signed-in surfaces: nothing here is useful to a crawler, and these all
      // redirect to /login anyway.
      disallow: [
        "/api/",
        "/admin/",
        "/dashboard",
        "/settings",
        "/analytics",
        "/knowledge-bases",
        "/upload",
        "/users",
        "/chat",
        "/retrieval",
        "/evaluation",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
