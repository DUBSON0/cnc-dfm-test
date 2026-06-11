"""Data model for analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SurfaceKind(str, Enum):
    PLANE = "plane"
    CYLINDER = "cylinder"
    CONE = "cone"
    SPHERE = "sphere"
    TORUS = "torus"
    FREEFORM = "freeform"
    OTHER = "other"


@dataclass
class FaceInfo:
    """Classified geometry for a single B-rep face."""

    index: int
    kind: SurfaceKind
    area: float
    # For cylinders/cones: axis info and radius.
    axis_origin: tuple[float, float, float] | None = None
    axis_dir: tuple[float, float, float] | None = None
    radius: float | None = None
    # Concave = material curves around the face (internal corner / hole wall).
    concave: bool | None = None
    # Angular extent of revolution surfaces, radians.
    sweep_angle: float | None = None
    # Outward normal for planar faces.
    normal: tuple[float, float, float] | None = None
    centroid: tuple[float, float, float] | None = None


@dataclass
class Finding:
    """One DFM issue tied to a set of faces."""

    rule: str
    title: str
    severity: Severity
    detail: str
    suggestion: str
    # Short imperative version of the fix, e.g. "Enlarge corner radii to ≥ 8 mm".
    action: str = ""
    face_indices: list[int] = field(default_factory=list)
    penalty: float = 0.0  # contribution to score reduction, pre-saturation
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "title": self.title,
            "severity": self.severity.value,
            "detail": self.detail,
            "suggestion": self.suggestion,
            "action": self.action,
            "face_indices": self.face_indices,
            "data": self.data,
        }


@dataclass
class AnalysisResult:
    score: float
    subscores: dict[str, float]
    findings: list[Finding]
    part_stats: dict[str, Any]
    setup_info: dict[str, Any]
    # Ranked design changes: most score impact first (see scoring.rank_design_changes).
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "subscores": {k: round(v, 1) for k, v in self.subscores.items()},
            "findings": [f.to_dict() for f in self.findings],
            "part_stats": self.part_stats,
            "setup_info": self.setup_info,
            "recommendations": self.recommendations,
        }
