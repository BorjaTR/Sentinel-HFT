import { auth, currentUser } from "@clerk/nextjs/server"
import { NextResponse } from "next/server"
import Stripe from "stripe"
import { getPriceIdForTier, type Tier } from "@/lib/license"

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2025-11-17.clover",
  })
}

export async function GET(request: Request) {
  try {
    const { userId } = await auth()
    const user = await currentUser()

    if (!userId || !user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 })
    }

    // Get tier from query params
    const url = new URL(request.url)
    const tier = (url.searchParams.get("tier") || "pro") as Tier

    // Get price ID for the tier
    const priceId = getPriceIdForTier(tier)
    if (!priceId) {
      return NextResponse.json({ error: "Invalid tier" }, { status: 400 })
    }

    const stripe = getStripe()

    // Check if user already has a Stripe customer ID
    let customerId = user.privateMetadata.stripeCustomerId as string | undefined

    if (!customerId) {
      // Create new Stripe customer
      const customer = await stripe.customers.create({
        email: user.emailAddresses[0]?.emailAddress,
        metadata: {
          clerkUserId: userId,
        },
      })
      customerId = customer.id
    }

    // Create checkout session
    const session = await stripe.checkout.sessions.create({
      customer: customerId,
      mode: "subscription",
      payment_method_types: ["card"],
      line_items: [
        {
          price: priceId,
          quantity: 1,
        },
      ],
      success_url: `${process.env.NEXT_PUBLIC_APP_URL}/dashboard?upgraded=true`,
      cancel_url: `${process.env.NEXT_PUBLIC_APP_URL}/pricing?canceled=true`,
      metadata: {
        clerkUserId: userId,
        tier,
      },
    })

    return NextResponse.json({ url: session.url })
  } catch (error) {
    console.error("Checkout error:", error)
    return NextResponse.json({ error: "Failed to create checkout session" }, { status: 500 })
  }
}
