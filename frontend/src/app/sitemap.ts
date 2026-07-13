import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://agisrag.vercel.app";
  
  const routes = [
    "",
    "/chat",
    "/dashboard",
    "/login",
    "/register",
    "/settings",
    "/retrieval",
    "/upload",
    "/knowledge-bases",
  ];

  return routes.map((route) => ({
    url: `${baseUrl}${route}`,
    lastModified: new Date(),
    changeFrequency: route === "" ? "daily" : "weekly",
    priority: route === "" ? 1.0 : route === "/chat" || route === "/dashboard" ? 0.8 : 0.5,
    alternates: {
      languages: {
        "en-US": `${baseUrl}/en-US${route}`,
        "en-GB": `${baseUrl}/en-GB${route}`,
        "es-ES": `${baseUrl}/es-ES${route}`,
        "fr-FR": `${baseUrl}/fr-FR${route}`,
      },
    },
  }));
}
