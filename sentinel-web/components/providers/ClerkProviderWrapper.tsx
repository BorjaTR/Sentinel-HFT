"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { ReactNode } from "react";

interface Props {
  children: ReactNode;
}

export function ClerkProviderWrapper({ children }: Props) {
  // Check if we have a valid Clerk key (starts with pk_test_ or pk_live_)
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  const hasValidKey = publishableKey &&
    (publishableKey.startsWith("pk_test_") || publishableKey.startsWith("pk_live_")) &&
    publishableKey.length > 20;

  // If no valid key, just render children without Clerk
  if (!hasValidKey) {
    return <>{children}</>;
  }

  return (
    <ClerkProvider
      appearance={{
        baseTheme: dark,
        variables: {
          colorPrimary: "#22c55e",
          colorBackground: "#0a0a0a",
          colorInputBackground: "#141414",
          colorInputText: "#ffffff",
        },
        elements: {
          formButtonPrimary: "bg-sentinel-500 hover:bg-sentinel-600",
          card: "bg-dark-card border border-dark-border",
        },
      }}
    >
      {children}
    </ClerkProvider>
  );
}
