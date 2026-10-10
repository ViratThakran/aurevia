import { NextRequest, NextResponse } from "next/server";

import { REFRESH_COOKIE, apiBase, clearRefresh, forbidden, sameOrigin } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return forbidden();
  const token = request.cookies.get(REFRESH_COOKIE)?.value;
  if (token) {
    // Best effort: the session ends in the browser either way.
    await fetch(`${apiBase()}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  const response = new NextResponse(null, { status: 204 });
  clearRefresh(response);
  return response;
}
