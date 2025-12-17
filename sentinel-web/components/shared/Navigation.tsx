"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X, Github, LayoutDashboard } from "lucide-react";
import { Logo } from "./Logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AuthButtons } from "./AuthButtons";
import { useAuth } from "@/hooks/useAuth";

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/analyze", label: "AI Analysis" },
  { href: "/demo", label: "Live Demo" },
  { href: "/pricing", label: "Pricing" },
];

export function Navigation() {
  const [isOpen, setIsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();
  const { isSignedIn } = useAuth();

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <motion.header
      initial={{ y: -100 }}
      animate={{ y: 0 }}
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-300",
        scrolled
          ? "bg-dark-bg/80 backdrop-blur-xl border-b border-dark-border"
          : "bg-transparent"
      )}
    >
      <nav className="container mx-auto px-4 h-16 flex items-center justify-between">
        <Link href="/" className="z-50">
          <Logo size="md" />
        </Link>

        {/* Desktop Navigation */}
        <div className="hidden md:flex items-center gap-8">
          <div className="flex items-center gap-6">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "text-sm font-medium transition-colors hover:text-sentinel-400",
                  pathname === link.href
                    ? "text-sentinel-400"
                    : "text-gray-400"
                )}
              >
                {link.label}
              </Link>
            ))}
          </div>

          <div className="flex items-center gap-3">
            {isSignedIn && (
              <Link
                href="/dashboard"
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
                  pathname === "/dashboard"
                    ? "bg-sentinel-500/20 text-sentinel-400"
                    : "text-gray-400 hover:text-white hover:bg-dark-border"
                )}
              >
                <LayoutDashboard size={16} />
                Dashboard
              </Link>
            )}
            <Button variant="ghost" size="sm" asChild>
              <a
                href="https://github.com/BorjaTR/Sentinel-HFT"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2"
              >
                <Github size={18} />
                <span>GitHub</span>
              </a>
            </Button>

            <AuthButtons size="sm" />
          </div>
        </div>

        {/* Mobile Menu Button */}
        <button
          className="md:hidden z-50 p-2"
          onClick={() => setIsOpen(!isOpen)}
          aria-label="Toggle menu"
        >
          {isOpen ? <X size={24} /> : <Menu size={24} />}
        </button>

        {/* Mobile Navigation */}
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="fixed inset-0 top-16 bg-dark-bg/95 backdrop-blur-xl md:hidden"
            >
              <div className="flex flex-col items-center justify-center h-full gap-8">
                {navLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={() => setIsOpen(false)}
                    className={cn(
                      "text-2xl font-medium transition-colors hover:text-sentinel-400",
                      pathname === link.href
                        ? "text-sentinel-400"
                        : "text-gray-400"
                    )}
                  >
                    {link.label}
                  </Link>
                ))}
                {isSignedIn && (
                  <Link
                    href="/dashboard"
                    onClick={() => setIsOpen(false)}
                    className={cn(
                      "flex items-center gap-2 text-2xl font-medium transition-colors hover:text-sentinel-400",
                      pathname === "/dashboard"
                        ? "text-sentinel-400"
                        : "text-gray-400"
                    )}
                  >
                    <LayoutDashboard size={24} />
                    Dashboard
                  </Link>
                )}
                <div className="flex flex-col items-center gap-4 mt-8">
                  <Button variant="ghost" size="lg" asChild>
                    <a
                      href="https://github.com/BorjaTR/Sentinel-HFT"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2"
                    >
                      <Github size={20} />
                      <span>GitHub</span>
                    </a>
                  </Button>

                  <AuthButtons size="lg" onNavigate={() => setIsOpen(false)} />
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </nav>
    </motion.header>
  );
}
