import type { ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  Shield,
  Zap,
  FileCheck,
  ShieldCheck,
  Brain,
  Siren,
  Scale,
} from "lucide-react";

// Trading-floor dark shell. Top bar + left nav + main content.
// Styled with pure Tailwind utility classes that are already in the
// sentinel-web Tailwind config.

const DRILL_NAV = [
  {
    href: "/sentinel",
    label: "Overview",
    icon: Activity,
  },
  {
    href: "/sentinel/toxic_flow",
    label: "Toxic flow",
    icon: Shield,
  },
  {
    href: "/sentinel/kill_drill",
    label: "Kill switch",
    icon: Zap,
  },
  {
    href: "/sentinel/latency",
    label: "Latency",
    icon: Activity,
  },
  {
    href: "/sentinel/daily_evidence",
    label: "Daily evidence",
    icon: FileCheck,
  },
  {
    href: "/sentinel/audit",
    label: "Audit verifier",
    icon: ShieldCheck,
  },
  {
    href: "/sentinel/regulations",
    label: "Regulations",
    icon: Scale,
  },
  {
    href: "/sentinel/rca",
    label: "RCA digest",
    icon: Brain,
  },
  {
    href: "/sentinel/triage",
    label: "Triage alerts",
    icon: Siren,
  },
];

export default function SentinelLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0a0e14] text-[#d5e0ea]">
      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b border-[#1a232e] bg-[#0a0e14]/95 backdrop-blur">
        <div className="flex h-14 items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <span className="font-mono text-sm font-semibold tracking-wider text-[#9ab3c8]">
              SENTINEL-HFT
            </span>
            <span className="rounded border border-[#1f2a38] bg-[#0f151d] px-2 py-0.5 font-mono text-[10px] text-[#6b8196]">
              v1.0.0-core-audit-closed
            </span>
          </div>
          <div className="flex items-center gap-4 font-mono text-xs text-[#6b8196]">
            <span>U55C · 322 MHz CMAC · 100 MHz datapath</span>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Left nav */}
        <aside className="sticky top-14 h-[calc(100vh-3.5rem)] w-56 shrink-0 border-r border-[#1a232e] bg-[#0a0e14] p-3">
          <nav className="flex flex-col gap-0.5">
            <div className="mb-2 px-2 font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
              Drills
            </div>
            {DRILL_NAV.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="group flex items-center gap-2 rounded-md px-2 py-2 font-mono text-xs text-[#9ab3c8] transition hover:bg-[#131c27] hover:text-[#e4edf5]"
              >
                <Icon className="h-3.5 w-3.5 text-[#4d617a] group-hover:text-emerald-400" />
                {label}
              </Link>
            ))}
          </nav>
          <div className="mt-6 rounded-md border border-[#1a232e] bg-[#0f151d] p-3 font-mono text-[10px] leading-relaxed text-[#6b8196]">
            <div className="mb-1 text-[#9ab3c8]">Backend</div>
            <div>/api/drills</div>
            <div>/api/audit/verify</div>
            <div>/api/drills/&#123;k&#125;/stream</div>
            <div>/api/compliance/crosswalk</div>
            <div>/api/ai/rca/&#123;list,run,date&#125;</div>
            <div>/api/ai/triage/&#123;alerts,eval&#125;</div>
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
