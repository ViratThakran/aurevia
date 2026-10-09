/**
 * Server-only helpers for the /session route handlers.
 *
 * The refresh token never reaches browser JavaScript: it lives in an httpOnly, SameSite=Strict
 * cookie scoped to /session. The browser only ever holds the short-lived access token, in
 * memory. Requests from another origin are refused.
 */
import "server-only";

import { NextRequest, NextResponse } from "next/server";

export const REFRESH_COOKIE = "aurevia_refresh";
const COOKIE_MAX_AGE = 30 * 24 * 3600; // matches the API's refresh token lifetime

export function apiBase(): string {
  return (
    process.env.AUREVIA_API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

/**
 * Same-origin check: a browser always sends Origin on POST. Compared with the Host the browser
 * used, not the server's own address (which differs inside a container).
 */
export function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (origin === null || host === null) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function forbidden(): NextResponse {
  return NextResponse.json(
    { error: { code: "forbidden", message: "Cross-origin request refused" } },
    { status: 403 },
  );
}

interface TokenBody {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** Forward to the API; on success keep the refresh token in the cookie and return the rest. */
export async function forwardForTokens(path: string, body: unknown): Promise<NextResponse> {
  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase()}/api/v1${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "api_unreachable", message: "The Aurevia API is not reachable" } },
      { status: 502 },
    );
  }
  const data = await upstream.json().catch(() => null);
  if (!upstream.ok || data === null) {
    const response = NextResponse.json(data ?? { error: { code: "upstream_error" } }, {
      status: upstream.status,
    });
    if (upstream.status === 401) clearRefresh(response);
    return response;
  }
  const tokens = data as TokenBody;
  const response = NextResponse.json({
    access_token: tokens.access_token,
    expires_in: tokens.expires_in,
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/session",
    maxAge: COOKIE_MAX_AGE,
  });
  return response;
}

export function clearRefresh(response: NextResponse): void {
  response.cookies.set(REFRESH_COOKIE, "", { path: "/session", maxAge: 0 });
}
