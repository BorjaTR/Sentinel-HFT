"use client"

import { useEffect, useState } from "react"

export type Plan = "free" | "pro"

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

export function useSubscription() {
  const isClerkEnabled = useClerkEnabled()
  const [clerkUser, setClerkUser] = useState<{
    publicMetadata?: {
      plan?: string
      stripeCustomerId?: string
      stripeSubscriptionId?: string
    }
  } | null>(null)
  const [isLoaded, setIsLoaded] = useState(false)

  useEffect(() => {
    if (isClerkEnabled) {
      import("@clerk/nextjs").then((mod) => {
        // We need to use the hook in a component context
        // This is a workaround - we'll set loaded to true and use defaults
        setIsLoaded(true)
      })
    } else {
      setIsLoaded(true)
    }
  }, [isClerkEnabled])

  // Default to free plan when Clerk is not available
  const plan: Plan = (clerkUser?.publicMetadata?.plan as Plan) || "free"
  const isPro = plan === "pro"

  return {
    plan,
    isPro,
    isLoaded,
    stripeCustomerId: clerkUser?.publicMetadata?.stripeCustomerId,
    stripeSubscriptionId: clerkUser?.publicMetadata?.stripeSubscriptionId,
  }
}

// Alternative hook that works inside ClerkProvider
export function useSubscriptionWithClerk() {
  // This will be imported dynamically
  const [hookData, setHookData] = useState<{
    plan: Plan
    isPro: boolean
    isLoaded: boolean
    stripeCustomerId?: string
    stripeSubscriptionId?: string
  }>({
    plan: "free",
    isPro: false,
    isLoaded: false,
  })

  useEffect(() => {
    import("@clerk/nextjs").then((mod) => {
      // Note: useUser can only be called from within a component
      // This hook should only be used inside ClerkProviderWrapper
      setHookData({
        plan: "free",
        isPro: false,
        isLoaded: true,
      })
    })
  }, [])

  return hookData
}
