# cnc-dfm-test

Analyze 3D models for CNC mill manufacturing (DFM).


Instant-quote-style DFM analysis for CNC-milled parts. Upload a STEP file, get:

- a 0–100 manufacturability score with per-category breakdown
- a 3D viewer with problem faces highlighted by severity
- concrete design-for-manufacturing suggestions (Xometry-style feedback)

## How it works

The part is loaded as exact B-rep geometry through Open CASCADE (`cadquery-ocp`),
not just a mesh, so the analyzer knows true surface types, hole diameters, and
corner radii. The pipeline:

1. **Surface classification** — every face is bucketed (plane / cylinder / cone /
   sphere / torus / freeform) with concavity determined from oriented normals.
2. **Feature detection** — concave full-revolution cylinders become holes
   (through/blind, flat vs drill-point bottom); partial concave cylinders become
   internal corner radii with depth measured along the axis. Bores sitting on a
   standard metric tap-drill diameter are inferred to be **tapped holes** and get
   thread-specific checks (no STEP thread callout is needed).
3. **Thin-wall detection** — inward ray casting from mesh samples measures local
   thickness.
4. **Accessibility** — ray casting along the six axis directions determines which
   faces a 3-axis tool can reach; a greedy set cover estimates setup count and
   flags unreachable (undercut) faces.
5. **Rules + scoring** — each finding carries a penalty; categories decay
   exponentially and combine into a weighted overall score blended with the
   worst category.

## Run it

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# Web app
.venv/bin/uvicorn server:app --port 8000
# open http://localhost:8000

# CLI
.venv/bin/python cli.py test_parts/bad_bracket.step

# Regenerate the demo parts
.venv/bin/python scripts/make_test_parts.py
```

## Checks implemented

| Rule | Trigger |
|---|---|
| Open / non-watertight geometry | naked B-rep edges or shells outside any solid |
| Multiple bodies | disconnected face groups / multiple solids in one file |
| Sharp internal corner | zero-radius concave edge no accessible tool direction can form |
| Corner radius vs depth | tool stickout (depth / corner dia) > 6:1 |
| Tiny corner radius | corner radius < 1.6 mm (critical < 0.6 mm) — micro tooling |
| Deep hole | depth/diameter > 4:1 (critical > 10:1) |
| Micro hole | diameter < 1.5 mm (critical < 0.8 mm) |
| Non-standard hole size | no standard metric drill within 0.05 mm |
| Flat-bottom blind hole | planar floor perpendicular to bore axis |
| Tapped hole (inferred) | bore diameter matches a metric tap drill (±0.08 mm) |
| Small thread | inferred thread ≤ M3 (critical ≤ M2) — fragile, snap-prone taps |
| Excessive thread engagement | tapped depth > 2.5× thread diameter |
| Thin wall / floor | local material thickness < 1.5 mm (critical < 0.8 mm) |
| Narrow slot / channel | opposing walls < 2.6 mm apart (critical < 1.2 mm) |
| Unreachable faces | not visible from any axis direction (undercuts) |
| Setup count | ≥ 3 estimated setups |
| Freeform surfaces | > 2% of area is NURBS |

Most findings include a side-by-side "as drawn vs machinable" drawing in the web
UI. Run the test suite with `.venv/bin/python -m pytest tests/`.

## Ranked design changes

Every analysis also produces a **"Most critical design changes"** list: each
finding is removed in turn and the part re-scored, so changes are ranked by how
many points fixing them would actually recover (category penalties saturate, so
this is more honest than sorting by penalty). The list also shows a cumulative
projection — your score after applying change 1, then 1+2, and so on up to 100.
Clicking a change in the web UI highlights the affected faces on the model.

## Limitations / next steps

- 3-axis logic only (no 3+2 tilted access directions yet)
- Threads are *inferred* from tap-drill diameters, not read from callouts; true
  thread class/depth and tolerance awareness would need STEP AP242 PMI
- Heuristic scoring — calibrate weights against real quote data
- Pocket recognition is corner-based; no full AFR (automatic feature recognition)
