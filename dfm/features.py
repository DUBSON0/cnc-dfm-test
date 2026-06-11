"""Feature detection: holes, internal corners, thin walls, accessibility."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import trimesh
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)

from dfm.geometry import PartMesh
from dfm.model import FaceInfo, SurfaceKind

FULL_SWEEP = 2.0 * math.pi
RAY_EPS = 1e-3


# ---------------------------------------------------------------------------
# Topology helpers
# ---------------------------------------------------------------------------

def face_adjacency(shape: TopoDS_Shape, faces: list[TopoDS_Face]) -> dict[int, set[int]]:
    """Map face index -> indices of faces sharing an edge."""
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)

    def idx_of(face) -> int | None:
        i = fmap.FindIndex(face)
        return i - 1 if i > 0 else None

    edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_map)

    adj: dict[int, set[int]] = {i: set() for i in range(len(faces))}
    for ei in range(1, edge_map.Extent() + 1):
        flist = edge_map.FindFromIndex(ei)
        ids = []
        for f in flist:
            j = idx_of(f)
            if j is not None:
                ids.append(j)
        for a in ids:
            for b in ids:
                if a != b:
                    adj[a].add(b)
    return adj


def faces_in_map_order(shape: TopoDS_Shape) -> list[TopoDS_Face]:
    """Faces indexed consistently with TopTools_IndexedMapOfShape order."""
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    return [TopoDS.Face_s(fmap.FindKey(i)) for i in range(1, fmap.Extent() + 1)]


def cylinder_axial_extent(face: TopoDS_Face, info: FaceInfo) -> float:
    """Length of a cylindrical/conical face along its axis (V extent)."""
    _, _, vmin, vmax = BRepTools.UVBounds_s(face)
    return abs(vmax - vmin)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

@dataclass
class Hole:
    face_indices: list[int]
    radius: float
    depth: float
    axis_origin: np.ndarray
    axis_dir: np.ndarray
    through: bool = False
    flat_bottom: bool = False


@dataclass
class InternalCorner:
    face_index: int
    radius: float
    depth: float
    axis_dir: np.ndarray
    centroid: np.ndarray


@dataclass
class ThinRegion:
    face_index: int
    thickness: float
    location: np.ndarray


@dataclass
class NarrowGap:
    """A narrow air gap between opposing walls (slot/channel too tight for
    a reasonable end mill)."""
    face_index: int
    width: float
    location: np.ndarray


@dataclass
class SharpConcaveEdge:
    """A zero-radius concave edge between two walls that no accessible tool
    orientation can produce (e.g. square pocket corners)."""
    face_indices: list[int]
    length: float
    midpoint: np.ndarray


@dataclass
class AccessibilityResult:
    directions: list[np.ndarray]
    # face index -> set of direction indices it is machinable from
    face_access: dict[int, set[int]]
    chosen_setups: list[int]  # direction indices from greedy set cover
    unreachable_faces: list[int]


def _same_axis(a_origin, a_dir, b_origin, b_dir, tol_ang=1e-3, tol_dist=1e-4) -> bool:
    if abs(abs(float(np.dot(a_dir, b_dir))) - 1.0) > tol_ang:
        return False
    d = np.asarray(b_origin) - np.asarray(a_origin)
    perp = d - np.dot(d, a_dir) * np.asarray(a_dir)
    return float(np.linalg.norm(perp)) < tol_dist + 1e-9 * (1 + np.linalg.norm(d))


def detect_holes_and_corners(
    faces: list[TopoDS_Face],
    infos: list[FaceInfo],
    adjacency: dict[int, set[int]],
    ray_caster: "RayCaster",
) -> tuple[list[Hole], list[InternalCorner]]:
    """Split concave cylinders into holes (full revolution) and internal corners."""
    concave_cyls = [
        i for i in infos
        if i.kind == SurfaceKind.CYLINDER and i.concave
    ]

    # Group co-axial same-radius faces (CAD kernels often split bores in half).
    groups: list[list[FaceInfo]] = []
    for info in concave_cyls:
        placed = False
        for g in groups:
            ref = g[0]
            if (
                abs(ref.radius - info.radius) < 1e-6
                and _same_axis(ref.axis_origin, ref.axis_dir, info.axis_origin, info.axis_dir)
            ):
                g.append(info)
                placed = True
                break
        if not placed:
            groups.append([info])

    holes: list[Hole] = []
    corners: list[InternalCorner] = []

    for g in groups:
        total_sweep = sum(i.sweep_angle or 0.0 for i in g)
        if total_sweep >= FULL_SWEEP - 0.05:
            ref = g[0]
            axis_dir = np.asarray(ref.axis_dir)
            axis_origin = np.asarray(ref.axis_origin)
            depth = max(cylinder_axial_extent(faces[i.index], i) for i in g)
            hole = Hole(
                face_indices=[i.index for i in g],
                radius=float(ref.radius),
                depth=float(depth),
                axis_origin=axis_origin,
                axis_dir=axis_dir,
            )
            _classify_hole_ends(hole, g, infos, adjacency, ray_caster)
            holes.append(hole)
        else:
            for i in g:
                depth = cylinder_axial_extent(faces[i.index], i)
                corners.append(
                    InternalCorner(
                        face_index=i.index,
                        radius=float(i.radius),
                        depth=float(depth),
                        axis_dir=np.asarray(i.axis_dir),
                        centroid=np.asarray(i.centroid),
                    )
                )
    return holes, corners


def _classify_hole_ends(
    hole: Hole,
    group: list[FaceInfo],
    infos: list[FaceInfo],
    adjacency: dict[int, set[int]],
    ray_caster: "RayCaster",
) -> None:
    """Determine through vs blind and flat vs drill-point bottom."""
    # Through check: cast from the hole's mid-axis point both ways along axis.
    centroid = np.mean([np.asarray(infos[i].centroid) for i in hole.face_indices], axis=0)
    mid = centroid + (hole.axis_origin - centroid).dot(hole.axis_dir) * hole.axis_dir
    # Project centroid onto axis line for a guaranteed-inside-bore point.
    rel = centroid - hole.axis_origin
    mid = hole.axis_origin + np.dot(rel, hole.axis_dir) * hole.axis_dir
    up_blocked = ray_caster.hits(mid, hole.axis_dir)
    down_blocked = ray_caster.hits(mid, -hole.axis_dir)
    hole.through = not up_blocked and not down_blocked

    if not hole.through:
        # Flat bottom if an adjacent planar face is perpendicular to the axis
        # and concave side (i.e. a floor); drill point shows up as a cone.
        for fi in hole.face_indices:
            for nb in adjacency.get(fi, ()):  
                ninfo = infos[nb]
                if ninfo.kind == SurfaceKind.CONE:
                    return  # drill point — fine
                if ninfo.kind == SurfaceKind.PLANE and ninfo.normal is not None:
                    if abs(abs(np.dot(ninfo.normal, hole.axis_dir)) - 1.0) < 1e-3:
                        # plane perpendicular to hole axis, smaller than the bore
                        if ninfo.area <= math.pi * hole.radius**2 * 1.5:
                            hole.flat_bottom = True
                            return


# ---------------------------------------------------------------------------
# Ray casting (mesh-based)
# ---------------------------------------------------------------------------

class RayCaster:
    def __init__(self, part_mesh: PartMesh):
        self.mesh = trimesh.Trimesh(
            vertices=part_mesh.vertices,
            faces=part_mesh.triangles,
            process=False,
        )
        self.part_mesh = part_mesh
        self._ray = self.mesh.ray

    def first_hit_distances(self, origins: np.ndarray, directions: np.ndarray) -> np.ndarray:
        """Distance to first hit per ray; inf where no hit."""
        out = np.full(len(origins), np.inf)
        locs, ray_ids, _ = self._ray.intersects_location(
            origins, directions, multiple_hits=False
        )
        if len(ray_ids):
            d = np.linalg.norm(locs - origins[ray_ids], axis=1)
            out[ray_ids] = d
        return out

    def hits(self, origin: np.ndarray, direction: np.ndarray) -> bool:
        d = self.first_hit_distances(
            np.asarray(origin, dtype=float).reshape(1, 3) + np.asarray(direction) * RAY_EPS,
            np.asarray(direction, dtype=float).reshape(1, 3),
        )
        return bool(np.isfinite(d[0]))


# ---------------------------------------------------------------------------
# Thin walls
# ---------------------------------------------------------------------------

def detect_thin_regions(
    caster: RayCaster,
    min_thickness: float,
    max_samples: int = 4000,
) -> list[ThinRegion]:
    """Sample triangle centroids, shoot rays inward, report thin spots per face."""
    mesh = caster.mesh
    pm = caster.part_mesh

    centroids = mesh.triangles_center
    normals = mesh.face_normals
    n = len(centroids)
    if n > max_samples:
        # Area-weighted sample so big faces aren't starved.
        areas = mesh.area_faces
        probs = areas / areas.sum()
        rng = np.random.default_rng(42)
        sel = rng.choice(n, size=max_samples, replace=False, p=probs)
    else:
        sel = np.arange(n)

    origins = centroids[sel] - normals[sel] * RAY_EPS
    dirs = -normals[sel]
    dists = caster.first_hit_distances(origins, dirs)

    thin: dict[int, ThinRegion] = {}
    for k, tri_idx in enumerate(sel):
        t = dists[k] + RAY_EPS
        if not np.isfinite(t) or t >= min_thickness:
            continue
        fi = int(pm.tri_face_index[tri_idx])
        if fi not in thin or t < thin[fi].thickness:
            thin[fi] = ThinRegion(
                face_index=fi,
                thickness=float(t),
                location=centroids[tri_idx],
            )
    return list(thin.values())


def detect_sharp_concave_edges(
    shape: TopoDS_Shape,
    infos: list[FaceInfo],
    access: "AccessibilityResult",
    min_length: float = 0.5,
) -> list[SharpConcaveEdge]:
    """Find zero-radius internal corners: straight concave edges between two
    planar walls that cannot be produced by any accessible tool direction.

    A concave edge IS millable when some accessible direction is perpendicular
    to it with both faces visible (a flat end mill then forms the sharp corner
    with its tip + side). What's left — e.g. vertical corners of a square-cut
    pocket — would need a tool with a square corner spinning about that axis,
    which doesn't exist.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line

    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_map)

    results: list[SharpConcaveEdge] = []
    for ei in range(1, edge_map.Extent() + 1):
        face_ids = sorted({fmap.FindIndex(f) - 1 for f in edge_map.FindFromIndex(ei)})
        if len(face_ids) != 2:
            continue
        i1, i2 = face_ids
        f1, f2 = infos[i1], infos[i2]
        if f1.kind != SurfaceKind.PLANE or f2.kind != SurfaceKind.PLANE:
            continue
        if f1.normal is None or f2.normal is None:
            continue
        n1, n2 = np.asarray(f1.normal), np.asarray(f2.normal)

        # Sharp dihedral only (fillets/tangent faces have near-parallel normals).
        cos_n = float(np.dot(n1, n2))
        if cos_n > math.cos(math.radians(25)) or cos_n < math.cos(math.radians(150)):
            continue

        edge = TopoDS.Edge_s(edge_map.FindKey(ei))
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() != GeomAbs_Line:
            continue
        p_a = curve.Value(curve.FirstParameter())
        p_b = curve.Value(curve.LastParameter())
        a = np.array([p_a.X(), p_a.Y(), p_a.Z()])
        b = np.array([p_b.X(), p_b.Y(), p_b.Z()])
        length = float(np.linalg.norm(b - a))
        if length < min_length:
            continue
        t = (b - a) / length
        mid = (a + b) / 2.0

        # Concavity: walking from the edge into face 1's interior should move
        # WITH face 2's outward normal (material wraps >180° around the edge).
        w1 = np.asarray(f1.centroid) - mid
        w1 -= np.dot(w1, t) * t
        w1 -= np.dot(w1, n1) * n1  # keep it tangent to face 1
        norm = np.linalg.norm(w1)
        if norm < 1e-9:
            continue
        w1 /= norm
        if float(np.dot(w1, n2)) < 0.2:
            continue  # convex or ambiguous — fine for milling

        # Millability: any accessible direction perpendicular to the edge with
        # both faces visible can form this corner with the tool tip + side.
        millable = False
        for di, d in enumerate(access.directions):
            if abs(float(np.dot(t, d))) > 0.1:
                continue
            if np.dot(n1, d) < -1e-3 or np.dot(n2, d) < -1e-3:
                continue
            if di in access.face_access.get(i1, set()) and di in access.face_access.get(i2, set()):
                millable = True
                break
        if not millable:
            results.append(SharpConcaveEdge(face_indices=[i1, i2], length=length, midpoint=mid))
    return results


