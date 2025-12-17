"""
Schema for FixPack template metadata.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class FPGAVendor(Enum):
    XILINX = "xilinx"
    INTEL = "intel"
    LATTICE = "lattice"
    GENERIC = "generic"


class ResourceType(Enum):
    LUT = "lut"
    FF = "ff"
    BRAM = "bram"
    DSP = "dsp"
    URAM = "uram"


@dataclass
class FPGAResources:
    """Resource usage estimates for a specific FPGA family."""
    vendor: FPGAVendor
    family: str  # e.g., "ultrascale+", "agilex"
    luts: int = 0
    ffs: int = 0
    bram_18k: int = 0
    bram_36k: int = 0
    dsp: int = 0
    uram: int = 0
    max_freq_mhz: int = 400
    latency_cycles: int = 1
    notes: str = ""


@dataclass
class TemplateParameter:
    """A configurable parameter for the template."""
    name: str
    description: str
    type: str  # "int", "bool", "string", "enum"
    default: Any
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    enum_values: Optional[List[str]] = None

    def validate(self, value: Any) -> bool:
        """Validate a parameter value."""
        if self.type == "int":
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False
        elif self.type == "enum":
            if value not in (self.enum_values or []):
                return False
        return True


@dataclass
class TemplateMetadata:
    """Metadata for a FixPack template."""

    # Identification
    id: str
    name: str
    version: str
    pattern_id: str  # Links to detected pattern

    # Description
    description: str
    problem_statement: str
    solution_approach: str

    # Technical details
    parameters: List[TemplateParameter]
    fpga_resources: List[FPGAResources]

    # Expected impact
    expected_latency_reduction_pct: float
    expected_throughput_improvement_pct: float
    confidence_range: tuple  # (min, max) confidence for this fix

    # Files
    rtl_template: str  # filename
    testbench_template: str  # filename
    integration_guide_template: str  # filename

    # Warnings and caveats
    prerequisites: List[str] = field(default_factory=list)
    breaking_changes: List[str] = field(default_factory=list)
    known_limitations: List[str] = field(default_factory=list)

    # Testing
    min_test_vectors: int = 1000
    recommended_test_duration_ms: int = 100

    @classmethod
    def from_yaml(cls, path: str) -> "TemplateMetadata":
        """Load metadata from YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)

        # Parse nested structures
        data['parameters'] = [
            TemplateParameter(**p) for p in data.get('parameters', [])
        ]
        data['fpga_resources'] = [
            FPGAResources(
                vendor=FPGAVendor(r['vendor']),
                **{k: v for k, v in r.items() if k != 'vendor'}
            )
            for r in data.get('fpga_resources', [])
        ]

        # Convert confidence_range from list to tuple
        if 'confidence_range' in data:
            data['confidence_range'] = tuple(data['confidence_range'])

        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateMetadata":
        """Load metadata from dictionary."""
        # Parse nested structures
        data['parameters'] = [
            TemplateParameter(**p) if isinstance(p, dict) else p
            for p in data.get('parameters', [])
        ]
        data['fpga_resources'] = [
            FPGAResources(
                vendor=FPGAVendor(r['vendor']) if isinstance(r.get('vendor'), str) else r.get('vendor'),
                **{k: v for k, v in r.items() if k != 'vendor'}
            ) if isinstance(r, dict) else r
            for r in data.get('fpga_resources', [])
        ]

        # Convert confidence_range from list to tuple
        if 'confidence_range' in data and isinstance(data['confidence_range'], list):
            data['confidence_range'] = tuple(data['confidence_range'])

        return cls(**data)
