"""Protocol context for trading analysis."""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import json


@dataclass
class ProtocolHealth:
    """Protocol health snapshot."""
    protocol_id: str
    protocol_name: str

    # Health scores (from Sentinel)
    overall_score: float            # 0-100
    health_tier: str                # 'A', 'B', 'C', 'D', 'F'

    # Financial metrics
    treasury_usd: float
    runway_months: float
    burn_rate_monthly: float

    # Governance metrics
    active_proposals: int
    governance_participation: float  # 0-1
    recent_votes: int               # Last 30 days

    # Risk indicators
    risk_flags: List[str]           # e.g., ['treasury_declining', 'low_governance']
    risk_level: str                 # 'low', 'medium', 'high', 'critical'

    # Metadata
    fetched_at: str
    data_staleness_hours: float

    def to_dict(self) -> dict:
        return {
            'protocol_id': self.protocol_id,
            'protocol_name': self.protocol_name,
            'health': {
                'overall_score': self.overall_score,
                'tier': self.health_tier,
            },
            'financial': {
                'treasury_usd': self.treasury_usd,
                'runway_months': self.runway_months,
                'burn_rate_monthly': self.burn_rate_monthly,
            },
            'governance': {
                'active_proposals': self.active_proposals,
                'participation_rate': self.governance_participation,
                'recent_votes': self.recent_votes,
            },
            'risk': {
                'flags': self.risk_flags,
                'level': self.risk_level,
            },
            'metadata': {
                'fetched_at': self.fetched_at,
                'staleness_hours': self.data_staleness_hours,
            },
        }

    def to_summary(self) -> str:
        """One-line summary for reports."""
        return (
            f"{self.protocol_name}: {self.health_tier}-tier health, "
            f"{self.runway_months:.0f}mo runway, "
            f"${self.treasury_usd/1e6:.1f}M treasury"
        )


@dataclass
class GovernanceEvent:
    """A governance event that might affect trading."""
    event_type: str                 # 'proposal_created', 'vote_started', 'vote_ended', 'execution'
    event_id: str
    title: str
    timestamp: str
    impact_level: str               # 'low', 'medium', 'high'

    # Optional details
    vote_outcome: Optional[str] = None
    treasury_impact_usd: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'type': self.event_type,
            'id': self.event_id,
            'title': self.title,
            'timestamp': self.timestamp,
            'impact': self.impact_level,
            'vote_outcome': self.vote_outcome,
            'treasury_impact_usd': self.treasury_impact_usd,
        }


@dataclass
class ProtocolContext:
    """Complete protocol context for a trading session."""
    health: ProtocolHealth
    recent_events: List[GovernanceEvent]

    # Time window
    analysis_start: str
    analysis_end: str

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'health': self.health.to_dict(),
            'recent_events': [e.to_dict() for e in self.recent_events],
            'analysis_window': {
                'start': self.analysis_start,
                'end': self.analysis_end,
            },
            'warnings': self.warnings,
        }

    def has_active_governance(self) -> bool:
        """Check if there's active governance during analysis window."""
        return self.health.active_proposals > 0

    def has_risk_flags(self) -> bool:
        """Check if protocol has any risk flags."""
        return len(self.health.risk_flags) > 0


