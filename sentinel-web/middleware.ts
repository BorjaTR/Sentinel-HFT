import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server"

// Routes that require authentication
const isProtectedRoute = createRouteMatcher([
  "/api/upload(.*)",
  "/api/analyze-custom(.*)",
])

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    await auth.protect()
  }
})

export const config = {
  matcher: ["/((?!.*\\..*|_next).*)", "/", "/(api|trpc)(.*)"],
}
