/**
 * Typed client for the Aurevia API. Types come from the API's OpenAPI schema
 * (`npm run gen:api`). The access token is kept in memory only; when it expires the client
 * asks the dashboard's /session/refresh route (which holds the refresh token in an httpOnly
 * cookie) for a new one, once, and retries.
 */
import type { components } from "./api-schema";

export type Schemas = components["schemas"];

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onExpired: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function onSessionExpired(callback: () => void): void {
  onExpired = callback;
}

async function readError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  const error = body?.error ?? {};
  return new ApiError(
    response.status,
    error.code ?? "error",
    error.message ?? response.statusText ?? "Request failed",
    error.details,
  );
}

/** Calls one of the dashboard's own /session routes (same origin, cookie-based). */
export async function sessionCall(
  path: "login" | "signup" | "accept" | "refresh" | "logout",
  body?: unknown,
): Promise<{ access_token: string; expires_in: number } | null> {
  const response = await fetch(`/session/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (response.status === 204) return null;
  if (!response.ok) throw await readError(response);
  const tokens = (await response.json()) as { access_token: string; expires_in: number };
  setAccessToken(tokens.access_token);
  return tokens;
}

export async function refreshAccess(): Promise<boolean> {
  refreshing ??= sessionCall("refresh")
    .then(() => true)
    .catch(() => {
      setAccessToken(null);
      return false;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
}

function url(path: string, query?: Query): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return `${API_URL}/api/v1${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const send = () =>
    fetch(url(path, options.query), {
      method: options.method ?? "GET",
      headers: {
        ...(options.body !== undefined ? { "content-type": "application/json" } : {}),
        ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  let response = await send();
  if (response.status === 401 && (await refreshAccess())) {
    response = await send();
  }
  if (response.status === 401) onExpired?.();
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A readable message for any error thrown by the client. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const reasons = (error.details as { reasons?: string[] } | undefined)?.reasons;
    if (reasons?.length) return `${error.message}: ${reasons.join(", ").replaceAll("_", " ")}`;
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong";
}
