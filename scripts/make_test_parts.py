"""Generate test STEP parts with known DFM problems."""

from __future__ import annotations

import math
import os
import sys

from OCP.BRep import BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape


def fillet_vertical_edges(shape: TopoDS_Shape, radius: float) -> TopoDS_Shape:
    """Fillet only edges parallel to Z (pocket corner edges)."""
    fillet = BRepFilletAPI_MakeFillet(shape)
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        vexp = TopExp_Explorer(edge, TopAbs_VERTEX)
        pts = []
        while vexp.More():
            p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vexp.Current()))
            pts.append((p.X(), p.Y(), p.Z()))
            vexp.Next()
        if len(pts) == 2:
            (x1, y1, z1), (x2, y2, z2) = pts
            if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9 and abs(z1 - z2) > 1e-9:
                fillet.Add(radius, edge)
        exp.Next()
    return fillet.Shape()

OUT = os.path.join(os.path.dirname(__file__), "..", "test_parts")


def write_step(shape: TopoDS_Shape, name: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    path = os.path.abspath(os.path.join(OUT, name))
    writer.Write(path)
    print(f"wrote {path}")


def cyl(x: float, y: float, z: float, d: gp_Dir, radius: float, height: float) -> TopoDS_Shape:
    ax = gp_Ax2(gp_Pnt(x, y, z), d)
    return BRepPrimAPI_MakeCylinder(ax, radius, height).Shape()


def make_bad_bracket() -> TopoDS_Shape:
    """80x60x40 block with several deliberate DFM problems:

    - deep narrow pocket with sharp (tiny-radius) internal corners
    - deep small hole (high depth/diameter)
    - non-standard hole diameter
    - thin wall between pocket and outside
    - a side hole forcing an extra setup
    """
    body = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 80.0, 60.0, 40.0).Shape()

    # Deep narrow pocket: 30 x 12, 32 deep => depth/width ~ 2.7, with r=1 corners
    # (corner radius 1mm at 32mm depth => needs 32:1 L/D end mill: terrible).
    pocket = BRepPrimAPI_MakeBox(gp_Pnt(10, 10, 8), 30.0, 12.0, 33.0).Shape()
    fillet = BRepFilletAPI_MakeFillet(pocket)
    exp = TopExp_Explorer(pocket, TopAbs_EDGE)
    while exp.More():
        fillet.Add(1.0, TopoDS.Edge_s(exp.Current()))
        exp.Next()
    pocket = fillet.Shape()
    body = BRepAlgoAPI_Cut(body, pocket).Shape()

    # Thin wall: second pocket leaving only 1.2 mm wall to the first one.
    pocket2 = BRepPrimAPI_MakeBox(gp_Pnt(10, 23.2, 8), 30.0, 12.0, 33.0).Shape()
    body = BRepAlgoAPI_Cut(body, pocket2).Shape()

    # Deep small hole from top: d=3, depth=36 => 12:1.
    hole1 = cyl(60, 15, 4, gp_Dir(0, 0, 1), 1.5, 36.0)
    body = BRepAlgoAPI_Cut(body, hole1).Shape()

    # Non-standard hole: d=7.3.
    hole2 = cyl(60, 40, 20, gp_Dir(0, 0, 1), 3.65, 20.0)
    body = BRepAlgoAPI_Cut(body, hole2).Shape()

    # Side hole (forces a second setup): d=8 from +X face.
    hole3 = cyl(80, 30, 20, gp_Dir(-1, 0, 0), 4.0, 25.0)
    body = BRepAlgoAPI_Cut(body, hole3).Shape()

    return body


def make_good_plate() -> TopoDS_Shape:
    """Simple, friendly part: plate with generous pocket and standard holes."""
    body = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 100.0, 60.0, 15.0).Shape()

    pocket = BRepPrimAPI_MakeBox(gp_Pnt(15, 15, 5), 40.0, 30.0, 11.0).Shape()
    pocket = fillet_vertical_edges(pocket, 6.0)
    body = BRepAlgoAPI_Cut(body, pocket).Shape()

    for x, y in [(75, 15), (75, 45), (90, 30)]:
        body = BRepAlgoAPI_Cut(body, cyl(x, y, -1, gp_Dir(0, 0, 1), 3.0, 17.0)).Shape()

    return body


