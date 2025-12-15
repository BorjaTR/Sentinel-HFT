import { Hero } from "@/components/landing/Hero";
import { TerminalDemo } from "@/components/landing/TerminalDemo";
import { Features } from "@/components/landing/Features";
import { Stats } from "@/components/landing/Stats";
import { Architecture } from "@/components/landing/Architecture";
import { CTA } from "@/components/landing/CTA";

export default function Home() {
  return (
    <>
      <Hero />
      <TerminalDemo />
      <Features />
      <Stats />
      <Architecture />
      <CTA />
    </>
  );
}
