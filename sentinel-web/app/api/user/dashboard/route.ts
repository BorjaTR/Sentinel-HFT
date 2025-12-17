import { NextResponse } from "next/server"
import { auth, clerkClient } from "@clerk/nextjs/server"
import Stripe from "stripe"
import { maskLicenseKey, getTierDisplayName, type Tier } from "@/lib/license"

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2025-11-17.clover",
  })
}

export interface DashboardData {
  plan: Tier
  planDisplayName: string
  licenseKey: string | null
  maskedKey: string | null
  licenseCreatedAt: string | null
  subscription: {
    status: string | null
    currentPeriodEnd: string | null
    cancelAtPeriodEnd: boolean
  } | null
  usage: {
    analysesThisMonth: number
    lastAnalysis: string | null
  }
}

/**
 * GET /api/user/dashboard
 *
 * Returns dashboard data for the authenticated user.
 */
export async function GET() {
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
      stripeCustomerId?: string
      stripeSubscriptionId?: string
    }

    const privateMeta = user.privateMetadata as {
      licenseKey?: string
      licenseCreatedAt?: string
    }

    const plan = (publicMeta.plan as Tier) || 'free'
    const licenseKey = privateMeta.licenseKey || null

    // Get subscription details from Stripe if exists
    let subscription = null
    if (publicMeta.stripeSubscriptionId) {
      try {
        const stripe = getStripe()
        const sub = await stripe.subscriptions.retrieve(publicMeta.stripeSubscriptionId)
        subscription = {
          status: sub.status,
          currentPeriodEnd: new Date(sub.current_period_end * 1000).toISOString(),
          cancelAtPeriodEnd: sub.cancel_at_period_end,
        }
      } catch (error) {
        console.error("Failed to retrieve subscription:", error)
      }
    }

    const dashboardData: DashboardData = {
      plan,
      planDisplayName: getTierDisplayName(plan),
      licenseKey,
      maskedKey: licenseKey ? maskLicenseKey(licenseKey) : null,
      licenseCreatedAt: privateMeta.licenseCreatedAt || null,
      subscription,
      usage: {
        analysesThisMonth: 0, // Would come from usage tracking
        lastAnalysis: null,
      },
    }

    return NextResponse.json(dashboardData)

  } catch (error) {
    console.error("Dashboard API error:", error)
    return NextResponse.json(
      { error: "Failed to load dashboard" },
      { status: 500 }
    )
  }
}
