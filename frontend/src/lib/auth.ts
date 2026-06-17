import { createAuthClient } from "@neondatabase/auth";
import { BetterAuthReactAdapter } from "@neondatabase/auth/react";

const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
const baseUrl = `${appUrl}/api/auth`;

export const authClient = createAuthClient(baseUrl, {
  adapter: BetterAuthReactAdapter(),
});
