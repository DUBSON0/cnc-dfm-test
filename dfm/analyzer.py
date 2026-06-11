"""Top-level analysis pipeline: STEP file in, scored report out."""

from __future__ import annotations

import numpy as np

from dfm.features import (
    RayCaster,
    analyze_accessibility,
    detect_holes_and_corners,
    detect_narrow_gaps,
    detect_sharp_concave_edges,
    detect_thin_regions,
    face_adjacency,
    faces_in_map_order,
)
from dfm.geometry import (
    PartMesh,
    classify_face,
    load_step,
    mesh_shape,
    shape_bbox,
    shape_volume,
)
from dfm.model import AnalysisResult
from dfm.rules import DIR_NAMES, WARN_WALL_METAL, run_all_rules


def analyze_step_file(path: str) -> tuple[AnalysisResult, PartMesh]:
    shape = load_step(path)
    return analyze_shape(shape)


def analyze_shape(shape) -> tuple[AnalysisResult, PartMesh]:
    faces = faces_in_map_order(shape)
    infos = [classify_face(f, i) for i, f in enumerate(faces)]
    adjacency = face_adjacency(shape, faces)

    bb_min, bb_max = shape_bbox(shape)
    size = bb_max - bb_min
    diag = float(np.linalg.norm(size))
    deflection = max(diag / 600.0, 0.05)

    part_mesh = mesh_shape(shape, faces, linear_deflection=deflection)
    caster = RayCaster(part_mesh)

    from dfm.integrity import check_integrity, inspect_integrity
    integrity = inspect_integrity(shape)
    integrity_findings = check_integrity(integrity)

    holes, corners = detect_holes_and_corners(faces, infos, adjacency, caster)
    thin = detect_thin_regions(caster, min_thickness=WARN_WALL_METAL)
    hole_faces = {fi for h in holes for fi in h.face_indices}
    gaps = detect_narrow_gaps(caster, exclude_faces=hole_faces)
    access = analyze_accessibility(caster, infos)
    sharp_edges = detect_sharp_concave_edges(shape, infos, access)

    findings = run_all_rules(
        corners, holes, thin, access, infos, integrity_findings,
        narrow_gaps=gaps, sharp_edges=sharp_edges,
    )

    from dfm.scoring import compute_score, rank_design_changes
    score, subscores = compute_score(findings)
    recommendations = rank_design_changes(findings)

    volume = shape_volume(shape)
    stock_volume = float(np.prod(size)) if np.all(size > 0) else 0.0
    part_stats = {
        "bbox_mm": [round(float(v), 2) for v in size],
        "volume_mm3": round(volume, 1),
        "stock_volume_mm3": round(stock_volume, 1),
        "material_removal_pct": round(100.0 * (1.0 - volume / stock_volume), 1)
        if stock_volume > 0 else None,
        "num_faces": len(faces),
        "num_holes": len(holes),
        "num_internal_corners": len(corners),
        "num_bodies": integrity.num_bodies,
        "watertight": integrity.watertight,
        "free_edges": integrity.num_free_edges,
    }
    setup_info = {
        "estimated_setups": max(len(access.chosen_setups), 1),
        "setup_directions": [DIR_NAMES[d] for d in access.chosen_setups],
        "unreachable_face_count": len(access.unreachable_faces),
    }

    result = AnalysisResult(
        score=score,
        subscores=subscores,
        findings=findings,
        part_stats=part_stats,
        setup_info=setup_info,
        recommendations=recommendations,
    )
    return result, part_mesh
