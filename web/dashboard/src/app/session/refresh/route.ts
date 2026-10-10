import { NextRequest, NextResponse } from "next/server";

import {
  REFRESH_COOKIE,
  clearRefresh,
  forbidden,
  forwardForTokens,
  sameOrigin,
} from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return forbidden();
  const token = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!token) {
    const response = NextResponse.json(
      { error: { code: "unauthorized", message: "Not signed in" } },
      { status: 401 },
    );
    clearRefresh(response);
    return response;
  }
  return forwardForTokens("/auth/refresh", { refresh_token: token });
}
