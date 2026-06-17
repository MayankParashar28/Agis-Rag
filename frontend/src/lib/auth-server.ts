import { createNeonAuth } from "@neondatabase/auth/next/server";

const baseUrl = process.env.NEXT_PUBLIC_NEON_AUTH_BASE_URL || "https://ep-still-grass-atrkssrr.neonauth.us-east-1.aws.neon.tech/neondb/auth";
const cookieSecret = process.env.NEON_AUTH_COOKIE_SECRET || "NEON_AUTH_COOKIE_SECRET_placeholder_key_at_least_32_characters";

export const auth = createNeonAuth({
  baseUrl,
  cookies: {
    secret: cookieSecret,
  },
});
