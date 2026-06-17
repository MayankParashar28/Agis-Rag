import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("rag_access_token")?.value;

  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  try {
    // Edge-compatible JWT decode
    const payloadBase64 = token.split(".")[1];
    const payloadString = atob(payloadBase64.replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(payloadString);

    if (payload.exp && payload.exp * 1000 < Date.now()) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
  } catch (error) {
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
  ],
};
