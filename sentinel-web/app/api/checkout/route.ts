import { auth, currentUser } from "@clerk/nextjs/server"
import { NextResponse } from "next/server"
import Stripe from "stripe"

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2025-11-17.clover",
  })
}

export async function GET() {
  try {
    const { userId } = await auth()
    const user = await currentUser()

    if (!userId || !user) {
      return NextResponse.redirect(new URL("/sign-in", process.env.NEXT_PUBLIC_APP_URL))
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
          price: process.env.STRIPE_PRO_PRICE_ID,
          quantity: 1,
        },
      ],
      success_url: `${process.env.NEXT_PUBLIC_APP_URL}/analyze?upgraded=true`,
      cancel_url: `${process.env.NEXT_PUBLIC_APP_URL}/pricing?canceled=true`,
      metadata: {
        clerkUserId: userId,
      },
    })

    return NextResponse.redirect(session.url!)
  } catch (error) {
    console.error("Checkout error:", error)
    return NextResponse.json({ error: "Failed to create checkout session" }, { status: 500 })
  }
}
