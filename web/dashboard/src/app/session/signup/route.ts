import { NextRequest } from "next/server";

import { forbidden, forwardForTokens, sameOrigin } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return forbidden();
  return forwardForTokens("/auth/signup", await request.json());
}
