"""End-to-end rule coverage tests against the generated test parts.

Regenerate parts with: .venv/bin/python scripts/make_test_parts.py
"""

from __future__ import annotations

import os

import pytest

from dfm.analyzer import analyze_step_file

PARTS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_parts")

_cache: dict[str, dict] = {}


def analyze(name: str) -> dict:
    if name not in _cache:
        path = os.path.join(PARTS_DIR, f"{name}.step")
        result, _ = analyze_step_file(path)
        _cache[name] = result.to_dict()
    return _cache[name]


def rules_of(report: dict) -> set[str]:
    return {f["rule"] for f in report["findings"]}


def find(report: dict, rule: str) -> list[dict]:
    return [f for f in report["findings"] if f["rule"] == rule]


# ---------------------------------------------------------------------------
# Clean part: no false positives
# ---------------------------------------------------------------------------

def test_good_plate_is_clean():
    report = analyze("good_plate")
    assert report["findings"] == []
    assert report["score"] == 100.0
    assert report["part_stats"]["watertight"] is True
    assert report["part_stats"]["num_bodies"] == 1
    assert report["setup_info"]["estimated_setups"] <= 2


# ---------------------------------------------------------------------------
# bad_bracket: classic pocket/hole/wall problems
# ---------------------------------------------------------------------------

def test_bad_bracket_rules():
    report = analyze("bad_bracket")
    rules = rules_of(report)
    assert "deep_small_corner_radius" in rules     # r=1 corners, ~30 mm deep
    assert "sharp_internal_corner" in rules        # square-cut second pocket
    assert "deep_hole" in rules                    # Ø3 x 36 mm
    assert "thin_wall" in rules                    # 1.2 mm wall between pockets
    assert "nonstandard_hole_diameter" in rules    # Ø7.3
    assert "flat_bottom_hole" in rules
    assert report["score"] < 60


def test_bad_bracket_deep_hole_numbers():
    report = analyze("bad_bracket")
    deep = find(report, "deep_hole")
    assert any(f["data"]["depth_to_dia"] > 10 for f in deep)


def test_bad_bracket_thin_wall_thickness():
    report = analyze("bad_bracket")
    thin = find(report, "thin_wall")
    assert thin and min(f["data"]["min_thickness_mm"] for f in thin) == pytest.approx(1.2, abs=0.15)


def test_bad_bracket_side_hole_costs_setup():
    report = analyze("bad_bracket")
    assert report["setup_info"]["estimated_setups"] >= 2


# ---------------------------------------------------------------------------
# fiddly_widget: small radii, micro holes, narrow channels, square corners
# ---------------------------------------------------------------------------

def test_fiddly_tiny_corner_radii():
    report = analyze("fiddly_widget")
    tiny = find(report, "tiny_corner_radius")
    assert tiny
    sev = {f["severity"] for f in tiny}
    assert "critical" in sev  # r=0.5 pocket
    radii = {f["data"]["radius_mm"] for f in tiny}
    assert 0.5 in radii
    assert 1.2 in radii


def test_fiddly_sharp_corners_detected():
    report = analyze("fiddly_widget")
    sharp = find(report, "sharp_internal_corner")
    assert sharp
    # The square pocket has 4 vertical corner edges, ~6 mm deep.
    assert any(f["data"]["count"] >= 4 for f in sharp)
    assert all(f["severity"] == "critical" for f in sharp)


def test_fiddly_narrow_channels():
    report = analyze("fiddly_widget")
    chans = find(report, "narrow_channel")
    widths = sorted(f["data"]["min_width_mm"] for f in chans)
    assert len(widths) == 2
    assert widths[0] == pytest.approx(1.0, abs=0.1)   # critical slot
    assert widths[1] == pytest.approx(2.0, abs=0.1)   # warning slot
    sevs = {f["severity"] for f in chans}
    assert sevs == {"critical", "warning"}


def test_fiddly_micro_holes():
    report = analyze("fiddly_widget")
    micro = find(report, "micro_hole")
    dias = sorted(f["data"]["diameter_mm"] for f in micro)
    assert dias == [pytest.approx(0.6, abs=0.05), pytest.approx(1.2, abs=0.05)]
    by_dia = {round(f["data"]["diameter_mm"], 1): f["severity"] for f in micro}
    assert by_dia[0.6] == "critical"
    assert by_dia[1.2] == "warning"


def test_fiddly_standard_hole_not_flagged():
    report = analyze("fiddly_widget")
    # The Ø6 through hole is standard and 3.3:1 — must not trigger hole rules.
    for f in find(report, "nonstandard_hole_diameter") + find(report, "deep_hole"):
        assert f["data"]["diameter_mm"] < 6.0


# ---------------------------------------------------------------------------
# threaded_plate: tapped-hole inference from tap-drill diameters
# ---------------------------------------------------------------------------

