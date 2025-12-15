import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server"
import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

// Routes that require authentication
const isProtectedRoute = createRouteMatcher([
  "/api/upload(.*)",
  "/api/analyze-custom(.*)",
])

// Check if Clerk is configured
const isClerkConfigured = () => {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
  return key && (key.startsWith("pk_test_") || key.startsWith("pk_live_"))
}

// Conditional middleware - only use Clerk if configured
export default function middleware(req: NextRequest) {
  if (isClerkConfigured()) {
    return clerkMiddleware(async (auth, req) => {
      if (isProtectedRoute(req)) {
        await auth.protect()
      }
    })(req, {} as any)
  }

  // No Clerk configured - just pass through
  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!.*\\..*|_next).*)", "/", "/(api|trpc)(.*)"],
}
