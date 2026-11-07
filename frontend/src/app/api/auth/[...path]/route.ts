import { getAuth } from "@/lib/auth-server";

// getAuth() throws if Neon Auth is not configured, so it is called per-request
// rather than at module scope - see the comment in lib/auth-server.ts.
export async function GET(req: Request, ctx: unknown) {
  return getAuth().handler().GET(req, ctx as never);
}

export async function POST(req: Request, ctx: unknown) {
  return getAuth().handler().POST(req, ctx as never);
}
