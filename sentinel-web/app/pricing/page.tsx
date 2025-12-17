"use client"

import { useState } from "react"
import { motion } from "framer-motion"
import { Check, X, Zap, Loader2 } from "lucide-react"
import Link from "next/link"
import { useAuth } from "@/hooks/useAuth"
import { useSubscription } from "@/hooks/useSubscription"
import { Button } from "@/components/ui/button"

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    tier: "free",
    description: "Explore with demo data",
    features: [
      { text: "Pre-loaded demo traces", included: true },
      { text: "Full visualization", included: true },
      { text: "Prescription previews (20 lines)", included: true },
      { text: "CI exit codes", included: true },
      { text: "Full prescription code", included: false },
      { text: "Slack alerts", included: false },
      { text: "CLI license key", included: false },
      { text: "GitHub Action", included: false },
    ],
    cta: "Try Demo",
    ctaLink: "/demo",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$99",
    period: "per month",
    tier: "pro",
    description: "For individual engineers",
    features: [
      { text: "Everything in Free", included: true },
      { text: "Full prescription code + testbench", included: true },
      { text: "Fix downloads (.sv files)", included: true },
      { text: "Slack regression alerts", included: true },
      { text: "CLI license key", included: true },
      { text: "GitHub Action integration", included: true },
      { text: "API access", included: true },
      { text: "Priority support", included: true },
    ],
    cta: "Subscribe",
    ctaLink: "/api/checkout?tier=pro",
    highlighted: true,
  },
  {
    name: "Team",
    price: "$499",
    period: "per month",
    tier: "team",
    description: "For trading teams",
    features: [
      { text: "Everything in Pro", included: true },
      { text: "Compliance PDF reports", included: true },
      { text: "Custom patterns library", included: true },
      { text: "5 team seats", included: true },
      { text: "Team dashboard", included: true },
      { text: "Audit trail", included: true },
      { text: "Priority support", included: true },
      { text: "Onboarding call", included: true },
    ],
    cta: "Subscribe",
    ctaLink: "/api/checkout?tier=team",
    highlighted: false,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "contact us",
    tier: "enterprise",
    description: "For trading firms",
    features: [
      { text: "Everything in Team", included: true },
      { text: "On-premise deployment", included: true },
      { text: "Custom integrations", included: true },
      { text: "SLA guarantee", included: true },
      { text: "Unlimited seats", included: true },
      { text: "Training sessions", included: true },
      { text: "Source code access", included: true },
      { text: "Custom AI models", included: true },
    ],
    cta: "Contact Sales",
    ctaLink: "mailto:borja@sentinel-hft.com",
    highlighted: false,
  },
]

