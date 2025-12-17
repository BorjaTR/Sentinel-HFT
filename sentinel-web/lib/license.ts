/**
 * License key utilities for Sentinel-HFT
 *
 * Key format: sl_{env}_{tier}_{random}
 * Example: sl_live_pro_abc123def456gh
 */

import { randomBytes } from 'crypto';

export type Tier = 'free' | 'pro' | 'team' | 'enterprise';

export interface LicenseInfo {
  key: string;
  tier: Tier;
  createdAt: Date;
  expiresAt: Date | null;
  isValid: boolean;
}

/**
 * Generate a new license key for the given tier.
 */
export function generateLicenseKey(tier: Tier): string {
  const random = randomBytes(12).toString('base64url').slice(0, 16);
  return `sl_live_${tier}_${random}`;
}

/**
 * Parse a license key and extract its components.
 */
export function parseLicenseKey(key: string): {
  env: string;
  tier: Tier;
  id: string
} | null {
  const pattern = /^sl_(test|live)_(pro|team|ent|enterprise)_([a-zA-Z0-9_-]{12,})$/;
  const match = key.match(pattern);

  if (!match) {
    return null;
  }

  const [, env, tierCode, id] = match;

  // Map tier codes
  const tierMap: Record<string, Tier> = {
    pro: 'pro',
    team: 'team',
    ent: 'enterprise',
    enterprise: 'enterprise',
  };

  return {
    env,
    tier: tierMap[tierCode] || 'pro',
    id,
  };
}

/**
 * Validate a license key format (doesn't check expiration).
 */
export function isValidKeyFormat(key: string): boolean {
  return parseLicenseKey(key) !== null;
}

/**
 * Get tier display name.
 */
export function getTierDisplayName(tier: Tier): string {
  const names: Record<Tier, string> = {
    free: 'Free',
    pro: 'Pro',
    team: 'Team',
    enterprise: 'Enterprise',
  };
  return names[tier] || 'Unknown';
}

/**
 * Get tier price display.
 */
export function getTierPrice(tier: Tier): string {
  const prices: Record<Tier, string> = {
    free: 'Free',
    pro: '$99/mo',
    team: '$499/mo',
    enterprise: 'Contact us',
  };
  return prices[tier] || '';
}

/**
 * Map Stripe price IDs to tiers.
 */
export function getTierFromPriceId(priceId: string): Tier {
  // These should match your Stripe price IDs
  const priceToTier: Record<string, Tier> = {
    [process.env.STRIPE_PRO_PRICE_ID || '']: 'pro',
    [process.env.STRIPE_TEAM_PRICE_ID || '']: 'team',
  };

  return priceToTier[priceId] || 'free';
}

/**
 * Get Stripe price ID for a tier.
 */
export function getPriceIdForTier(tier: Tier): string | null {
  const tierToPrice: Record<Tier, string | undefined> = {
    free: undefined,
    pro: process.env.STRIPE_PRO_PRICE_ID,
    team: process.env.STRIPE_TEAM_PRICE_ID,
    enterprise: undefined,
  };

  return tierToPrice[tier] || null;
}

/**
 * Calculate expiration date (1 year from now for annual, or billing period end).
 */
export function calculateExpirationDate(billingPeriodEnd?: number): Date {
  if (billingPeriodEnd) {
    // Use Stripe's billing period end + grace period
    return new Date((billingPeriodEnd + 7 * 24 * 60 * 60) * 1000); // 7 day grace
  }
  // Default: 1 year from now
  return new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
}

/**
 * Mask a license key for display (show first and last parts).
 */
export function maskLicenseKey(key: string): string {
  if (key.length < 20) return '****';

  const prefix = key.slice(0, 12); // sl_live_pro_
  const suffix = key.slice(-4);
  return `${prefix}****${suffix}`;
}
