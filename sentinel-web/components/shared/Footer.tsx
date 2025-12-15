"use client";

import Link from "next/link";
import { Github, Twitter, Mail, ExternalLink } from "lucide-react";
import { Logo } from "./Logo";

const footerLinks = {
  product: [
    { label: "Features", href: "/#features" },
    { label: "AI Analysis", href: "/analyze" },
    { label: "Live Demo", href: "/demo" },
    { label: "Documentation", href: "https://github.com/BorjaTR/Sentinel-HFT#readme", external: true },
  ],
  developers: [
    { label: "Getting Started", href: "https://github.com/BorjaTR/Sentinel-HFT#quick-start", external: true },
    { label: "API Reference", href: "https://github.com/BorjaTR/Sentinel-HFT#api", external: true },
    { label: "GitHub", href: "https://github.com/BorjaTR/Sentinel-HFT", external: true },
    { label: "PyPI", href: "https://pypi.org/project/sentinel-hft/", external: true },
  ],
  resources: [
    { label: "Trace Format", href: "https://github.com/BorjaTR/Sentinel-HFT#trace-format-v12", external: true },
    { label: "RTL Integration", href: "https://github.com/BorjaTR/Sentinel-HFT#rtl-integration", external: true },
    { label: "Grafana Dashboards", href: "https://github.com/BorjaTR/Sentinel-HFT#grafana-dashboard", external: true },
    { label: "GitHub Actions", href: "https://github.com/BorjaTR/Sentinel-HFT#github-action", external: true },
  ],
};

const socialLinks = [
  { icon: Github, href: "https://github.com/BorjaTR/Sentinel-HFT", label: "GitHub" },
  { icon: Twitter, href: "https://twitter.com/sentinel_hft", label: "Twitter" },
  { icon: Mail, href: "mailto:contact@sentinel-hft.dev", label: "Email" },
];

export function Footer() {
  return (
    <footer className="border-t border-dark-border bg-dark-bg/50">
      <div className="container mx-auto px-4 py-12">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-8 lg:gap-12">
          {/* Brand */}
          <div className="lg:col-span-2">
            <Logo size="lg" />
            <p className="mt-4 text-gray-400 text-sm max-w-md">
              FPGA-grade latency verification for high-frequency trading systems.
              Catch nanosecond regressions before they cost real money.
            </p>
            <div className="flex gap-4 mt-6">
              {socialLinks.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-sentinel-400 transition-colors"
                  aria-label={social.label}
                >
                  <social.icon size={20} />
                </a>
              ))}
            </div>
          </div>

          {/* Links */}
          <div>
            <h4 className="font-semibold text-white mb-4">Product</h4>
            <ul className="space-y-3">
              {footerLinks.product.map((link) => (
                <li key={link.label}>
                  {link.external ? (
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-400 hover:text-sentinel-400 transition-colors text-sm flex items-center gap-1"
                    >
                      {link.label}
                      <ExternalLink size={12} />
                    </a>
                  ) : (
                    <Link
                      href={link.href}
                      className="text-gray-400 hover:text-sentinel-400 transition-colors text-sm"
                    >
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-4">Developers</h4>
            <ul className="space-y-3">
              {footerLinks.developers.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-gray-400 hover:text-sentinel-400 transition-colors text-sm flex items-center gap-1"
                  >
                    {link.label}
                    <ExternalLink size={12} />
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-4">Resources</h4>
            <ul className="space-y-3">
              {footerLinks.resources.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-gray-400 hover:text-sentinel-400 transition-colors text-sm flex items-center gap-1"
                  >
                    {link.label}
                    <ExternalLink size={12} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="border-t border-dark-border mt-12 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-gray-500 text-sm">
            &copy; {new Date().getFullYear()} Sentinel-HFT. Open source under MIT License.
          </p>
          <div className="flex gap-6 text-sm">
            <a
              href="https://github.com/BorjaTR/Sentinel-HFT/blob/main/LICENSE"
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-500 hover:text-gray-400 transition-colors"
            >
              License
            </a>
            <a
              href="https://github.com/BorjaTR/Sentinel-HFT/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-500 hover:text-gray-400 transition-colors"
            >
              Report Issue
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