class ProtocolContextProvider:
    """Provides protocol context for trading analysis."""

    def __init__(
        self,
        sentinel_path: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: float = 1.0,
    ):
        """
        Initialize provider.

        Args:
            sentinel_path: Path to Sentinel package (for direct import)
            cache_dir: Directory for caching protocol data
            cache_ttl_hours: How long to cache data
        """
        self.sentinel_path = sentinel_path
        self.cache_dir = cache_dir or Path.home() / '.sentinel-hft' / 'cache'
        self.cache_ttl_hours = cache_ttl_hours

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Try to import Sentinel
        self._sentinel = None
        self._load_sentinel()

    def _load_sentinel(self):
        """Try to load Sentinel package."""
        try:
            # Option 1: Installed as package
            from sentinel import ProtocolAnalyzer
            self._sentinel = ProtocolAnalyzer
        except ImportError:
            try:
                # Option 2: Path provided
                if self.sentinel_path:
                    import sys
                    sys.path.insert(0, str(self.sentinel_path))
                    from sentinel import ProtocolAnalyzer
                    self._sentinel = ProtocolAnalyzer
            except ImportError:
                pass

    def get_context(
        self,
        protocol_id: str,
        analysis_start: Optional[datetime] = None,
        analysis_end: Optional[datetime] = None,
    ) -> Optional[ProtocolContext]:
        """
        Get protocol context for analysis.

        Args:
            protocol_id: Protocol identifier (e.g., 'arbitrum', 'optimism')
            analysis_start: Start of analysis window
            analysis_end: End of analysis window

        Returns:
            ProtocolContext or None if unavailable
        """
        # Check cache first
        cached = self._get_cached(protocol_id)
        if cached:
            return cached

        # Try to fetch fresh data
        if self._sentinel:
            context = self._fetch_from_sentinel(protocol_id, analysis_start, analysis_end)
            if context:
                return context

        # Try to load from static config
        return self._load_static_config(protocol_id, analysis_start, analysis_end)

    def _get_cached(self, protocol_id: str) -> Optional[ProtocolContext]:
        """Get cached context if fresh enough."""
        cache_file = self.cache_dir / f"{protocol_id}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)

            # Check staleness
            fetched_at = datetime.fromisoformat(data['health']['metadata']['fetched_at'])
            age_hours = (datetime.now() - fetched_at).total_seconds() / 3600

            if age_hours > self.cache_ttl_hours:
                return None

            return self._dict_to_context(data)
        except Exception:
            return None

    def _fetch_from_sentinel(
        self,
        protocol_id: str,
        analysis_start: Optional[datetime],
        analysis_end: Optional[datetime],
    ) -> Optional[ProtocolContext]:
        """Fetch fresh data from Sentinel."""
        try:
            analyzer = self._sentinel(protocol_id)

            # Run analysis
            result = analyzer.analyze()

            # Convert to our format
            health = ProtocolHealth(
                protocol_id=protocol_id,
                protocol_name=result.get('name', protocol_id),
                overall_score=result.get('health_score', 0),
                health_tier=self._score_to_tier(result.get('health_score', 0)),
                treasury_usd=result.get('treasury', {}).get('total_usd', 0),
                runway_months=result.get('runway', {}).get('months', 0),
                burn_rate_monthly=result.get('runway', {}).get('burn_rate', 0),
                active_proposals=result.get('governance', {}).get('active_proposals', 0),
                governance_participation=result.get('governance', {}).get('participation', 0),
                recent_votes=result.get('governance', {}).get('recent_votes', 0),
                risk_flags=result.get('risk_flags', []),
                risk_level=result.get('risk_level', 'unknown'),
                fetched_at=datetime.now().isoformat(),
                data_staleness_hours=0,
            )

            # Get governance events
            events = []
            for event in result.get('governance_events', []):
                events.append(GovernanceEvent(
                    event_type=event.get('type', 'unknown'),
                    event_id=event.get('id', ''),
                    title=event.get('title', ''),
                    timestamp=event.get('timestamp', ''),
                    impact_level=event.get('impact', 'low'),
                    vote_outcome=event.get('outcome'),
                    treasury_impact_usd=event.get('treasury_impact'),
                ))

            context = ProtocolContext(
                health=health,
                recent_events=events,
                analysis_start=(analysis_start or datetime.now() - timedelta(days=1)).isoformat(),
                analysis_end=(analysis_end or datetime.now()).isoformat(),
            )

            # Cache it
            self._cache_context(protocol_id, context)

            return context

        except Exception:
            return None

    def _load_static_config(
        self,
        protocol_id: str,
        analysis_start: Optional[datetime],
        analysis_end: Optional[datetime],
    ) -> Optional[ProtocolContext]:
        """Load from static configuration file."""
        # Try protocol-specific config
        config_file = Path(__file__).parent / 'configs' / f"{protocol_id}.json"

        if not config_file.exists():
            # Try default config
            config_file = Path(__file__).parent / 'configs' / 'default.json'

        if not config_file.exists():
            return None

        try:
            with open(config_file) as f:
                data = json.load(f)

            context = self._dict_to_context(data)

            # Update analysis window
            context.analysis_start = (analysis_start or datetime.now() - timedelta(days=1)).isoformat()
            context.analysis_end = (analysis_end or datetime.now()).isoformat()

            return context
        except Exception:
            return None

    def _cache_context(self, protocol_id: str, context: ProtocolContext):
        """Cache context to disk."""
        cache_file = self.cache_dir / f"{protocol_id}.json"

        try:
            with open(cache_file, 'w') as f:
                json.dump(context.to_dict(), f, indent=2)
        except Exception:
            pass

    def _dict_to_context(self, data: dict) -> ProtocolContext:
        """Convert dict to ProtocolContext."""
        health_data = data.get('health', data)

        health = ProtocolHealth(
            protocol_id=health_data.get('protocol_id', 'unknown'),
            protocol_name=health_data.get('protocol_name', 'Unknown'),
            overall_score=health_data.get('health', {}).get('overall_score', 0),
            health_tier=health_data.get('health', {}).get('tier', 'F'),
            treasury_usd=health_data.get('financial', {}).get('treasury_usd', 0),
            runway_months=health_data.get('financial', {}).get('runway_months', 0),
            burn_rate_monthly=health_data.get('financial', {}).get('burn_rate_monthly', 0),
            active_proposals=health_data.get('governance', {}).get('active_proposals', 0),
            governance_participation=health_data.get('governance', {}).get('participation_rate', 0),
            recent_votes=health_data.get('governance', {}).get('recent_votes', 0),
            risk_flags=health_data.get('risk', {}).get('flags', []),
            risk_level=health_data.get('risk', {}).get('level', 'unknown'),
            fetched_at=health_data.get('metadata', {}).get('fetched_at', datetime.now().isoformat()),
            data_staleness_hours=health_data.get('metadata', {}).get('staleness_hours', 0),
        )

        events = []
        for event_data in data.get('recent_events', []):
            events.append(GovernanceEvent(
                event_type=event_data.get('type', 'unknown'),
                event_id=event_data.get('id', ''),
                title=event_data.get('title', ''),
                timestamp=event_data.get('timestamp', ''),
                impact_level=event_data.get('impact', 'low'),
                vote_outcome=event_data.get('vote_outcome'),
                treasury_impact_usd=event_data.get('treasury_impact_usd'),
            ))

        return ProtocolContext(
            health=health,
            recent_events=events,
            analysis_start=data.get('analysis_window', {}).get('start', ''),
            analysis_end=data.get('analysis_window', {}).get('end', ''),
            warnings=data.get('warnings', []),
        )

    def _score_to_tier(self, score: float) -> str:
        """Convert numeric score to letter tier."""
        if score >= 80:
            return 'A'
        elif score >= 60:
            return 'B'
        elif score >= 40:
            return 'C'
        elif score >= 20:
            return 'D'
        return 'F'
