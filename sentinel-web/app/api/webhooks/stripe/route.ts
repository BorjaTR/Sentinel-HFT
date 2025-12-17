import { headers } from "next/headers"
import { NextResponse } from "next/server"
import Stripe from "stripe"
import { clerkClient } from "@clerk/nextjs/server"
import { generateLicenseKey, getTierFromPriceId, type Tier } from "@/lib/license"

function getStripe() {
  return new Stripe(process.env.STRIPE_SECRET_KEY!, {
    apiVersion: "2025-11-17.clover",
  })
}

/**
 * Get tier from subscription items.
 */
function getTierFromSubscription(subscription: Stripe.Subscription): Tier {
  const item = subscription.items.data[0]
  if (!item) return 'free'
  return getTierFromPriceId(item.price.id)
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

        if (clerkUserId && session.subscription) {
          // Retrieve subscription to get tier info
          const subscription = await stripe.subscriptions.retrieve(
            session.subscription as string
          )
          const tier = getTierFromSubscription(subscription)

          // Generate license key for CLI
          const licenseKey = generateLicenseKey(tier)

          // Update user metadata with plan and license key
          await client.users.updateUserMetadata(clerkUserId, {
            publicMetadata: {
              plan: tier,
              stripeCustomerId: session.customer as string,
              stripeSubscriptionId: session.subscription as string,
            },
            privateMetadata: {
              licenseKey,
              licenseCreatedAt: new Date().toISOString(),
            },
          })

          // Store clerkUserId in Stripe customer for reverse lookup
          await stripe.customers.update(session.customer as string, {
            metadata: { clerkUserId },
          })
        }
        break
      }

      case "customer.subscription.deleted": {
        const subscription = event.data.object as Stripe.Subscription
        const customerId = subscription.customer as string

        // Find user by Stripe customer ID and downgrade
        const customer = await stripe.customers.retrieve(customerId)
        const clerkUserId = (customer as Stripe.Customer).metadata?.clerkUserId

        if (clerkUserId) {
          await client.users.updateUserMetadata(clerkUserId, {
            publicMetadata: {
              plan: "free",
              stripeSubscriptionId: null,
            },
            privateMetadata: {
              licenseKey: null,
              licenseRevokedAt: new Date().toISOString(),
            },
          })
        }
        break
      }

      case "customer.subscription.updated": {
        const subscription = event.data.object as Stripe.Subscription
        const customerId = subscription.customer as string

        // Check if subscription is active or past_due (still valid)
        if (subscription.status === 'active' || subscription.status === 'past_due') {
          const customer = await stripe.customers.retrieve(customerId)
          const clerkUserId = (customer as Stripe.Customer).metadata?.clerkUserId

          if (clerkUserId) {
            const tier = getTierFromSubscription(subscription)

            // Get current user to check if tier changed
            const user = await client.users.getUser(clerkUserId)
            const currentPlan = (user.publicMetadata as { plan?: string })?.plan

            if (currentPlan !== tier) {
              // Tier changed - generate new license key
              const licenseKey = generateLicenseKey(tier)

              await client.users.updateUserMetadata(clerkUserId, {
                publicMetadata: {
                  plan: tier,
                },
                privateMetadata: {
                  licenseKey,
                  licenseCreatedAt: new Date().toISOString(),
                },
              })
            }
          }
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
