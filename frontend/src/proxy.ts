import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const RETURN_TO_HEADER = "x-ai-workshop-return-to";

export function proxy(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(
    RETURN_TO_HEADER,
    `${request.nextUrl.pathname}${request.nextUrl.search}`,
  );
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: ["/app/:path*", "/admin/:path*"],
};
