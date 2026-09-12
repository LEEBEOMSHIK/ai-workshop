import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const RETURN_TO_HEADER = "x-ai-workshop-return-to";

export function decideRouteAccess(
  pathname: string,
  mode: string | undefined,
): "allow" | "not-found" {
  if (mode !== "public") return "allow";
  if (pathname.startsWith("/api/public/")) return "allow";
  if (
    pathname === "/login" ||
    pathname === "/setup" ||
    pathname.startsWith("/admin") ||
    pathname.startsWith("/workshop") ||
    pathname.startsWith("/api/")
  ) return "not-found";
  return "allow";
}

export function proxy(request: NextRequest) {
  if (decideRouteAccess(request.nextUrl.pathname, process.env.AI_WORKSHOP_FRONTEND_RUNTIME) === "not-found") {
    return new NextResponse(null, { status: 404 });
  }
  const requestHeaders = new Headers(request.headers);
  if (request.nextUrl.pathname.startsWith("/admin") || request.nextUrl.pathname.startsWith("/workshop")) {
    requestHeaders.set(
      RETURN_TO_HEADER,
      `${request.nextUrl.pathname}${request.nextUrl.search}`,
    );
  }
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: [
    "/workshop/:path*",
    "/admin/:path*",
    "/login",
    "/setup",
    "/api/:path*",
  ],
};