def detect_narrow_gaps(
    caster: RayCaster,
    exclude_faces: set[int],
    max_gap: float = 2.6,
    max_samples: int = 4000,
) -> list[NarrowGap]:
    """Probe the air gap in front of each surface sample: a ray leaving the
    material along the outward normal that hits the part again within
    `max_gap` mm reveals a slot/channel narrower than any sturdy end mill.

    Faces in `exclude_faces` (hole bores — they have their own rule) are
    skipped.
    """
    mesh = caster.mesh
    pm = caster.part_mesh

    centroids = mesh.triangles_center
    normals = mesh.face_normals
    n = len(centroids)
    if n > max_samples:
        areas = mesh.area_faces
        probs = areas / areas.sum()
        rng = np.random.default_rng(11)
        sel = rng.choice(n, size=max_samples, replace=False, p=probs)
    else:
        sel = np.arange(n)

    keep = np.array(
        [int(pm.tri_face_index[t]) not in exclude_faces for t in sel], dtype=bool
    )
    sel = sel[keep]
    if len(sel) == 0:
        return []

    origins = centroids[sel] + normals[sel] * RAY_EPS
    dists = caster.first_hit_distances(origins, normals[sel])

    gaps: dict[int, NarrowGap] = {}
    for k, tri_idx in enumerate(sel):
        w = dists[k] + RAY_EPS
        if not np.isfinite(w) or w >= max_gap:
            continue
        fi = int(pm.tri_face_index[tri_idx])
        if fi not in gaps or w < gaps[fi].width:
            gaps[fi] = NarrowGap(face_index=fi, width=float(w), location=centroids[tri_idx])
    return list(gaps.values())


