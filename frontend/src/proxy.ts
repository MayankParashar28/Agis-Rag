import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route gate for authenticated pages.
 *
 * Renamed from `middleware.ts`: the `middleware` file convention is deprecated
 * in Next 16 in favour of `proxy`.
 *
 * SCOPE: this is a redirect/UX optimisation, NOT a security boundary. It only
 * base64-decodes the JWT payload to check `exp`; it does not verify the
 * signature, so a hand-crafted cookie will pass it. Every protected resource is
 * authorised server-side by the FastAPI backend, which does verify signatures
 * (see backend/app/core/security.py). Do not add privileged logic here.
 */
export function proxy(request: NextRequest) {
  const token = request.cookies.get("rag_access_token")?.value;

  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  try {
    const payloadBase64 = token.split(".")[1];
    if (!payloadBase64) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    const payloadString = atob(payloadBase64.replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(payloadString);

    if (payload.exp && payload.exp * 1000 < Date.now()) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
  } catch {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/settings/:path*",
    "/analytics/:path*",
    "/knowledge-bases/:path*",
    "/upload/:path*",
    "/users/:path*",
    "/chat/:path*",
    "/admin/:path*",
    // These two were missing, so they were the only signed-in pages with no gate.
    "/retrieval/:path*",
    "/evaluation/:path*",
  ],
};