def make_fiddly_widget() -> TopoDS_Shape:
    """90x50x20 block packed with small-feature DFM problems:

    - pocket with r=0.5 corner fillets (micro-tool corner radius, critical)
    - pocket with r=1.2 corner fillets (micro-tool corner radius, warning)
    - square-cut pocket (zero-radius corners — unmillable)
    - 1.0 mm and 2.0 mm wide slots (narrow channels)
    - Ø0.6 and Ø1.2 micro holes
    Everything cut from the top so setups/accessibility stay clean.
    """
    body = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 90.0, 50.0, 20.0).Shape()

    # Pocket A: tiny r=0.5 corners, 6 deep.
    pa = BRepPrimAPI_MakeBox(gp_Pnt(8, 8, 14), 20.0, 14.0, 7.0).Shape()
    body = BRepAlgoAPI_Cut(body, fillet_vertical_edges(pa, 0.5)).Shape()

    # Pocket B: small r=1.2 corners, 5 deep.
    pb = BRepPrimAPI_MakeBox(gp_Pnt(35, 8, 15), 20.0, 14.0, 6.0).Shape()
    body = BRepAlgoAPI_Cut(body, fillet_vertical_edges(pb, 1.2)).Shape()

    # Pocket C: square corners (r=0), 6 deep — unmillable as drawn.
    pc = BRepPrimAPI_MakeBox(gp_Pnt(62, 8, 14), 20.0, 14.0, 7.0).Shape()
    body = BRepAlgoAPI_Cut(body, pc).Shape()

    # Slot 1: 1.0 mm wide, 6 deep (extreme narrow channel).
    s1 = BRepPrimAPI_MakeBox(gp_Pnt(8, 30, 14), 30.0, 1.0, 7.0).Shape()
    body = BRepAlgoAPI_Cut(body, s1).Shape()

    # Slot 2: 2.0 mm wide, 6 deep (narrow channel).
    s2 = BRepPrimAPI_MakeBox(gp_Pnt(8, 40, 14), 30.0, 2.0, 7.0).Shape()
    body = BRepAlgoAPI_Cut(body, s2).Shape()

    # Micro holes: Ø0.6 x 3 deep, Ø1.2 x 4 deep.
    body = BRepAlgoAPI_Cut(body, cyl(55, 35, 17, gp_Dir(0, 0, 1), 0.3, 4.0)).Shape()
    body = BRepAlgoAPI_Cut(body, cyl(65, 35, 16, gp_Dir(0, 0, 1), 0.6, 5.0)).Shape()

    # One friendly standard hole for contrast.
    body = BRepAlgoAPI_Cut(body, cyl(78, 35, -1, gp_Dir(0, 0, 1), 3.0, 22.0)).Shape()

    return body


def make_open_box() -> TopoDS_Shape:
    """Box with the top face deleted and the rest sewn into an open shell —
    simulates an unstitched / surface-only export."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.GeomAbs import GeomAbs_Plane

    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 50.0, 40.0, 30.0).Shape()
    sew = BRepBuilderAPI_Sewing()
    fexp = TopExp_Explorer(box, TopAbs_FACE)
    while fexp.More():
        face = TopoDS.Face_s(fexp.Current())
        surf = BRepAdaptor_Surface(face)
        # Skip the +Z (top) face.
        is_top = (
            surf.GetType() == GeomAbs_Plane
            and abs(surf.Plane().Axis().Direction().Z()) > 0.99
            and surf.Plane().Location().Z() > 15.0
        )
        if not is_top:
            sew.Add(face)
        fexp.Next()
    sew.Perform()
    return sew.SewedShape()


def make_two_bodies() -> TopoDS_Shape:
    """Two disconnected solids in one file — an accidental 'assembly' export."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    builder.Add(comp, BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40.0, 30.0, 20.0).Shape())
    builder.Add(comp, BRepPrimAPI_MakeBox(gp_Pnt(60, 0, 0), 25.0, 25.0, 25.0).Shape())
    return comp


if __name__ == "__main__":
    write_step(make_bad_bracket(), "bad_bracket.step")
    write_step(make_good_plate(), "good_plate.step")
    write_step(make_fiddly_widget(), "fiddly_widget.step")
    write_step(make_open_box(), "open_box.step")
    write_step(make_two_bodies(), "two_bodies.step")
