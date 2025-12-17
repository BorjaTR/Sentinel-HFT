"""
Protocol analyzer with HFT-specific latency budgets.

Provides:
- Protocol detection and decoding
- Expected latency budgets per message type
- Protocol-aware latency attribution
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
import struct


class ProtocolType(Enum):
    """Supported HFT protocols."""
    FIX = "fix"
    ITCH = "itch"
    OUCH = "ouch"
    SBE = "sbe"
    CUSTOM_BINARY = "custom_binary"
    UNKNOWN = "unknown"


@dataclass
class LatencyBudget:
    """
    Expected latency budget for a message type.

    In HFT, different message types have different latency requirements.
    Market data should be faster than administrative messages.
    """
    message_type: str
    expected_ns: int  # Target latency
    warning_ns: int   # Warning threshold
    critical_ns: int  # Critical threshold
    description: str = ""

    def evaluate(self, actual_ns: int) -> str:
        """Evaluate actual latency against budget."""
        if actual_ns <= self.expected_ns:
            return "good"
        elif actual_ns <= self.warning_ns:
            return "warning"
        elif actual_ns <= self.critical_ns:
            return "critical"
        else:
            return "violation"


@dataclass
class ProtocolConfig:
    """Configuration for protocol analysis."""
    protocol_type: ProtocolType
    clock_mhz: float = 100.0

    # Custom latency budgets (override defaults)
    custom_budgets: Dict[str, LatencyBudget] = field(default_factory=dict)

    # Message filtering
    include_message_types: Optional[List[str]] = None
    exclude_message_types: Optional[List[str]] = None

    # Protocol-specific options
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProtocolMetrics:
    """Metrics for a specific protocol/message type."""
    protocol: ProtocolType
    message_type: str
    count: int = 0
    total_latency_ns: int = 0
    min_latency_ns: int = 0
    max_latency_ns: int = 0
    budget_violations: int = 0
    warnings: int = 0

    @property
    def avg_latency_ns(self) -> float:
        return self.total_latency_ns / self.count if self.count > 0 else 0


class ProtocolAnalyzer:
    """
    Analyze latency traces with protocol awareness.

    Usage:
        analyzer = ProtocolAnalyzer(ProtocolConfig(
            protocol_type=ProtocolType.ITCH,
            clock_mhz=156.25
        ))

        for event in trace:
            analyzer.process_event(event)

        report = analyzer.get_report()
    """

    # Default latency budgets by protocol and message type (nanoseconds)
    DEFAULT_BUDGETS = {
        ProtocolType.ITCH: {
            'A': LatencyBudget('A', 200, 400, 800, "Add Order"),
            'F': LatencyBudget('F', 200, 400, 800, "Add Order (MPID)"),
            'E': LatencyBudget('E', 150, 300, 600, "Order Executed"),
            'C': LatencyBudget('C', 150, 300, 600, "Order Executed (Price)"),
            'X': LatencyBudget('X', 200, 400, 800, "Order Cancel"),
            'D': LatencyBudget('D', 200, 400, 800, "Order Delete"),
            'U': LatencyBudget('U', 250, 500, 1000, "Order Replace"),
            'P': LatencyBudget('P', 100, 200, 400, "Trade (Non-Cross)"),
            'Q': LatencyBudget('Q', 100, 200, 400, "Cross Trade"),
            'B': LatencyBudget('B', 100, 200, 400, "Broken Trade"),
            'I': LatencyBudget('I', 500, 1000, 2000, "NOII"),
            'S': LatencyBudget('S', 1000, 2000, 5000, "System Event"),
            'R': LatencyBudget('R', 1000, 2000, 5000, "Stock Directory"),
            'H': LatencyBudget('H', 500, 1000, 2000, "Stock Trading Action"),
            'Y': LatencyBudget('Y', 500, 1000, 2000, "Reg SHO"),
            'L': LatencyBudget('L', 500, 1000, 2000, "Market Participant Position"),
        },
        ProtocolType.OUCH: {
            'O': LatencyBudget('O', 500, 1000, 2000, "Enter Order"),
            'U': LatencyBudget('U', 500, 1000, 2000, "Replace Order"),
            'X': LatencyBudget('X', 300, 600, 1200, "Cancel Order"),
            'A': LatencyBudget('A', 200, 400, 800, "Accepted"),
            'E': LatencyBudget('E', 150, 300, 600, "Executed"),
            'C': LatencyBudget('C', 200, 400, 800, "Canceled"),
            'J': LatencyBudget('J', 300, 600, 1200, "Rejected"),
        },
        ProtocolType.FIX: {
            '0': LatencyBudget('0', 10000, 50000, 100000, "Heartbeat"),
            '1': LatencyBudget('1', 5000, 10000, 50000, "Test Request"),
            'A': LatencyBudget('A', 50000, 100000, 500000, "Logon"),
            '5': LatencyBudget('5', 50000, 100000, 500000, "Logout"),
            'D': LatencyBudget('D', 1000, 2000, 5000, "New Order Single"),
            'F': LatencyBudget('F', 800, 1500, 3000, "Order Cancel Request"),
            'G': LatencyBudget('G', 1000, 2000, 5000, "Order Replace Request"),
            '8': LatencyBudget('8', 500, 1000, 2000, "Execution Report"),
            '9': LatencyBudget('9', 500, 1000, 2000, "Order Cancel Reject"),
            'W': LatencyBudget('W', 300, 600, 1200, "Market Data Snapshot"),
            'X': LatencyBudget('X', 200, 400, 800, "Market Data Incremental"),
        },
        ProtocolType.SBE: {
            # SBE template IDs (numeric)
            '1': LatencyBudget('1', 200, 400, 800, "Market Data"),
            '2': LatencyBudget('2', 300, 600, 1200, "Order Entry"),
            '3': LatencyBudget('3', 200, 400, 800, "Execution"),
        },
    }

    def __init__(self, config: ProtocolConfig):
        """
        Initialize protocol analyzer.

        Args:
            config: Protocol configuration
        """
        self.config = config
        self.metrics: Dict[str, ProtocolMetrics] = {}

        # Build budget lookup
        self.budgets = dict(self.DEFAULT_BUDGETS.get(config.protocol_type, {}))
        self.budgets.update(config.custom_budgets)

    def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a trace event with protocol awareness.

        Args:
            event: Trace event with 'data', 'latency_ns', etc.

        Returns:
            Enriched event with protocol info, or None if filtered
        """
        # Extract message type
        msg_type = self._extract_message_type(event)
        if msg_type is None:
            msg_type = 'UNKNOWN'

        # Apply filters
        if self.config.include_message_types:
            if msg_type not in self.config.include_message_types:
                return None

        if self.config.exclude_message_types:
            if msg_type in self.config.exclude_message_types:
                return None

        # Get latency
        latency_ns = event.get('latency_ns', 0)
        if 'latency_cycles' in event and latency_ns == 0:
            latency_ns = int(event['latency_cycles'] * 1000 / self.config.clock_mhz)

        # Update metrics
        if msg_type not in self.metrics:
            self.metrics[msg_type] = ProtocolMetrics(
                protocol=self.config.protocol_type,
                message_type=msg_type,
                min_latency_ns=latency_ns,
                max_latency_ns=latency_ns,
            )

        m = self.metrics[msg_type]
        m.count += 1
        m.total_latency_ns += latency_ns
        m.min_latency_ns = min(m.min_latency_ns, latency_ns)
        m.max_latency_ns = max(m.max_latency_ns, latency_ns)

        # Check against budget
        budget = self.budgets.get(msg_type)
        budget_status = None
        if budget:
            budget_status = budget.evaluate(latency_ns)
            if budget_status == 'violation':
                m.budget_violations += 1
            elif budget_status == 'warning':
                m.warnings += 1

        # Return enriched event
        return {
            **event,
            'protocol': self.config.protocol_type.value,
            'message_type': msg_type,
            'message_description': budget.description if budget else None,
            'latency_ns': latency_ns,
            'budget_status': budget_status,
            'budget_expected_ns': budget.expected_ns if budget else None,
        }

    def _extract_message_type(self, event: Dict[str, Any]) -> Optional[str]:
        """Extract message type from event based on protocol."""
        # Check for explicit message type
        if 'message_type' in event:
            return str(event['message_type'])

        # Extract from data based on protocol
        data = event.get('data')
        if data is None:
            return None

        if isinstance(data, bytes):
            return self._extract_from_bytes(data)
        elif isinstance(data, str):
            return self._extract_from_string(data)
        elif isinstance(data, dict):
            return data.get('msg_type') or data.get('type')

        return None

    def _extract_from_bytes(self, data: bytes) -> Optional[str]:
        """Extract message type from binary data."""
        if len(data) < 1:
            return None

        protocol = self.config.protocol_type

        if protocol == ProtocolType.ITCH:
            # ITCH: message type is first byte after length
            if len(data) >= 3:
                return chr(data[2])

        elif protocol == ProtocolType.OUCH:
            # OUCH: message type is first byte
            return chr(data[0])

        elif protocol == ProtocolType.SBE:
            # SBE: template ID in header (bytes 4-5 typically)
            if len(data) >= 6:
                template_id = struct.unpack('<H', data[4:6])[0]
                return str(template_id)

        # Default: first byte as char
        return chr(data[0]) if data[0] < 128 else str(data[0])

    def _extract_from_string(self, data: str) -> Optional[str]:
        """Extract message type from string data (FIX)."""
        protocol = self.config.protocol_type

        if protocol == ProtocolType.FIX:
            # FIX: look for 35= tag
            if '35=' in data:
                idx = data.index('35=') + 3
                end = data.find('\x01', idx)
                if end == -1:
                    end = data.find('|', idx)
                if end == -1:
                    end = len(data)
                return data[idx:end]

        return data[0] if data else None

    def get_report(self) -> Dict[str, Any]:
        """
        Get protocol analysis report.

        Returns:
            Report with metrics per message type and overall summary
        """
        by_message_type = {}
        total_count = 0
        total_violations = 0
        total_warnings = 0

        for msg_type, metrics in sorted(self.metrics.items()):
            budget = self.budgets.get(msg_type)
            by_message_type[msg_type] = {
                'description': budget.description if budget else None,
                'count': metrics.count,
                'avg_latency_ns': round(metrics.avg_latency_ns, 1),
                'min_latency_ns': metrics.min_latency_ns,
                'max_latency_ns': metrics.max_latency_ns,
                'budget_expected_ns': budget.expected_ns if budget else None,
                'budget_violations': metrics.budget_violations,
                'warnings': metrics.warnings,
                'violation_rate': (
                    round(metrics.budget_violations / metrics.count * 100, 2)
                    if metrics.count > 0 else 0
                ),
            }
            total_count += metrics.count
            total_violations += metrics.budget_violations
            total_warnings += metrics.warnings

        return {
            'protocol': self.config.protocol_type.value,
            'total_messages': total_count,
            'total_violations': total_violations,
            'total_warnings': total_warnings,
            'violation_rate': (
                round(total_violations / total_count * 100, 2)
                if total_count > 0 else 0
            ),
            'by_message_type': by_message_type,
        }

    def get_critical_messages(self) -> List[str]:
        """Get message types with high violation rates."""
        critical = []
        for msg_type, metrics in self.metrics.items():
            if metrics.count > 0:
                violation_rate = metrics.budget_violations / metrics.count
                if violation_rate > 0.05:  # > 5% violations
                    critical.append(msg_type)
        return critical

    def suggest_focus_areas(self) -> List[Dict[str, Any]]:
        """Suggest areas to focus optimization efforts."""
        suggestions = []

        for msg_type, metrics in self.metrics.items():
            budget = self.budgets.get(msg_type)
            if not budget or metrics.count < 10:
                continue

            # High volume + violations = high impact
            if metrics.budget_violations > 0:
                impact_score = (
                    metrics.count * metrics.budget_violations /
                    (metrics.count ** 0.5)
                )
                suggestions.append({
                    'message_type': msg_type,
                    'description': budget.description,
                    'reason': 'Budget violations',
                    'violation_count': metrics.budget_violations,
                    'violation_rate': round(
                        metrics.budget_violations / metrics.count * 100, 1
                    ),
                    'avg_latency_ns': round(metrics.avg_latency_ns, 0),
                    'budget_ns': budget.expected_ns,
                    'impact_score': round(impact_score, 1),
                })

        # Sort by impact score
        suggestions.sort(key=lambda x: x['impact_score'], reverse=True)
        return suggestions[:5]  # Top 5
