"""Future-training label seam for WP6.1.

This module is intentionally separate from ``wp6_1_audit``.  Coverage code must never import it:
opening labels is not part of the source-observation audit.
"""

from __future__ import annotations

from dataclasses import dataclass

from touchline.modeling.wp6_1_context import V2ShotContext, assert_context_boundary


@dataclass(frozen=True, slots=True)
class V2TrainingExample:
    """A later training consumer may explicitly combine a canonical context and goal label."""

    context: V2ShotContext
    is_goal: int

    def __post_init__(self) -> None:
        if not isinstance(self.context, V2ShotContext):
            raise TypeError("V2TrainingExample context must be a V2ShotContext")
        assert_context_boundary(self.context)
        if self.is_goal not in (0, 1):
            raise ValueError(f"is_goal must be 0 or 1, got {self.is_goal!r}")
