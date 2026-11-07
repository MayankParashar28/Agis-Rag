import { createNeonAuth } from "@neondatabase/auth/next/server";

// No hardcoded fallbacks here on purpose. A committed default cookie secret is a
// real vulnerability: anything signed with a value that lives in the repo can be
// forged by anyone who can read the repo. So this fails loudly when unset.
//
// The check is deliberately lazy rather than at module scope. Neon Auth is
// optional - the app can authenticate against the backend's own /auth/login
// instead - and a module-level throw here would fail `next build` while it
// collects page data for this route, taking down every other page with it.
// Resolving on first use keeps the failure scoped to /api/auth/* requests,
// which are the only thing that actually needs these values.
function resolveConfig() {
  const baseUrl = process.env.NEXT_PUBLIC_NEON_AUTH_BASE_URL;
  const cookieSecret = process.env.NEON_AUTH_COOKIE_SECRET;

  if (!baseUrl) {
    throw new Error(
      "NEXT_PUBLIC_NEON_AUTH_BASE_URL is not set. Set it in your environment, " +
        "or remove src/app/api/auth if you are using the backend's own /auth/login."
    );
  }

  if (!cookieSecret || cookieSecret.length < 32) {
    throw new Error(
      "NEON_AUTH_COOKIE_SECRET must be set to at least 32 characters. " +
        "Generate one with: openssl rand -hex 32"
    );
  }

  return { baseUrl, cookieSecret };
}

let cached: ReturnType<typeof createNeonAuth> | undefined;

export function getAuth() {
  if (!cached) {
    const { baseUrl, cookieSecret } = resolveConfig();
    cached = createNeonAuth({ baseUrl, cookies: { secret: cookieSecret } });
  }
  return cached;
}
