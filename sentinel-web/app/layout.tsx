import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Navigation } from "@/components/shared/Navigation";
import { Footer } from "@/components/shared/Footer";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Sentinel-HFT | FPGA-Grade Latency Verification",
  description:
    "Catch nanosecond regressions before they cost real money. Hardware-level tracing with AI-powered root cause analysis for high-frequency trading systems.",
  keywords: [
    "FPGA",
    "HFT",
    "latency",
    "verification",
    "trading",
    "RTL",
    "observability",
  ],
  authors: [{ name: "Sentinel-HFT Team" }],
  openGraph: {
    title: "Sentinel-HFT | FPGA-Grade Latency Verification",
    description:
      "Catch nanosecond regressions before they cost real money. Hardware-level tracing with AI-powered root cause analysis.",
    type: "website",
    url: "https://sentinel-hft.dev",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Sentinel-HFT",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Sentinel-HFT | FPGA-Grade Latency Verification",
    description:
      "Catch nanosecond regressions before they cost real money.",
    images: ["/og-image.png"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased bg-dark-bg text-white`}
      >
        <TooltipProvider>
          <Navigation />
          <main className="min-h-screen">{children}</main>
          <Footer />
        </TooltipProvider>
      </body>
    </html>
  );
}
