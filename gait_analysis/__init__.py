"""Causal gait-cycle analysis for rr_app walk recordings."""

from .segmenter import Cycle, SegmentationConfig, segment_rows

__all__ = ["Cycle", "SegmentationConfig", "segment_rows"]
