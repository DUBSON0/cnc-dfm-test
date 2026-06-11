"""Geometry integrity checks: open boundaries and disconnected bodies.

Works at the exact B-rep level — naked (free) edges reveal holes in the
surface, and connected components of the face-adjacency graph reveal
disconnected bodies. Broken geometry makes every other DFM measurement
unreliable, so these findings carry heavy penalties.
"""

from __future__ import annotations

from dataclasses import dataclass

from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)

from dfm.model import Finding, Severity


@dataclass
class IntegrityReport:
    num_solids: int
    num_open_shells: int
    num_free_edges: int
    free_edge_face_indices: list[int]
    num_components: int  # connected face groups (B-rep adjacency)
    # Face indices of every component except the largest (the strays).
    minor_component_faces: list[int]

    @property
    def watertight(self) -> bool:
        return self.num_free_edges == 0 and self.num_open_shells == 0

    @property
    def num_bodies(self) -> int:
        return max(self.num_solids + self.num_open_shells, self.num_components)


def _count_shapes(shape: TopoDS_Shape, kind) -> int:
    smap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, smap)
    return smap.Extent()


def _free_edges(shape: TopoDS_Shape) -> tuple[int, list[int]]:
    """Count naked edges (bordering exactly one face once) and the face
    indices touching them, using the same face indexing as the analyzer."""
    edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_map)

    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)

    free_count = 0
    face_indices: set[int] = set()
    for ei in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(ei))
        if BRep_Tool.Degenerated_s(edge):
            continue  # cone apex / sphere pole — not a real boundary
        ancestors = list(edge_map.FindFromIndex(ei))
        # Seam edges (cylinder closure) list the same face twice, so counting
        # occurrences with multiplicity correctly skips them.
        if len(ancestors) == 1:
            free_count += 1
            fi = fmap.FindIndex(ancestors[0])
            if fi > 0:
                face_indices.add(fi - 1)
    return free_count, sorted(face_indices)


def _open_shells(shape: TopoDS_Shape) -> int:
    """Shells not wrapped in any solid = surface-only geometry."""
    solids_shells: set[int] = set()
    sexp = TopExp_Explorer(shape, TopAbs_SOLID)
    while sexp.More():
        shexp = TopExp_Explorer(sexp.Current(), TopAbs_SHELL)
        while shexp.More():
            solids_shells.add(hash(shexp.Current()))
            shexp.Next()
        sexp.Next()

    open_count = 0
    shexp = TopExp_Explorer(shape, TopAbs_SHELL)
    while shexp.More():
        if hash(shexp.Current()) not in solids_shells:
            open_count += 1
        shexp.Next()
    return open_count


def _connected_components(shape: TopoDS_Shape) -> list[list[int]]:
    """Connected face groups (as face index lists), via union-find on shared
    edges. Exact B-rep connectivity — immune to tessellation artifacts that
    plague mesh-based component counting.
    """
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    n = fmap.Extent()
    if n == 0:
        return []

    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_map)
    for ei in range(1, edge_map.Extent() + 1):
        ids = [fmap.FindIndex(f) - 1 for f in edge_map.FindFromIndex(ei)]
        for other in ids[1:]:
            union(ids[0], other)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def inspect_integrity(shape: TopoDS_Shape) -> IntegrityReport:
    num_free, free_faces = _free_edges(shape)
    components = _connected_components(shape)
    minor_faces = [fi for grp in components[1:] for fi in grp]
    return IntegrityReport(
        num_solids=_count_shapes(shape, TopAbs_SOLID),
        num_open_shells=_open_shells(shape),
        num_free_edges=num_free,
        free_edge_face_indices=free_faces,
        num_components=len(components),
        minor_component_faces=sorted(minor_faces),
    )


def check_integrity(report: IntegrityReport) -> list[Finding]:
    findings: list[Finding] = []

    if report.num_free_edges > 0 or report.num_open_shells > 0:
        n = report.num_free_edges
        findings.append(Finding(
            rule="open_geometry",
            title="Open / non-watertight geometry",
            severity=Severity.CRITICAL,
            detail=(
                f"The model has {n} naked boundary edge(s)"
                + (f" and {report.num_open_shells} open shell(s)" if report.num_open_shells else "")
                + " — it does not enclose a solid volume. Gaps like this come from "
                "unstitched surfaces, deleted faces, or a lossy export, and make "
                "volume, thickness, and accessibility results unreliable."
            ),
            suggestion="Repair the model in CAD: stitch/sew surfaces into a closed "
                       "solid, close the highlighted boundary openings, and re-export "
                       "as a solid (not surface) STEP. Most CAD packages have a "
                       "'check geometry' or 'heal' tool that finds these gaps.",
            action="Stitch the surfaces into a closed solid and re-export the STEP",
            face_indices=report.free_edge_face_indices,
            penalty=30.0,
            data={"free_edges": n, "open_shells": report.num_open_shells},
        ))

    n_bodies = report.num_bodies
    if n_bodies > 1:
        findings.append(Finding(
            rule="multiple_bodies",
            title=f"File contains {n_bodies} disconnected bodies",
            severity=Severity.CRITICAL,
            detail=f"The STEP file contains {n_bodies} separate, non-touching bodies. "
                   "A CNC-milled part must be a single connected solid — disconnected "
                   "bodies are either an assembly, floating reference geometry, or "
                   "pieces that were never joined.",
            suggestion="Export each part to its own STEP file for individual quoting, "
                       "or boolean-union the bodies if they are meant to be one part. "
                       "Delete any leftover construction/reference bodies. The "
                       "highlighted bodies are the ones beyond the largest.",
            action="Export each body as its own STEP file (or boolean-union them)",
            face_indices=report.minor_component_faces,
            penalty=22.0,
            data={"bodies": n_bodies},
        ))

    return findings
