"use client"

import { motion, AnimatePresence } from "framer-motion"
import { X, Upload, Sparkles, FileText, Code } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"

interface Props {
  open: boolean
  onClose: () => void
  isSignedIn: boolean
}

const proFeatures = [
  { icon: Upload, text: "Upload your own trace files" },
  { icon: Sparkles, text: "Live AI-powered analysis" },
  { icon: FileText, text: "Export reports (JSON, PDF)" },
  { icon: Code, text: "API access for CI/CD" },
]

export function UpgradeModal({ open, onClose, isSignedIn }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md"
          >
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-2xl relative">
              {/* Close button */}
              <button
                onClick={onClose}
                className="absolute top-4 right-4 text-gray-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>

              {/* Content */}
              <div className="text-center mb-6">
                <div className="w-16 h-16 rounded-full bg-sentinel-500/20 flex items-center justify-center mx-auto mb-4">
                  <Upload className="w-8 h-8 text-sentinel-400" />
                </div>
                <h2 className="text-2xl font-bold mb-2">Upgrade to Pro</h2>
                <p className="text-gray-400">
                  Analyze your own FPGA traces with AI-powered insights
                </p>
              </div>

              {/* Features */}
              <ul className="space-y-3 mb-6">
                {proFeatures.map((feature) => (
                  <li key={feature.text} className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-sentinel-500/10 flex items-center justify-center">
                      <feature.icon className="w-4 h-4 text-sentinel-400" />
                    </div>
                    <span>{feature.text}</span>
                  </li>
                ))}
              </ul>

              {/* Price */}
              <div className="text-center py-4 border-y border-dark-border mb-6">
                <div className="flex items-baseline justify-center gap-1">
                  <span className="text-3xl font-bold">€10</span>
                  <span className="text-gray-400">/month</span>
                </div>
                <p className="text-sm text-gray-400 mt-1">
                  Cancel anytime · 14-day money-back guarantee
                </p>
              </div>

              {/* CTA */}
              {isSignedIn ? (
                <Button
                  asChild
                  className="w-full bg-sentinel-500 hover:bg-sentinel-600"
                  size="lg"
                >
                  <Link href="/api/checkout">Subscribe to Pro</Link>
                </Button>
              ) : (
                <div className="space-y-2">
                  <Button
                    asChild
                    className="w-full bg-sentinel-500 hover:bg-sentinel-600"
                    size="lg"
                  >
                    <Link href="/sign-up">Create Account</Link>
                  </Button>
                  <p className="text-center text-sm text-gray-400">
                    Already have an account?{" "}
                    <Link href="/sign-in" className="text-sentinel-400 hover:underline">
                      Sign in
                    </Link>
                  </p>
                </div>
              )}

              {/* Demo link */}
              <p className="text-center text-sm text-gray-400 mt-4">
                Or{" "}
                <button onClick={onClose} className="text-sentinel-400 hover:underline">
                  continue with demo
                </button>
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
