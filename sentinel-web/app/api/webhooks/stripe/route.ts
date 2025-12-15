import { headers } from "next/headers"
import { NextResponse } from "next/server"
import Stripe from "stripe"
import { clerkClient } from "@clerk/nextjs/server"

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2025-11-17.clover",
  })
}

export async function POST(req: Request) {
  const body = await req.text()
  const headersList = await headers()
  const signature = headersList.get("stripe-signature")!

  const stripe = getStripe()
  let event: Stripe.Event

  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!
    )
  } catch (error) {
    console.error("Webhook signature verification failed:", error)
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 })
  }

  try {
    const client = await clerkClient()

    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session
        const clerkUserId = session.metadata?.clerkUserId

        if (clerkUserId) {
          // Update user metadata to mark as Pro
          await client.users.updateUserMetadata(clerkUserId, {
            publicMetadata: {
              plan: "pro",
              stripeCustomerId: session.customer as string,
              stripeSubscriptionId: session.subscription as string,
            },
          })
        }
        break
      }

      case "customer.subscription.deleted": {
        const subscription = event.data.object as Stripe.Subscription
        const customerId = subscription.customer as string

        // Find user by Stripe customer ID and downgrade
        const customers = await stripe.customers.retrieve(customerId)
        const clerkUserId = (customers as Stripe.Customer).metadata?.clerkUserId

        if (clerkUserId) {
          await client.users.updateUserMetadata(clerkUserId, {
            publicMetadata: {
              plan: "free",
              stripeSubscriptionId: null,
            },
          })
        }
        break
      }

      case "invoice.payment_failed": {
        const invoice = event.data.object as Stripe.Invoice
        const customerId = invoice.customer as string

        // Optionally notify user of payment failure
        console.log(`Payment failed for customer: ${customerId}`)
        break
      }
    }

    return NextResponse.json({ received: true })
  } catch (error) {
    console.error("Webhook handler error:", error)
    return NextResponse.json({ error: "Webhook handler failed" }, { status: 500 })
  }
}
