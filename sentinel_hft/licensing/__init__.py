"""
Sentinel-HFT License Management

Freemium model:
- Free: Full analysis, prescription previews, CI exit codes
- Pro ($99/mo): Full prescriptions, Slack, GitHub Action
- Team ($499/mo): Compliance PDF, custom patterns, 5 seats
"""

import os
import re
import json
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict
from enum import Enum
import urllib.request
import urllib.error


logger = logging.getLogger(__name__)


class Tier(Enum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"
    ENTERPRISE = "enterprise"

    @property
    def level(self) -> int:
        """Numeric level for comparison."""
        return {"free": 0, "pro": 1, "team": 2, "enterprise": 3}[self.value]

    def __ge__(self, other: "Tier") -> bool:
        return self.level >= other.level

    def __gt__(self, other: "Tier") -> bool:
        return self.level > other.level


# Feature definitions with required tier
FEATURES = {
    # Free features
    "analyze": Tier.FREE,
    "attribution": Tier.FREE,
    "anomalies": Tier.FREE,
    "regression": Tier.FREE,
    "ci_exit_codes": Tier.FREE,
    "prescription_preview": Tier.FREE,

    # Pro features ($99/mo)
    "prescription_full": Tier.PRO,
    "fix_download": Tier.PRO,
    "testbench_generation": Tier.PRO,
    "slack_alerts": Tier.PRO,
    "github_action": Tier.PRO,
    "api_access": Tier.PRO,

    # Team features ($499/mo)
    "compliance_pdf": Tier.TEAM,
    "custom_patterns": Tier.TEAM,
    "multiple_seats": Tier.TEAM,
}

# Limits by tier
LIMITS = {
    Tier.FREE: {
        "prescription_preview_lines": 20,
        "max_prescriptions_shown": 3,
        "seats": 1,
    },
    Tier.PRO: {
        "prescription_preview_lines": None,  # Unlimited
        "max_prescriptions_shown": None,
        "seats": 1,
    },
    Tier.TEAM: {
        "prescription_preview_lines": None,
        "max_prescriptions_shown": None,
        "seats": 5,
    },
    Tier.ENTERPRISE: {
        "prescription_preview_lines": None,
        "max_prescriptions_shown": None,
        "seats": None,  # Unlimited
    },
}


@dataclass
class License:
    """License information."""
    tier: Tier
    valid: bool
    key: Optional[str] = None
    org_name: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[int] = None  # Unix timestamp
    seats: int = 1
    error: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_active(self) -> bool:
        return self.valid and not self.is_expired

    @property
    def effective_tier(self) -> Tier:
        """Return FREE if license is invalid/expired."""
        return self.tier if self.is_active else Tier.FREE


class LicenseManager:
    """Manage license validation and feature access."""

    # API endpoint for online validation
    API_URL = "https://api.sentinel-hft.com/v1/license/validate"

    # Cache file location
    CACHE_FILE = Path.home() / ".sentinel-hft" / "license_cache.json"
    CACHE_TTL = 86400  # 24 hours

    def __init__(self):
        self._license: Optional[License] = None
        self._cache_dir = Path.home() / ".sentinel-hft"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get_license(self) -> License:
        """Get current license, validating if necessary."""
        if self._license is not None:
            return self._license

        key = os.environ.get("SENTINEL_LICENSE_KEY", "").strip()

        if not key:
            self._license = License(tier=Tier.FREE, valid=True)
            return self._license

        # Try cache first
        cached = self._load_cache(key)
        if cached:
            self._license = cached
            return self._license

        # Validate key
        self._license = self._validate_key(key)

        # Cache result
        if self._license.valid:
            self._save_cache(key, self._license)

        return self._license

    def _validate_key(self, key: str) -> License:
        """Validate a license key."""

        # Check format: sl_{env}_{tier}_{random}
        pattern = r'^sl_(test|live)_(pro|team|ent)_([a-zA-Z0-9]{12,})$'
        match = re.match(pattern, key)

        if not match:
            return License(
                tier=Tier.FREE,
                valid=False,
                key=key,
                error="Invalid license key format"
            )

        env, tier_code, _ = match.groups()

        # Map tier code to Tier enum
        tier_map = {"pro": Tier.PRO, "team": Tier.TEAM, "ent": Tier.ENTERPRISE}
        tier = tier_map.get(tier_code, Tier.FREE)

        # Test keys always work (for development)
        if env == "test":
            return License(
                tier=tier,
                valid=True,
                key=key,
                org_name="Test Organization",
                email="test@example.com"
            )

        # Live keys: try online validation, fall back to offline
        try:
            return self._validate_online(key)
        except Exception as e:
            logger.debug(f"Online validation failed: {e}")
            # Offline validation: trust the key format for 24h grace period
            return License(
                tier=tier,
                valid=True,
                key=key,
                error="Offline mode - online validation will retry"
            )

    def _validate_online(self, key: str) -> License:
        """Validate key with API server."""
        try:
            data = json.dumps({"key": key}).encode()
            req = urllib.request.Request(
                self.API_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())

            if not result.get("valid"):
                return License(
                    tier=Tier.FREE,
                    valid=False,
                    key=key,
                    error=result.get("error", "Invalid license")
                )

            return License(
                tier=Tier(result.get("tier", "free")),
                valid=True,
                key=key,
                org_name=result.get("org_name"),
                email=result.get("email"),
                expires_at=result.get("expires_at"),
                seats=result.get("seats", 1)
            )

        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            raise RuntimeError(f"Online validation failed: {e}")

    def _load_cache(self, key: str) -> Optional[License]:
        """Load cached license if valid."""
        try:
            if not self.CACHE_FILE.exists():
                return None

            with open(self.CACHE_FILE) as f:
                data = json.load(f)

            # Check if cache is for this key and not expired
            if data.get("key") != key:
                return None

            cache_time = data.get("cached_at", 0)
            if time.time() - cache_time > self.CACHE_TTL:
                return None

            return License(
                tier=Tier(data.get("tier", "free")),
                valid=data.get("valid", False),
                key=key,
                org_name=data.get("org_name"),
                email=data.get("email"),
                expires_at=data.get("expires_at"),
                seats=data.get("seats", 1)
            )

        except Exception:
            return None

    def _save_cache(self, key: str, license: License):
        """Cache license validation result."""
        try:
            data = {
                "key": key,
                "tier": license.tier.value,
                "valid": license.valid,
                "org_name": license.org_name,
                "email": license.email,
                "expires_at": license.expires_at,
                "seats": license.seats,
                "cached_at": time.time()
            }

            with open(self.CACHE_FILE, "w") as f:
                json.dump(data, f)

        except Exception:
            pass  # Caching is best-effort

    def check_feature(self, feature: str) -> bool:
        """Check if a feature is available."""
        required_tier = FEATURES.get(feature)
        if required_tier is None:
            return True  # Unknown features are allowed

        license = self.get_license()
        return license.effective_tier >= required_tier

    def get_limit(self, limit_name: str) -> Optional[int]:
        """Get a limit value for current tier."""
        license = self.get_license()
        tier_limits = LIMITS.get(license.effective_tier, LIMITS[Tier.FREE])
        return tier_limits.get(limit_name)

    def require_feature(self, feature: str, action: str = None):
        """Raise error if feature not available with upgrade prompt."""
        if self.check_feature(feature):
            return

        required_tier = FEATURES.get(feature, Tier.PRO)
        license = self.get_license()
        action_text = action or feature.replace("_", " ").title()

        raise FeatureRequiresUpgrade(
            feature=feature,
            required_tier=required_tier,
            current_tier=license.effective_tier,
            action=action_text
        )


class FeatureRequiresUpgrade(Exception):
    """Raised when a feature requires a higher tier."""

    def __init__(self, feature: str, required_tier: Tier,
                 current_tier: Tier, action: str):
        self.feature = feature
        self.required_tier = required_tier
        self.current_tier = current_tier
        self.action = action

        # Price info
        prices = {Tier.PRO: "$99/mo", Tier.TEAM: "$499/mo"}
        price = prices.get(required_tier, "")

        super().__init__(
            f"\n"
            f"┌{'─' * 52}┐\n"
            f"│{'PRO FEATURE':^52}│\n"
            f"├{'─' * 52}┤\n"
            f"│{f'{action} requires {required_tier.value.title()} plan':^52}│\n"
            f"│{' ':^52}│\n"
            f"│{f'Upgrade ({price}): sentinel-hft.com/pricing':^52}│\n"
            f"└{'─' * 52}┘"
        )


# Global instance
_manager: Optional[LicenseManager] = None


def get_manager() -> LicenseManager:
    """Get global license manager."""
    global _manager
    if _manager is None:
        _manager = LicenseManager()
    return _manager


# Convenience functions
def get_license() -> License:
    """Get current license."""
    return get_manager().get_license()


def check_feature(feature: str) -> bool:
    """Check if feature is available."""
    return get_manager().check_feature(feature)


def require_feature(feature: str, action: str = None):
    """Require a feature, raise if not available."""
    get_manager().require_feature(feature, action)


def get_limit(limit_name: str) -> Optional[int]:
    """Get a limit value."""
    return get_manager().get_limit(limit_name)


def get_tier() -> Tier:
    """Get current effective tier."""
    return get_manager().get_license().effective_tier
