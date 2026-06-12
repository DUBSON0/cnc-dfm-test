"""Composite manufacturability scoring."""

from __future__ import annotations

import math

from dfm.model import Finding

# Rule -> scoring category
CATEGORY_OF_RULE = {
    "sharp_internal_corner": "features",
    "deep_small_corner_radius": "features",
    "tiny_corner_radius": "features",
    "deep_hole": "features",
    "micro_hole": "features",
    "nonstandard_hole_diameter": "features",
    "flat_bottom_hole": "features",
    "small_thread": "features",
    "deep_thread": "features",
    "tapped_hole": "features",
    "thin_wall": "thin_features",
    "narrow_channel": "thin_features",
    "unreachable_faces": "accessibility",
    "many_setups": "setups",
    "freeform_surfaces": "surface_finish",
    "open_geometry": "integrity",
    "multiple_bodies": "integrity",
}

CATEGORY_WEIGHTS = {
    "features": 0.27,
    "setups": 0.22,
    "accessibility": 0.18,
    "thin_features": 0.13,
    "surface_finish": 0.08,
    "integrity": 0.12,
}

# Penalty scale at which a category saturates toward 0.
SATURATION = {
    "features": 35.0,
    "setups": 18.0,
    "accessibility": 25.0,
    "thin_features": 25.0,
    "surface_finish": 20.0,
    "integrity": 20.0,
}


def compute_score(findings: list[Finding]) -> tuple[float, dict[str, float]]:
    """Return (overall 0-100, per-category subscores 0-100).

    Each category decays exponentially with accumulated penalty so one
    catastrophic feature doesn't zero the whole score, but repeated issues
    keep dragging it down.
    """
    penalties: dict[str, float] = {c: 0.0 for c in CATEGORY_WEIGHTS}
    for f in findings:
        cat = CATEGORY_OF_RULE.get(f.rule, "features")
        penalties[cat] += f.penalty

    subscores: dict[str, float] = {}
    weighted = 0.0
    for cat, weight in CATEGORY_WEIGHTS.items():
        s = 100.0 * math.exp(-penalties[cat] / SATURATION[cat])
        subscores[cat] = s
        weighted += weight * s
    # Blend in the worst category so one catastrophic area can't hide behind
    # otherwise-clean subscores.
    overall = 0.65 * weighted + 0.35 * min(subscores.values())
    # Broken geometry gates everything: a file that isn't a single closed
    # solid can't be quoted as-is, regardless of how nice its features are.
    if subscores.get("integrity", 100.0) < 50.0:
        overall = min(overall, 40.0)
    return overall, subscores


def rank_design_changes(findings: list[Finding]) -> list[dict]:
    """Rank findings by how much fixing each one would raise the score.

    For every finding we re-score the part without it ("fix just this") and
    sort by that solo impact. Then we walk the list in that order, removing
    findings cumulatively, so `score_after` shows the projected score as the
    designer applies change 1, then 1+2, etc. — ending at 100 when everything
    is addressed. (Solo gains don't sum linearly because category penalties
    saturate; the cumulative walk is what's honest.)
    """
    if not findings:
        return []

    base, _ = compute_score(findings)

    solo: list[tuple[float, int]] = []
    for i in range(len(findings)):
        without, _ = compute_score(findings[:i] + findings[i + 1:])
        solo.append((without - base, i))
    solo.sort(key=lambda x: (-x[0], x[1]))

    changes: list[dict] = []
    remaining = list(findings)
    current = base
    for solo_gain, i in solo:
        f = findings[i]
        remaining.remove(f)
        after, _ = compute_score(remaining)
        changes.append({
            "finding_index": i,
            "rule": f.rule,
            "severity": f.severity.value,
            "action": f.action or f.title,
            "face_indices": f.face_indices,
            "solo_gain": round(solo_gain, 1),
            "cumulative_gain": round(after - current, 1),
            "score_after": round(after, 1),
        })
        current = after
    return changes
