import { NextResponse } from "next/server"
import { auth, clerkClient } from "@clerk/nextjs/server"
import { generateLicenseKey, type Tier } from "@/lib/license"

/**
 * POST /api/user/regenerate-key
 *
 * Regenerates the license key for the authenticated user.
 * Only available for paid plans.
 */
export async function POST() {
  try {
    const { userId } = await auth()

    if (!userId) {
      return NextResponse.json(
        { error: "Unauthorized" },
        { status: 401 }
      )
    }

    const client = await clerkClient()
    const user = await client.users.getUser(userId)

    const publicMeta = user.publicMetadata as {
      plan?: Tier
      stripeSubscriptionId?: string
    }

    const plan = (publicMeta.plan as Tier) || 'free'

    // Only paid plans can have license keys
    if (plan === 'free') {
      return NextResponse.json(
        { error: "License keys are only available for paid plans" },
        { status: 403 }
      )
    }

    // Verify subscription is still active
    if (!publicMeta.stripeSubscriptionId) {
      return NextResponse.json(
        { error: "No active subscription found" },
        { status: 403 }
      )
    }

    // Generate new key
    const licenseKey = generateLicenseKey(plan)

    // Update user metadata
    await client.users.updateUserMetadata(userId, {
      privateMetadata: {
        licenseKey,
        licenseCreatedAt: new Date().toISOString(),
        previousKeyRevokedAt: new Date().toISOString(),
      },
    })

    return NextResponse.json({
      success: true,
      licenseKey,
      message: "New license key generated. Previous key is now invalid.",
    })

  } catch (error) {
    console.error("Key regeneration error:", error)
    return NextResponse.json(
      { error: "Failed to regenerate key" },
      { status: 500 }
    )
  }
}
