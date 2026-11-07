/**
 * Deployment-specific values. Set these per environment rather than hardcoding
 * one deployment's hostname into the source.
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"
).replace(/\/$/, "");

/** Google Analytics measurement ID. Analytics is skipped when unset. */
export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID || "";
