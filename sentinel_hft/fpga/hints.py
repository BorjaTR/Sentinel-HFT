"""
FPGA implementation hints and optimization strategies.

Provides vendor-specific guidance for implementing HFT designs
on different FPGA families.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class FPGAFamily(Enum):
    """Supported FPGA families."""
    # Xilinx
    XILINX_ULTRASCALE_PLUS = "xilinx_ultrascale_plus"
    XILINX_ULTRASCALE = "xilinx_ultrascale"
    XILINX_VERSAL = "xilinx_versal"

    # Intel (formerly Altera)
    INTEL_AGILEX = "intel_agilex"
    INTEL_STRATIX10 = "intel_stratix10"
    INTEL_ARRIA10 = "intel_arria10"

    # Lattice
    LATTICE_NEXUS = "lattice_nexus"

    # Generic
    GENERIC = "generic"


@dataclass
class TimingConstraint:
    """A timing constraint for FPGA implementation."""
    name: str
    constraint_type: str  # "period", "max_delay", "false_path", "multicycle"
    value: str  # TCL constraint string
    description: str
    applies_to: List[str] = field(default_factory=list)  # Signal patterns


@dataclass
class ResourceEstimate:
    """Resource utilization estimate for an FPGA family."""
    family: FPGAFamily
    luts: int
    ffs: int
    bram_18k: int = 0
    bram_36k: int = 0
    uram: int = 0
    dsp: int = 0
    io_pins: int = 0
    max_freq_mhz: int = 400
    power_watts: float = 0.0
    notes: str = ""


@dataclass
class ImplementationStrategy:
    """Implementation strategy for a specific pattern/FPGA combo."""
    pattern_id: str
    family: FPGAFamily
    strategy_name: str
    description: str

    # Tool-specific settings
    synthesis_options: Dict[str, str] = field(default_factory=dict)
    place_options: Dict[str, str] = field(default_factory=dict)
    route_options: Dict[str, str] = field(default_factory=dict)

    # Constraints
    timing_constraints: List[TimingConstraint] = field(default_factory=list)
    physical_constraints: List[str] = field(default_factory=list)

    # Code modifications
    attribute_hints: Dict[str, str] = field(default_factory=dict)


class FPGAHints:
    """
    FPGA implementation hints generator.

    Provides vendor-specific optimization guidance based on
    detected patterns and target FPGA family.
    """

    # Vendor-specific attribute names
    VENDOR_ATTRS = {
        FPGAFamily.XILINX_ULTRASCALE_PLUS: {
            'keep': 'KEEP',
            'dont_touch': 'DONT_TOUCH',
            'async_reg': 'ASYNC_REG',
            'iob': 'IOB',
            'shreg_extract': 'SHREG_EXTRACT',
            'ram_style': 'ram_style',
            'rom_style': 'rom_style',
            'use_dsp': 'use_dsp',
            'max_fanout': 'MAX_FANOUT',
        },
        FPGAFamily.INTEL_AGILEX: {
            'keep': 'preserve',
            'dont_touch': 'noprune',
            'async_reg': 'SYNCHRONIZER_IDENTIFICATION',
            'ram_style': 'ramstyle',
            'rom_style': 'romstyle',
            'use_dsp': 'multstyle',
            'max_fanout': 'maxfan',
        },
    }

    # Pattern-specific strategies
    PATTERN_STRATEGIES = {
        'FIFO_BACKPRESSURE': {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: ImplementationStrategy(
                pattern_id='FIFO_BACKPRESSURE',
                family=FPGAFamily.XILINX_ULTRASCALE_PLUS,
                strategy_name='distributed_ram_fifo',
                description='Use distributed RAM for shallow FIFOs, BRAM for deep',
                synthesis_options={
                    '-flatten_hierarchy': 'rebuilt',
                    '-directive': 'AreaOptimized_high',
                },
                attribute_hints={
                    'ram_style': '(* ram_style = "distributed" *) // For DEPTH <= 64',
                    'shreg_extract': '(* SHREG_EXTRACT = "no" *) // Disable SRL inference',
                },
                timing_constraints=[
                    TimingConstraint(
                        name='fifo_credit_path',
                        constraint_type='max_delay',
                        value='set_max_delay -datapath_only 2.0 -from [get_cells *credit*]',
                        description='Relax credit feedback path',
                    ),
                ],
            ),
            FPGAFamily.INTEL_AGILEX: ImplementationStrategy(
                pattern_id='FIFO_BACKPRESSURE',
                family=FPGAFamily.INTEL_AGILEX,
                strategy_name='mlab_fifo',
                description='Use MLAB for shallow FIFOs, M20K for deep',
                synthesis_options={
                    'OPTIMIZATION_MODE': 'HIGH PERFORMANCE EFFORT',
                },
                attribute_hints={
                    'ramstyle': '(* ramstyle = "MLAB" *) // For DEPTH <= 32',
                },
            ),
        },
        'CLOCK_DOMAIN_CROSSING': {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: ImplementationStrategy(
                pattern_id='CLOCK_DOMAIN_CROSSING',
                family=FPGAFamily.XILINX_ULTRASCALE_PLUS,
                strategy_name='async_fifo_ultrascale',
                description='Gray-code CDC with ASYNC_REG',
                attribute_hints={
                    'async_reg': '(* ASYNC_REG = "TRUE" *)',
                    'dont_touch': '(* DONT_TOUCH = "yes" *) // Prevent optimization across sync boundary',
                },
                timing_constraints=[
                    TimingConstraint(
                        name='cdc_false_path',
                        constraint_type='false_path',
                        value='set_false_path -from [get_clocks wr_clk] -to [get_cells *_meta_reg[0]*]',
                        description='False path to first sync stage',
                    ),
                    TimingConstraint(
                        name='cdc_max_delay',
                        constraint_type='max_delay',
                        value='set_max_delay -datapath_only 2.0 -from [get_clocks wr_clk] -to [get_clocks rd_clk]',
                        description='Limit CDC path delay',
                    ),
                ],
            ),
        },
        'ARBITER_CONTENTION': {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: ImplementationStrategy(
                pattern_id='ARBITER_CONTENTION',
                family=FPGAFamily.XILINX_ULTRASCALE_PLUS,
                strategy_name='parallel_arbiter',
                description='Use parallel priority encoder for fast arbitration',
                synthesis_options={
                    '-directive': 'AreaOptimized_high',
                },
                attribute_hints={
                    'max_fanout': '(* MAX_FANOUT = 4 *) // Limit fanout on grant signals',
                },
            ),
        },
        'PIPELINE_BUBBLE': {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: ImplementationStrategy(
                pattern_id='PIPELINE_BUBBLE',
                family=FPGAFamily.XILINX_ULTRASCALE_PLUS,
                strategy_name='retimed_bypass',
                description='Enable retiming for bypass network',
                synthesis_options={
                    '-retiming': 'on',
                },
                place_options={
                    'directive': 'ExtraNetDelay_high',
                },
            ),
        },
        'MEMORY_BANDWIDTH': {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: ImplementationStrategy(
                pattern_id='MEMORY_BANDWIDTH',
                family=FPGAFamily.XILINX_ULTRASCALE_PLUS,
                strategy_name='uram_prefetch',
                description='Use URAM for prefetch buffer if available',
                attribute_hints={
                    'ram_style': '(* ram_style = "ultra" *) // Use URAM for large buffers',
                },
                timing_constraints=[
                    TimingConstraint(
                        name='axi_interface',
                        constraint_type='max_delay',
                        value='set_max_delay 3.0 -through [get_nets *axi*]',
                        description='AXI interface timing',
                    ),
                ],
            ),
        },
    }

    def __init__(self, family: FPGAFamily = FPGAFamily.XILINX_ULTRASCALE_PLUS):
        """
        Initialize hints generator.

        Args:
            family: Target FPGA family
        """
        self.family = family

    def get_strategy(self, pattern_id: str) -> Optional[ImplementationStrategy]:
        """Get implementation strategy for a pattern."""
        pattern_strategies = self.PATTERN_STRATEGIES.get(pattern_id, {})
        return pattern_strategies.get(self.family)

    def get_attribute(self, attr_name: str) -> str:
        """Get vendor-specific attribute syntax."""
        family_attrs = self.VENDOR_ATTRS.get(self.family, {})
        return family_attrs.get(attr_name, attr_name)

    def generate_constraints_tcl(self, pattern_id: str) -> str:
        """
        Generate TCL constraints for a pattern.

        Args:
            pattern_id: Pattern to generate constraints for

        Returns:
            TCL constraint file content
        """
        strategy = self.get_strategy(pattern_id)
        if not strategy:
            return f"# No specific constraints for {pattern_id} on {self.family.value}\n"

        lines = [
            f"# Timing constraints for {pattern_id}",
            f"# Target: {self.family.value}",
            f"# Strategy: {strategy.strategy_name}",
            "#",
            f"# {strategy.description}",
            "#" + "=" * 60,
            "",
        ]

        for tc in strategy.timing_constraints:
            lines.append(f"# {tc.description}")
            lines.append(tc.value)
            lines.append("")

        if strategy.physical_constraints:
            lines.append("# Physical constraints")
            for pc in strategy.physical_constraints:
                lines.append(pc)
            lines.append("")

        return "\n".join(lines)

    def generate_synthesis_script(self, pattern_id: str) -> str:
        """
        Generate synthesis script snippet.

        Args:
            pattern_id: Pattern to generate script for

        Returns:
            Tool-specific synthesis commands
        """
        strategy = self.get_strategy(pattern_id)
        if not strategy:
            return ""

        if self.family in [FPGAFamily.XILINX_ULTRASCALE_PLUS,
                           FPGAFamily.XILINX_ULTRASCALE,
                           FPGAFamily.XILINX_VERSAL]:
            return self._generate_vivado_script(strategy)
        elif self.family in [FPGAFamily.INTEL_AGILEX,
                             FPGAFamily.INTEL_STRATIX10]:
            return self._generate_quartus_script(strategy)

        return ""

    def _generate_vivado_script(self, strategy: ImplementationStrategy) -> str:
        """Generate Vivado TCL snippet."""
        lines = [
            f"# Vivado settings for {strategy.pattern_id}",
            f"# Strategy: {strategy.strategy_name}",
            "",
        ]

        if strategy.synthesis_options:
            lines.append("# Synthesis settings")
            for opt, val in strategy.synthesis_options.items():
                lines.append(f"set_property {opt} {val} [current_run]")
            lines.append("")

        if strategy.place_options:
            lines.append("# Place settings")
            for opt, val in strategy.place_options.items():
                lines.append(f"set_property STEPS.PLACE_DESIGN.ARGS.{opt.upper()} {val} [get_runs impl_1]")
            lines.append("")

        return "\n".join(lines)

    def _generate_quartus_script(self, strategy: ImplementationStrategy) -> str:
        """Generate Quartus TCL snippet."""
        lines = [
            f"# Quartus settings for {strategy.pattern_id}",
            f"# Strategy: {strategy.strategy_name}",
            "",
        ]

        if strategy.synthesis_options:
            lines.append("# Synthesis settings")
            for opt, val in strategy.synthesis_options.items():
                lines.append(f"set_global_assignment -name {opt} \"{val}\"")
            lines.append("")

        return "\n".join(lines)

    def get_code_annotations(self, pattern_id: str) -> Dict[str, str]:
        """
        Get code annotations/attributes for a pattern.

        Args:
            pattern_id: Pattern to get annotations for

        Returns:
            Dict of annotation purpose -> annotation code
        """
        strategy = self.get_strategy(pattern_id)
        if not strategy:
            return {}

        return strategy.attribute_hints

    def estimate_resources(
        self,
        pattern_id: str,
        params: Dict[str, Any] = None
    ) -> ResourceEstimate:
        """
        Estimate resource usage for a pattern.

        Args:
            pattern_id: Pattern to estimate
            params: Pattern parameters (e.g., DEPTH, WIDTH)

        Returns:
            Resource estimate for target family
        """
        params = params or {}

        # Base estimates by pattern
        base_estimates = {
            'FIFO_BACKPRESSURE': {
                'luts': 50 + params.get('BUFFER_DEPTH', 16) * 2,
                'ffs': 30 + params.get('BUFFER_DEPTH', 16) * 2,
                'bram_18k': 1 if params.get('BUFFER_DEPTH', 16) > 64 else 0,
            },
            'ARBITER_CONTENTION': {
                'luts': 100 + params.get('NUM_PORTS', 4) * 30,
                'ffs': 50 + params.get('NUM_PORTS', 4) * 20,
            },
            'PIPELINE_BUBBLE': {
                'luts': 200 + params.get('NUM_STAGES', 4) * 50,
                'ffs': 100 + params.get('NUM_STAGES', 4) * 30,
            },
            'MEMORY_BANDWIDTH': {
                'luts': 500 + params.get('PREFETCH_DEPTH', 8) * 30,
                'ffs': 300 + params.get('PREFETCH_DEPTH', 8) * 50,
                'bram_18k': max(1, params.get('PREFETCH_DEPTH', 8) // 4),
            },
            'CLOCK_DOMAIN_CROSSING': {
                'luts': 80 + params.get('DEPTH', 16) * 3,
                'ffs': 100 + params.get('DEPTH', 16) * 4 + params.get('SYNC_STAGES', 2) * 20,
                'bram_18k': 1 if params.get('DEPTH', 16) > 32 else 0,
            },
        }

        base = base_estimates.get(pattern_id, {'luts': 100, 'ffs': 100})

        # Adjust for family
        family_factor = {
            FPGAFamily.XILINX_ULTRASCALE_PLUS: 1.0,
            FPGAFamily.INTEL_AGILEX: 1.1,  # Slightly different LUT structure
            FPGAFamily.XILINX_VERSAL: 0.9,  # More efficient
        }.get(self.family, 1.0)

        return ResourceEstimate(
            family=self.family,
            luts=int(base.get('luts', 100) * family_factor),
            ffs=int(base.get('ffs', 100) * family_factor),
            bram_18k=base.get('bram_18k', 0),
            bram_36k=base.get('bram_36k', 0),
            uram=base.get('uram', 0),
            dsp=base.get('dsp', 0),
        )

    def get_critical_paths(self, pattern_id: str) -> List[str]:
        """
        Get likely critical paths for a pattern.

        Args:
            pattern_id: Pattern to analyze

        Returns:
            List of critical path descriptions
        """
        critical_paths = {
            'FIFO_BACKPRESSURE': [
                "wr_ptr -> count -> up_credit (credit feedback)",
                "rd_ptr -> dn_valid (empty detection)",
                "up_data -> buffer -> dn_data (data path)",
            ],
            'ARBITER_CONTENTION': [
                "req -> priority_encoder -> grant (arbitration logic)",
                "weight_counters -> eligible -> winner (eligibility check)",
            ],
            'PIPELINE_BUBBLE': [
                "src_addr -> stage_dst_addr comparison (hazard detection)",
                "stage_result -> fwd_data mux (forwarding path)",
            ],
            'MEMORY_BANDWIDTH': [
                "demand_addr -> buffer address match (hit detection)",
                "stride calculation -> prefetch_addr (address generation)",
            ],
            'CLOCK_DOMAIN_CROSSING': [
                "wr_ptr_gray -> sync_stages -> rd_ptr_gray_sync (pointer sync)",
                "Gray code comparison for full/empty flags",
            ],
        }

        return critical_paths.get(pattern_id, ["No specific critical paths identified"])

    def format_report(self, pattern_id: str, params: Dict[str, Any] = None) -> str:
        """
        Generate a formatted implementation hints report.

        Args:
            pattern_id: Pattern to report on
            params: Pattern parameters

        Returns:
            Formatted report string
        """
        lines = [
            f"FPGA Implementation Hints: {pattern_id}",
            f"Target: {self.family.value}",
            "=" * 60,
            "",
        ]

        strategy = self.get_strategy(pattern_id)
        if strategy:
            lines.append(f"Strategy: {strategy.strategy_name}")
            lines.append(f"Description: {strategy.description}")
            lines.append("")

        # Resource estimate
        estimate = self.estimate_resources(pattern_id, params)
        lines.append("Resource Estimate:")
        lines.append(f"  LUTs: ~{estimate.luts}")
        lines.append(f"  FFs: ~{estimate.ffs}")
        if estimate.bram_18k:
            lines.append(f"  BRAM 18K: {estimate.bram_18k}")
        lines.append("")

        # Critical paths
        lines.append("Critical Paths to Monitor:")
        for path in self.get_critical_paths(pattern_id):
            lines.append(f"  - {path}")
        lines.append("")

        # Code annotations
        annotations = self.get_code_annotations(pattern_id)
        if annotations:
            lines.append("Recommended Attributes:")
            for purpose, code in annotations.items():
                lines.append(f"  {purpose}:")
                lines.append(f"    {code}")
            lines.append("")

        # Constraints
        if strategy and strategy.timing_constraints:
            lines.append("Timing Constraints:")
            for tc in strategy.timing_constraints:
                lines.append(f"  {tc.description}:")
                lines.append(f"    {tc.value}")
            lines.append("")

        return "\n".join(lines)
