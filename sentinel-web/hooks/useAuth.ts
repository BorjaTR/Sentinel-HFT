"use client"

import { useEffect, useState } from "react"

// Check if Clerk is properly configured
function useClerkEnabled() {
  const [isEnabled, setIsEnabled] = useState(false)

  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
    const enabled =
      key !== undefined &&
      key !== "" &&
      (key.startsWith("pk_test_") || key.startsWith("pk_live_")) &&
      key.length > 20
    setIsEnabled(enabled)
  }, [])

  return isEnabled
}

export function useAuth() {
  const isClerkEnabled = useClerkEnabled()
  const [authState, setAuthState] = useState<{
    isSignedIn: boolean
    isLoaded: boolean
    user: {
      publicMetadata?: {
        plan?: string
        stripeCustomerId?: string
        stripeSubscriptionId?: string
      }
    } | null
  }>({
    isSignedIn: false,
    isLoaded: false,
    user: null,
  })

  useEffect(() => {
    if (isClerkEnabled) {
      // Dynamically import and use Clerk
      import("@clerk/nextjs").then(async (mod) => {
        // We can't use hooks outside of components, so we'll use the auth() function
        // For client-side, we need to check if we're in a ClerkProvider context
        // This is a workaround - the real auth state will be managed by ClerkProvider
        setAuthState({
          isSignedIn: false,
          isLoaded: true,
          user: null,
        })
      })
    } else {
      setAuthState({
        isSignedIn: false,
        isLoaded: true,
        user: null,
      })
    }
  }, [isClerkEnabled])

  return authState
}
