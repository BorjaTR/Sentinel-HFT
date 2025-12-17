"""
FixPack Generator Engine.

Generates RTL, testbenches, and integration guides from templates
based on detected patterns and user parameters.
"""

import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import TemplateMetadata, TemplateParameter


@dataclass
class GeneratedFixPack:
    """Result of FixPack generation."""
    pattern_id: str
    template_id: str

    # Generated file paths
    rtl_file: str
    testbench_file: str
    integration_guide_file: str

    # Metadata
    parameters: Dict[str, Any]
    metadata: Dict[str, Any]

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"FixPack Generated: {self.template_id}",
            f"  Pattern: {self.pattern_id}",
            f"  RTL: {self.rtl_file}",
            f"  Testbench: {self.testbench_file}",
            f"  Guide: {self.integration_guide_file}",
        ]
        if self.warnings:
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)


class FixPackGenerator:
    """
    Generate FixPacks from templates.

    Usage:
        generator = FixPackGenerator()
        result = generator.generate(
            pattern_id="FIFO_BACKPRESSURE",
            output_dir="./fixpack_output",
            params={"BUFFER_DEPTH": 32, "DATA_WIDTH": 128}
        )
    """

    # Pattern ID to template directory mapping
    PATTERN_TEMPLATES = {
        "FIFO_BACKPRESSURE": "fifo_backpressure",
        "ARBITER_CONTENTION": "arbiter_contention",
        "PIPELINE_BUBBLE": "pipeline_bubble",
        "MEMORY_BANDWIDTH": "memory_bandwidth",
        "CLOCK_DOMAIN_CROSSING": "clock_domain_crossing",
    }

    def __init__(self, templates_dir: Path = None):
        """
        Initialize generator.

        Args:
            templates_dir: Path to templates directory.
                          Defaults to this module's directory.
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent
        self.templates_dir = templates_dir

        # Set up Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def get_available_patterns(self) -> List[str]:
        """Get list of patterns with templates."""
        return list(self.PATTERN_TEMPLATES.keys())

    def get_template_metadata(self, pattern_id: str) -> Optional[TemplateMetadata]:
        """Load metadata for a pattern's template."""
        if pattern_id not in self.PATTERN_TEMPLATES:
            return None

        template_dir = self.PATTERN_TEMPLATES[pattern_id]
        metadata_path = self.templates_dir / template_dir / "metadata.yaml"

        if not metadata_path.exists():
            return None

        return TemplateMetadata.from_yaml(str(metadata_path))

    def get_default_params(self, pattern_id: str) -> Dict[str, Any]:
        """Get default parameters for a pattern."""
        metadata = self.get_template_metadata(pattern_id)
        if not metadata:
            return {}

        return {p.name: p.default for p in metadata.parameters}

    def validate_params(self, pattern_id: str, params: Dict[str, Any]) -> List[str]:
        """
        Validate parameters against template constraints.

        Returns list of validation errors (empty if valid).
        """
        metadata = self.get_template_metadata(pattern_id)
        if not metadata:
            return [f"Unknown pattern: {pattern_id}"]

        errors = []
        for param in metadata.parameters:
            if param.name in params:
                value = params[param.name]
                if not param.validate(value):
                    errors.append(
                        f"Parameter {param.name}={value} out of range "
                        f"[{param.min_value}, {param.max_value}]"
                    )

        return errors

    def generate(
        self,
        pattern_id: str,
        output_dir: str,
        params: Dict[str, Any] = None,
        prefix: str = "",
    ) -> GeneratedFixPack:
        """
        Generate a FixPack for a pattern.

        Args:
            pattern_id: Pattern identifier (e.g., "FIFO_BACKPRESSURE")
            output_dir: Directory to write generated files
            params: Template parameters (uses defaults if not specified)
            prefix: Optional prefix for output filenames

        Returns:
            GeneratedFixPack with paths to generated files

        Raises:
            ValueError: If pattern_id is unknown
            FileNotFoundError: If template files are missing
        """
        if pattern_id not in self.PATTERN_TEMPLATES:
            raise ValueError(f"Unknown pattern: {pattern_id}")

        template_dir_name = self.PATTERN_TEMPLATES[pattern_id]
        template_dir = self.templates_dir / template_dir_name

        # Load metadata
        metadata_path = template_dir / "metadata.yaml"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Metadata not found: {metadata_path}")

        with open(metadata_path) as f:
            metadata_dict = yaml.safe_load(f)

        metadata = TemplateMetadata.from_dict(metadata_dict)

        # Merge defaults with provided params
        final_params = self.get_default_params(pattern_id)
        if params:
            final_params.update(params)

        # Validate
        warnings = []
        errors = self.validate_params(pattern_id, final_params)
        if errors:
            warnings.extend(errors)

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Build template context
        context = {
            'params': final_params,
            'metadata': {
                'id': metadata.id,
                'name': metadata.name,
                'version': metadata.version,
                'pattern_id': metadata.pattern_id,
                'description': metadata.description,
                'problem_statement': metadata.problem_statement,
                'solution_approach': metadata.solution_approach,
                'expected_latency_reduction_pct': metadata.expected_latency_reduction_pct,
                'expected_throughput_improvement_pct': metadata.expected_throughput_improvement_pct,
                'confidence_range': metadata.confidence_range,
                'prerequisites': metadata.prerequisites,
                'breaking_changes': metadata.breaking_changes,
                'known_limitations': metadata.known_limitations,
                'min_test_vectors': metadata.min_test_vectors,
                'recommended_test_duration_ms': metadata.recommended_test_duration_ms,
                'generation_timestamp': datetime.utcnow().isoformat() + "Z",
                'fpga_resources': [
                    {
                        'vendor': r.vendor,
                        'family': r.family,
                        'luts': r.luts,
                        'ffs': r.ffs,
                        'bram_18k': r.bram_18k,
                        'bram_36k': r.bram_36k,
                        'dsp': r.dsp,
                        'max_freq_mhz': r.max_freq_mhz,
                        'latency_cycles': r.latency_cycles,
                        'notes': r.notes,
                    }
                    for r in metadata.fpga_resources
                ],
            },
        }

        # Generate files
        rtl_template = self.env.get_template(
            f"{template_dir_name}/{metadata.rtl_template}"
        )
        tb_template = self.env.get_template(
            f"{template_dir_name}/{metadata.testbench_template}"
        )
        guide_template = self.env.get_template(
            f"{template_dir_name}/{metadata.integration_guide_template}"
        )

        # Determine output filenames
        base_name = metadata.rtl_template.replace('.sv.j2', '')
        if prefix:
            base_name = f"{prefix}_{base_name}"

        rtl_file = output_path / f"{base_name}.sv"
        tb_file = output_path / f"{base_name}_tb.sv"
        guide_file = output_path / f"{base_name}_integration_guide.md"

        # Render and write
        rtl_file.write_text(rtl_template.render(**context))
        tb_file.write_text(tb_template.render(**context))
        guide_file.write_text(guide_template.render(**context))

        return GeneratedFixPack(
            pattern_id=pattern_id,
            template_id=metadata.id,
            rtl_file=str(rtl_file),
            testbench_file=str(tb_file),
            integration_guide_file=str(guide_file),
            parameters=final_params,
            metadata=context['metadata'],
            warnings=warnings,
        )

    def generate_all_for_analysis(
        self,
        analysis_result: Dict[str, Any],
        output_dir: str,
    ) -> List[GeneratedFixPack]:
        """
        Generate FixPacks for all patterns detected in an analysis.

        Args:
            analysis_result: Output from multi-pattern detector
            output_dir: Directory for output files

        Returns:
            List of generated FixPacks
        """
        results = []

        patterns = analysis_result.get('patterns', [])
        for pattern in patterns:
            pattern_id = pattern.get('pattern_id')
            if pattern_id not in self.PATTERN_TEMPLATES:
                continue

            confidence = pattern.get('confidence', 0)
            if confidence < 0.3:  # Skip low-confidence matches
                continue

            # Extract suggested parameters from analysis
            suggested_params = pattern.get('suggested_params', {})

            try:
                result = self.generate(
                    pattern_id=pattern_id,
                    output_dir=output_dir,
                    params=suggested_params,
                    prefix=f"{pattern_id.lower()}",
                )
                results.append(result)
            except Exception as e:
                # Log but continue with other patterns
                print(f"Warning: Failed to generate FixPack for {pattern_id}: {e}")

        return results


def generate_fixpack_cli(
    pattern_id: str,
    output_dir: str,
    params: Dict[str, Any] = None,
) -> GeneratedFixPack:
    """
    CLI-friendly function to generate a FixPack.

    Args:
        pattern_id: Pattern to generate fix for
        output_dir: Output directory
        params: Optional parameter overrides

    Returns:
        GeneratedFixPack result
    """
    generator = FixPackGenerator()
    return generator.generate(pattern_id, output_dir, params)