export default function PricingPage() {
  const { isSignedIn } = useAuth()
  const { plan: currentPlan, isPro } = useSubscription()
  const [loadingTier, setLoadingTier] = useState<string | null>(null)

  const handleSubscribe = async (tier: string) => {
    if (!isSignedIn) {
      window.location.href = `/sign-up?redirect_url=/pricing`
      return
    }

    setLoadingTier(tier)
    try {
      const res = await fetch(`/api/checkout?tier=${tier}`)
      const data = await res.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch (error) {
      console.error("Checkout error:", error)
    } finally {
      setLoadingTier(null)
    }
  }

  const getPlanButton = (plan: typeof plans[0]) => {
    const isCurrentPlan = currentPlan === plan.tier
    const isLoading = loadingTier === plan.tier

    if (plan.tier === "free") {
      return (
        <Button asChild variant="outline" className="w-full" size="lg">
          <Link href={plan.ctaLink}>{plan.cta}</Link>
        </Button>
      )
    }

    if (plan.tier === "enterprise") {
      return (
        <Button asChild variant="outline" className="w-full" size="lg">
          <Link href={plan.ctaLink}>{plan.cta}</Link>
        </Button>
      )
    }

    if (isCurrentPlan) {
      return (
        <Button disabled className="w-full" size="lg">
          Current Plan
        </Button>
      )
    }

    return (
      <Button
        onClick={() => handleSubscribe(plan.tier)}
        disabled={isLoading}
        className={`w-full ${
          plan.highlighted
            ? "bg-sentinel-500 hover:bg-sentinel-600"
            : "bg-dark-border hover:bg-gray-700"
        }`}
        size="lg"
      >
        {isLoading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading...
          </>
        ) : (
          plan.cta
        )}
      </Button>
    )
  }

  return (
    <div className="min-h-screen pt-24 pb-16">
      <div className="max-w-7xl mx-auto px-4">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-16"
        >
          <h1 className="text-4xl md:text-5xl font-bold mb-4">
            Simple, transparent <span className="text-sentinel-400">pricing</span>
          </h1>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            Start free with demo data. Upgrade when you&apos;re ready to analyze your own trading systems.
          </p>
        </motion.div>

        {/* Pricing cards */}
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-7xl mx-auto">
          {plans.map((plan, i) => (
            <motion.div
              key={plan.name}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.1 }}
              className={`relative rounded-2xl p-8 ${
                plan.highlighted
                  ? "bg-sentinel-500/10 border-2 border-sentinel-500"
                  : "bg-dark-card border border-dark-border"
              }`}
            >
              {plan.highlighted && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2">
                  <span className="px-4 py-1 bg-sentinel-500 text-white text-sm font-medium rounded-full">
                    Most Popular
                  </span>
                </div>
              )}

              <div className="text-center mb-8">
                <h2 className="text-2xl font-bold mb-2">{plan.name}</h2>
                <div className="flex items-baseline justify-center gap-1">
                  <span className="text-4xl font-bold">{plan.price}</span>
                  <span className="text-gray-400">/{plan.period}</span>
                </div>
                <p className="text-gray-400 mt-2">{plan.description}</p>
              </div>

              <ul className="space-y-4 mb-8">
                {plan.features.map((feature) => (
                  <li key={feature.text} className="flex items-start gap-3">
                    {feature.included ? (
                      <Check className="w-5 h-5 text-sentinel-500 shrink-0 mt-0.5" />
                    ) : (
                      <X className="w-5 h-5 text-gray-600 shrink-0 mt-0.5" />
                    )}
                    <span className={feature.included ? "" : "text-gray-500"}>
                      {feature.text}
                    </span>
                  </li>
                ))}
              </ul>

              {getPlanButton(plan)}
            </motion.div>
          ))}
        </div>

        {/* FAQ */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="mt-24 max-w-3xl mx-auto"
        >
          <h2 className="text-2xl font-bold text-center mb-8">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            <div className="bg-dark-card border border-dark-border rounded-lg p-6">
              <h3 className="font-semibold mb-2">Can I cancel anytime?</h3>
              <p className="text-gray-400">
                Yes, you can cancel your Pro subscription at any time. You&apos;ll keep access until the end of your billing period.
              </p>
            </div>
            <div className="bg-dark-card border border-dark-border rounded-lg p-6">
              <h3 className="font-semibold mb-2">What trace formats are supported?</h3>
              <p className="text-gray-400">
                Sentinel-HFT supports v1.0, v1.1, and v1.2 binary trace formats. See the documentation for format specifications.
              </p>
            </div>
            <div className="bg-dark-card border border-dark-border rounded-lg p-6">
              <h3 className="font-semibold mb-2">Is my data secure?</h3>
              <p className="text-gray-400">
                Yes. Uploaded traces are processed in memory and never stored. AI analysis is done via Anthropic&apos;s API with enterprise security.
              </p>
            </div>
            <div className="bg-dark-card border border-dark-border rounded-lg p-6">
              <h3 className="font-semibold mb-2">Do you offer refunds?</h3>
              <p className="text-gray-400">
                Yes, we offer a 14-day money-back guarantee if Pro doesn&apos;t meet your needs.
              </p>
            </div>
          </div>
        </motion.div>

        {/* CTA */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="mt-24 text-center"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-sentinel-500/10 rounded-full text-sentinel-400 mb-6">
            <Zap className="w-4 h-4" />
            <span>Start free, upgrade when ready</span>
          </div>
          <h2 className="text-3xl font-bold mb-4">
            Ready to catch nanosecond regressions?
          </h2>
          <p className="text-gray-400 mb-8 max-w-xl mx-auto">
            Join trading firms using Sentinel-HFT to verify FPGA latency with confidence.
          </p>
          <Button asChild size="lg" className="bg-sentinel-500 hover:bg-sentinel-600">
            <Link href="/demo">Try the Demo</Link>
          </Button>
        </motion.div>
      </div>
    </div>
  )
}
