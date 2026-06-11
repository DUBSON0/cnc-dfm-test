"""STEP loading, face classification, and meshing on top of OCCT (OCP)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import (
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape

from dfm.model import FaceInfo, SurfaceKind


def load_step(path: str) -> TopoDS_Shape:
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise ValueError(f"Failed to read STEP file: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError(f"STEP file contains no usable shapes: {path}")
    return shape


def explode_faces(shape: TopoDS_Shape) -> list[TopoDS_Face]:
    faces: list[TopoDS_Face] = []
    seen: set[int] = set()
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        h = hash(face)
        if h not in seen:
            seen.add(h)
            faces.append(face)
        exp.Next()
    return faces


def face_area_and_centroid(face: TopoDS_Face) -> tuple[float, tuple[float, float, float]]:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    c = props.CentreOfMass()
    return props.Mass(), (c.X(), c.Y(), c.Z())


def shape_volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def shape_bbox(shape: TopoDS_Shape) -> tuple[np.ndarray, np.ndarray]:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return np.array([xmin, ymin, zmin]), np.array([xmax, ymax, zmax])


def _oriented_normal_at(face: TopoDS_Face, u: float, v: float) -> tuple[gp_Pnt, gp_Vec]:
    """Outward (material-respecting) normal at UV, accounting for face orientation."""
    gp_face = BRepGProp_Face(face)
    pnt = gp_Pnt()
    vec = gp_Vec()
    gp_face.Normal(u, v, pnt, vec)
    return pnt, vec


def classify_face(face: TopoDS_Face, index: int) -> FaceInfo:
    surf = BRepAdaptor_Surface(face)
    stype = surf.GetType()
    area, centroid = face_area_and_centroid(face)

    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    umid, vmid = (umin + umax) / 2.0, (vmin + vmax) / 2.0

    info = FaceInfo(index=index, kind=SurfaceKind.OTHER, area=area, centroid=centroid)

    if stype == GeomAbs_Plane:
        info.kind = SurfaceKind.PLANE
        _, n = _oriented_normal_at(face, umid, vmid)
        if n.Magnitude() > 1e-12:
            n.Normalize()
            info.normal = (n.X(), n.Y(), n.Z())
    elif stype in (GeomAbs_Cylinder, GeomAbs_Cone):
        if stype == GeomAbs_Cylinder:
            info.kind = SurfaceKind.CYLINDER
            geom = surf.Cylinder()
            info.radius = geom.Radius()
        else:
            info.kind = SurfaceKind.CONE
            geom = surf.Cone()
            info.radius = geom.RefRadius()
        ax = geom.Axis()
        loc, adir = ax.Location(), ax.Direction()
        info.axis_origin = (loc.X(), loc.Y(), loc.Z())
        info.axis_dir = (adir.X(), adir.Y(), adir.Z())
        info.sweep_angle = abs(umax - umin)
        info.concave = _is_concave_revolved(face, umid, vmid, info)
    elif stype == GeomAbs_Sphere:
        info.kind = SurfaceKind.SPHERE
        info.radius = surf.Sphere().Radius()
        info.concave = _is_concave_point(face, umid, vmid, surf.Sphere().Location())
    elif stype == GeomAbs_Torus:
        info.kind = SurfaceKind.TORUS
        torus = surf.Torus()
        info.radius = torus.MinorRadius()
        ax = torus.Axis()
        loc, adir = ax.Location(), ax.Direction()
        info.axis_origin = (loc.X(), loc.Y(), loc.Z())
        info.axis_dir = (adir.X(), adir.Y(), adir.Z())
        # Concavity of the tube itself (fillet vs groove) — approximate by
        # checking the normal vs the direction from the tube center circle.
        info.concave = _is_concave_torus(face, umid, vmid, torus)
    else:
        info.kind = SurfaceKind.FREEFORM

    return info


def _is_concave_revolved(face: TopoDS_Face, u: float, v: float, info: FaceInfo) -> bool:
    """True if material lies outside the revolved surface (hole / internal wall)."""
    pnt, n = _oriented_normal_at(face, u, v)
    if n.Magnitude() < 1e-12:
        return False
    n.Normalize()
    origin = np.array(info.axis_origin)
    axis = np.array(info.axis_dir)
    p = np.array([pnt.X(), pnt.Y(), pnt.Z()])
    radial = (p - origin) - np.dot(p - origin, axis) * axis
    norm = np.linalg.norm(radial)
    if norm < 1e-12:
        return False
    radial /= norm
    nv = np.array([n.X(), n.Y(), n.Z()])
    # Outward normal pointing toward the axis => material outside => concave.
    return float(np.dot(nv, radial)) < 0.0


def _is_concave_point(face: TopoDS_Face, u: float, v: float, center) -> bool:
    pnt, n = _oriented_normal_at(face, u, v)
    if n.Magnitude() < 1e-12:
        return False
    n.Normalize()
    c = np.array([center.X(), center.Y(), center.Z()])
    p = np.array([pnt.X(), pnt.Y(), pnt.Z()])
    out = p - c
    norm = np.linalg.norm(out)
    if norm < 1e-12:
        return False
    return float(np.dot(out / norm, [n.X(), n.Y(), n.Z()])) < 0.0


def _is_concave_torus(face: TopoDS_Face, u: float, v: float, torus) -> bool:
    pnt, n = _oriented_normal_at(face, u, v)
    if n.Magnitude() < 1e-12:
        return False
    n.Normalize()
    ax = torus.Axis()
    origin = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
    axis = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
    p = np.array([pnt.X(), pnt.Y(), pnt.Z()])
    rel = p - origin
    radial = rel - np.dot(rel, axis) * axis
    rn = np.linalg.norm(radial)
    if rn < 1e-12:
        return False
    # Center of the tube cross-section circle nearest to p.
    tube_center = origin + np.dot(rel, axis) * axis * 0 + radial / rn * torus.MajorRadius()
    tube_center = tube_center + np.dot(rel, axis) * axis
    out = p - tube_center
    on = np.linalg.norm(out)
    if on < 1e-12:
        return False
    return float(np.dot(out / on, [n.X(), n.Y(), n.Z()])) < 0.0


@dataclass
class PartMesh:
    """Triangulated part with per-triangle face indices."""

    vertices: np.ndarray  # (N, 3) float64
    triangles: np.ndarray  # (M, 3) int64
    tri_face_index: np.ndarray  # (M,) int64 — B-rep face index per triangle


def mesh_shape(
    shape: TopoDS_Shape,
    faces: list[TopoDS_Face],
    linear_deflection: float = 0.2,
    angular_deflection: float = 0.35,
) -> PartMesh:
    BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)

    all_verts: list[np.ndarray] = []
    all_tris: list[np.ndarray] = []
    all_fidx: list[np.ndarray] = []
    offset = 0

    for fi, face in enumerate(faces):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        nv, nt = tri.NbNodes(), tri.NbTriangles()
        verts = np.empty((nv, 3), dtype=np.float64)
        for i in range(1, nv + 1):
            p = tri.Node(i)
            if not loc.IsIdentity():
                p = p.Transformed(trsf)
            verts[i - 1] = (p.X(), p.Y(), p.Z())
        tris = np.empty((nt, 3), dtype=np.int64)
        for i in range(1, nt + 1):
            t = tri.Triangle(i)
            a, b, c = t.Get()
            tris[i - 1] = (a - 1, b - 1, c - 1)
        if face.Orientation() == TopAbs_REVERSED:
            tris = tris[:, [0, 2, 1]]
        all_verts.append(verts)
        all_tris.append(tris + offset)
        all_fidx.append(np.full(nt, fi, dtype=np.int64))
        offset += nv

    if not all_verts:
        raise ValueError("Meshing produced no triangles")

    return PartMesh(
        vertices=np.vstack(all_verts),
        triangles=np.vstack(all_tris),
        tri_face_index=np.concatenate(all_fidx),
    )
