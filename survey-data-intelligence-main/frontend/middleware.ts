import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Next emits dynamic-route chunks under folders named `[batchId]`.
 * Browsers request those URLs as `%5BbatchId%5D`. If the static file
 * lookup uses the encoded name, the chunk 404s. Rewrite to the on-disk path.
 */
export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (!pathname.startsWith("/_next/static/chunks/")) {
    return NextResponse.next();
  }
  if (!pathname.includes("%5B") && !pathname.includes("%5D")) {
    return NextResponse.next();
  }
  const url = request.nextUrl.clone();
  url.pathname = decodeURIComponent(pathname);
  return NextResponse.rewrite(url);
}

export const config = {
  matcher: "/_next/static/chunks/:path*",
};