# ---------------------------------------------------------------------------
# Accessibility / setups
# ---------------------------------------------------------------------------

AXIS_DIRECTIONS = [
    np.array([0.0, 0.0, 1.0]),
    np.array([0.0, 0.0, -1.0]),
    np.array([1.0, 0.0, 0.0]),
    np.array([-1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]),
    np.array([0.0, -1.0, 0.0]),
]


def analyze_accessibility(
    caster: RayCaster,
    infos: list[FaceInfo],
    max_samples: int = 3000,
    coverage_threshold: float = 0.85,
) -> AccessibilityResult:
    """For each face, find which tool directions can reach it (3-axis logic).

    A sample point is machinable from direction d (tool approaching along -d,
    i.e. d points from the part toward the spindle) when:
      - the surface normal does not oppose d beyond side-milling tolerance, and
      - a ray from the point toward d escapes the part (nothing overhangs it).
    """
    mesh = caster.mesh
    pm = caster.part_mesh

    centroids = mesh.triangles_center
    normals = mesh.face_normals
    areas = mesh.area_faces
    n = len(centroids)
    if n > max_samples:
        probs = areas / areas.sum()
        rng = np.random.default_rng(7)
        sel = rng.choice(n, size=max_samples, replace=False, p=probs)
    else:
        sel = np.arange(n)

    tri_faces = pm.tri_face_index[sel]
    face_total: dict[int, float] = {}
    face_ok: dict[int, dict[int, float]] = {}
    for k, tri in enumerate(sel):
        fi = int(tri_faces[k])
        face_total[fi] = face_total.get(fi, 0.0) + areas[tri]

    for di, d in enumerate(AXIS_DIRECTIONS):
        ndot = normals[sel] @ d
        candidates = np.where(ndot > -1e-3)[0]  # walls parallel to tool OK
        if len(candidates) == 0:
            continue
        # Offset along the surface normal so grazing rays don't self-intersect
        # the faceted wall they start on.
        origins = (
            centroids[sel[candidates]]
            + normals[sel[candidates]] * RAY_EPS * 5
            + d * RAY_EPS * 5
        )
        dirs = np.tile(d, (len(candidates), 1))
        dists = caster.first_hit_distances(origins, dirs)
        escaped = ~np.isfinite(dists)
        for k_local, esc in zip(candidates, escaped):
            if not esc:
                continue
            tri = sel[k_local]
            fi = int(tri_faces[k_local])
            face_ok.setdefault(fi, {}).setdefault(di, 0.0)
            face_ok[fi][di] += areas[tri]

    face_access: dict[int, set[int]] = {}
    for fi, total in face_total.items():
        dirs_ok = set()
        for di, ok_area in face_ok.get(fi, {}).items():
            if ok_area / total >= coverage_threshold:
                dirs_ok.add(di)
        face_access[fi] = dirs_ok

    # Greedy set cover for setups (prefer Z directions first as tie-break).
    uncovered = {fi for fi, dirs in face_access.items() if dirs}
    unreachable = sorted(fi for fi, dirs in face_access.items() if not dirs)
    chosen: list[int] = []
    while uncovered:
        best_di, best_gain = None, -1
        for di in range(len(AXIS_DIRECTIONS)):
            gain = sum(1 for fi in uncovered if di in face_access[fi])
            if gain > best_gain:
                best_di, best_gain = di, gain
        if not best_gain:
            break
        chosen.append(best_di)
        uncovered = {fi for fi in uncovered if best_di not in face_access[fi]}

    return AccessibilityResult(
        directions=AXIS_DIRECTIONS,
        face_access=face_access,
        chosen_setups=chosen,
        unreachable_faces=unreachable,
    )
