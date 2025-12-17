"""Upgrade prompts for CLI output."""

from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

from . import get_tier, get_license, Tier, FEATURES


def _print(msg: str, style: str = None):
    """Print with optional styling."""
    if HAS_RICH and console:
        console.print(msg, style=style)
    else:
        print(msg)


def show_upgrade_prompt(feature: str, context: str = None):
    """Show a contextual upgrade prompt."""
    required_tier = FEATURES.get(feature, Tier.PRO)
    current_tier = get_tier()

    if current_tier >= required_tier:
        return  # No upgrade needed

    prices = {
        Tier.PRO: ("$99/mo", [
            "Full prescription code",
            "Fix downloads",
            "Testbench generation",
            "Slack alerts",
            "GitHub Action",
        ]),
        Tier.TEAM: ("$499/mo", [
            "Everything in Pro",
            "Compliance PDF reports",
            "Custom patterns",
            "5 team seats",
            "Priority support",
        ]),
    }

    price, features = prices.get(required_tier, ("", []))

    _print("")
    _print("─" * 54, "yellow")

    if context:
        _print(f"  {context}", "yellow")
        _print("")

    _print(f"  Upgrade to {required_tier.value.title()} ({price}):", "yellow bold")
    for f in features[:4]:
        _print(f"    ✓ {f}", "yellow")

    _print("")
    _print("  → sentinel-hft.com/pricing", "cyan bold")
    _print("─" * 54, "yellow")
    _print("")


def show_prescription_preview_notice(total_lines: int, preview_lines: int):
    """Show notice when prescription is truncated."""
    _print("")
    _print(f"  ┌{'─' * 48}┐", "bright_black")
    _print(f"  │{' ' * 48}│", "bright_black")
    _print(f"  │{'PREVIEW - Showing first ' + str(preview_lines) + ' of ' + str(total_lines) + ' lines':^48}│", "yellow")
    _print(f"  │{' ' * 48}│", "bright_black")
    _print(f"  │{'Upgrade to Pro for full code + testbench':^48}│", "bright_black")
    _print(f"  │{'→ sentinel-hft.com/pricing':^48}│", "cyan")
    _print(f"  │{' ' * 48}│", "bright_black")
    _print(f"  └{'─' * 48}┘", "bright_black")


def show_slack_upgrade_prompt():
    """Show prompt when Slack alerts would be useful."""
    if get_tier() >= Tier.PRO:
        return  # Already has access

    _print("")
    _print("💡 Tip: Get Slack alerts when regressions are detected", "bright_black")
    _print("   Upgrade to Pro: sentinel-hft.com/pricing", "bright_black")


def show_compliance_upgrade_prompt():
    """Show prompt for compliance PDF feature."""
    _print("")
    _print("─" * 54, "yellow")
    _print("  📄 Need a compliance report for auditors?", "yellow")
    _print("")
    _print("  Team plan includes:", "yellow")
    _print("    ✓ MiFID II / SEC compliance PDFs", "yellow")
    _print("    ✓ Audit-ready documentation", "yellow")
    _print("    ✓ Executive summaries", "yellow")
    _print("")
    _print("  → sentinel-hft.com/pricing", "cyan bold")
    _print("─" * 54, "yellow")


def show_tier_status():
    """Show current tier status."""
    license = get_license()
    tier = license.effective_tier

    tier_colors = {
        Tier.FREE: "white",
        Tier.PRO: "green",
        Tier.TEAM: "blue",
        Tier.ENTERPRISE: "magenta",
    }

    color = tier_colors.get(tier, "white")

    if tier == Tier.FREE:
        _print(f"License: Free tier", color)
        _print("  Upgrade for full features: sentinel-hft.com/pricing", "bright_black")
    else:
        org = license.org_name or "Personal"
        _print(f"License: {tier.value.title()} ({org})", color)

        if license.expires_at:
            import time
            days_left = int((license.expires_at - time.time()) / 86400)
            if days_left < 30:
                _print(f"  Expires in {days_left} days", "yellow")