def test_threaded_plate_recognizes_three_tapped_holes():
    report = analyze("threaded_plate")
    # M6, M3, M8 bores match tap drills; the Ø6 clearance hole must not.
    assert report["part_stats"]["num_tapped_holes"] == 3


def test_threaded_plate_small_thread():
    report = analyze("threaded_plate")
    small = find(report, "small_thread")
    assert len(small) == 1
    f = small[0]
    assert f["severity"] == "warning"          # M3 → fragile but not sub-M2
    assert f["data"]["designation"] == "M3×0.5"
    assert f["data"]["nominal_mm"] == 3.0


def test_threaded_plate_deep_thread():
    report = analyze("threaded_plate")
    deep = find(report, "deep_thread")
    assert len(deep) == 1
    f = deep[0]
    assert f["data"]["designation"] == "M8×1.25"
    assert f["data"]["engagement_ratio"] > 2.5


def test_threaded_plate_clean_tapped_hole_is_info():
    report = analyze("threaded_plate")
    info = find(report, "tapped_hole")
    # The well-proportioned M6 hole is recognized but costs nothing.
    assert any(f["data"]["designation"] == "M6×1" for f in info)
    assert all(f["severity"] == "info" for f in info)


def test_threaded_plate_clearance_hole_not_threaded():
    report = analyze("threaded_plate")
    # No recognized thread should sit on the Ø6.0 clearance bore.
    for f in find(report, "tapped_hole") + find(report, "small_thread") + find(report, "deep_thread"):
        assert f["data"]["nominal_mm"] in (3.0, 6.0, 8.0)
        # tap drill of a real thread is never 6.0 (that's the clearance bore dia)
        assert f["data"].get("tap_drill_mm", 5.0) != 6.0


def test_good_plate_holes_not_misread_as_threads():
    report = analyze("good_plate")
    # Ø6 clearance holes are not tap drills — keep the clean part clean.
    assert report["part_stats"]["num_tapped_holes"] == 0
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# Geometry integrity
# ---------------------------------------------------------------------------

def test_open_box_integrity():
    report = analyze("open_box")
    open_findings = find(report, "open_geometry")
    assert len(open_findings) == 1
    f = open_findings[0]
    assert f["severity"] == "critical"
    assert f["data"]["free_edges"] == 4          # the 4 edges of the missing top
    assert len(f["face_indices"]) == 4           # the 4 side walls
    assert report["part_stats"]["watertight"] is False
    assert report["score"] <= 40.0               # integrity gate


def test_two_bodies_integrity():
    report = analyze("two_bodies")
    multi = find(report, "multiple_bodies")
    assert len(multi) == 1
    assert multi[0]["data"]["bodies"] == 2
    # The smaller body's 6 faces should be highlighted.
    assert len(multi[0]["face_indices"]) == 6
    assert report["part_stats"]["num_bodies"] == 2
    assert report["score"] <= 40.0


# ---------------------------------------------------------------------------
# Scoring sanity
# ---------------------------------------------------------------------------

def test_score_ordering():
    good = analyze("good_plate")["score"]
    bad = analyze("bad_bracket")["score"]
    fiddly = analyze("fiddly_widget")["score"]
    assert good > bad
    assert good > fiddly
    assert all(0 <= s <= 100 for s in (good, bad, fiddly))


def test_recommendations_ranked_by_impact():
    report = analyze("fiddly_widget")
    recs = report["recommendations"]
    assert len(recs) == len(report["findings"])
    # Sorted by solo impact, descending.
    gains = [r["solo_gain"] for r in recs]
    assert gains == sorted(gains, reverse=True)
    # Cumulative projection is monotonic and ends at a perfect score.
    cums = [r["score_after"] for r in recs]
    assert cums == sorted(cums)
    assert cums[-1] == 100.0
    assert cums[0] > report["score"]
    # Every change has an actionable instruction and points at a finding.
    for r in recs:
        assert len(r["action"]) > 15
        assert 0 <= r["finding_index"] < len(report["findings"])


def test_recommendations_top_change_is_the_worst_problem():
    report = analyze("fiddly_widget")
    # The unmillable square corners should be the #1 design change.
    assert report["recommendations"][0]["rule"] == "sharp_internal_corner"


def test_clean_part_has_no_recommendations():
    assert analyze("good_plate")["recommendations"] == []


def test_every_finding_is_well_formed():
    for name in ("bad_bracket", "fiddly_widget", "open_box", "two_bodies"):
        report = analyze(name)
        for f in report["findings"]:
            assert f["severity"] in ("critical", "warning", "info")
            assert len(f["detail"]) > 80, f"{f['rule']} detail too terse"
            assert len(f["suggestion"]) > 80, f"{f['rule']} suggestion too terse"
            assert isinstance(f["face_indices"], list)
