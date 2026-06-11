"""DFM rules: consume detected features, emit findings with rich suggestions.

Every finding aims to read like feedback from an experienced machinist:
what the problem is, why the physics of milling makes it expensive, what it
does to the quote, and concrete redesign options with numbers.
"""

from __future__ import annotations

import math

import numpy as np

from dfm.features import (
    AccessibilityResult,
    Hole,
    InternalCorner,
    NarrowGap,
    SharpConcaveEdge,
    ThinRegion,
)
from dfm.model import FaceInfo, Finding, Severity, SurfaceKind

# Common metric drill sizes (mm). Anything close to one of these is "standard".
STANDARD_DRILLS_MM = [
    1.0, 1.5, 2.0, 2.5, 3.0, 3.2, 3.3, 3.5, 4.0, 4.2, 4.5, 5.0, 5.5,
    6.0, 6.5, 6.8, 7.0, 7.5, 8.0, 8.5, 9.0, 10.0, 10.2, 11.0, 12.0,
    13.0, 14.0, 16.0, 18.0, 20.0, 25.0,
]

DIR_NAMES = ["+Z (top)", "-Z (bottom)", "+X (right)", "-X (left)", "+Y (back)", "-Y (front)"]

MIN_WALL_METAL = 0.8   # mm — below this, walls fail during machining
WARN_WALL_METAL = 1.5  # mm — below this, walls need babying

MICRO_HOLE_WARN = 1.5  # mm — below this, micro drilling territory
MICRO_HOLE_CRIT = 0.8

TINY_RADIUS_WARN = 1.6  # mm — corner needs a ≤ Ø3.2 mm end mill
TINY_RADIUS_CRIT = 0.6  # mm — corner needs a ≤ Ø1.2 mm end mill

NARROW_GAP_CRIT = 1.2  # mm


# ---------------------------------------------------------------------------
# Internal corners
# ---------------------------------------------------------------------------

def check_internal_corners(corners: list[InternalCorner]) -> list[Finding]:
    findings = []

    # Group identical corners (same radius/depth bucket) into one finding.
    groups: dict[tuple[float, float, str], list[InternalCorner]] = {}
    for c in corners:
        if c.radius <= 0.05:
            continue  # zero-radius corners are caught by the edge-based check
        ld = c.depth / (2.0 * c.radius)
        if ld > 6.0:
            kind = "deep"
        elif c.radius < TINY_RADIUS_WARN:
            kind = "tiny"
        else:
            continue
        groups.setdefault((round(c.radius, 1), round(c.depth, 0), kind), []).append(c)

    for (radius, depth, kind), grp in groups.items():
        n = len(grp)
        faces = [c.face_index for c in grp]
        count_note = f" ({n} corners like this)" if n > 1 else ""

        if kind == "deep":
            ld = depth / (2.0 * radius)
            sev = Severity.CRITICAL if ld > 10 else Severity.WARNING
            findings.append(Finding(
                rule="deep_small_corner_radius",
                title="Corner radius too small for pocket depth",
                severity=sev,
                detail=(
                    f"Internal corner radius of {radius:.1f} mm at {depth:.0f} mm depth"
                    f"{count_note}. The largest tool that fits this corner is Ø{2 * radius:.1f} mm, "
                    f"and it must hang {depth:.0f} mm out of the holder — a {ld:.0f}:1 "
                    "length-to-diameter ratio. Tool deflection grows with the cube of stickout: "
                    "at this ratio the tool flexes like a fishing rod, so the machinist must "
                    "take whisper-light cuts at reduced feed, multiplying cycle time. Beyond "
                    "~8:1, chatter ruins the surface finish; beyond ~12:1, tools snap. Expect "
                    "this single corner to dominate the machining cost of the whole pocket"
                    + (" — or to be rejected as unmachinable." if ld > 10 else ".")
                ),
                suggestion=(
                    f"Increase the corner radius to at least {depth / 4.0:.1f} mm (radius ≥ depth/4). "
                    "Two refinements machinists will thank you for: (1) make the corner radius "
                    "slightly LARGER than a standard tool radius — e.g. 4.2 mm corners for a "
                    "Ø8 mm tool — so the tool arcs smoothly through the corner instead of "
                    "dwelling and chattering; (2) if you can't enlarge the radius, reduce the "
                    "pocket depth, or split the pocket into a deep section with big corners "
                    "and a shallow section with the tight ones."
                ),
                action=f"Enlarge {n} pocket corner radi{'i' if n > 1 else 'us'} "
                       f"from {radius:.1f} mm to ≥ {depth / 4.0:.1f} mm (or make the pocket shallower)",
                face_indices=faces,
                penalty=min(6.0 + ld, 20.0) + 1.5 * (n - 1),
                data={"radius_mm": radius, "depth_mm": depth,
                      "tool_l_over_d": round(ld, 1), "count": n},
            ))

        else:  # tiny radius, shallow but still micro-tool territory
            sev = Severity.CRITICAL if radius < TINY_RADIUS_CRIT else Severity.WARNING
            findings.append(Finding(
                rule="tiny_corner_radius",
                title="Very small corner radius (micro tooling)",
                severity=sev,
                detail=(
                    f"Internal corner radius of {radius:.1f} mm{count_note} requires an end mill "
                    f"of Ø{2 * radius:.1f} mm or smaller. Tools under Ø3 mm are disproportionately "
                    "expensive to run: they break if a chip recuts, they can't take meaningful "
                    "depth of cut (think 0.1 mm passes), and many shops surcharge or decline "
                    "micro-milling work. A corner that takes one pass with a Ø10 mm tool takes "
                    "dozens of passes with a Ø1 mm tool"
                    + (" — and below Ø1.2 mm many job shops simply won't quote it." if radius < TINY_RADIUS_CRIT else ".")
                ),
                suggestion=(
                    "Open the corner radius to ≥ 2 mm wherever the mating part allows — going "
                    f"from {radius:.1f} mm to 2 mm can cut the corner machining time by an order "
                    "of magnitude. If a small slot/corner is functionally required (e.g. for a "
                    "retaining ring or seal), confine the tiny radius to the smallest possible "
                    "depth and give the rest of the feature a generous radius."
                ),
                action=f"Open {n} corner radi{'i' if n > 1 else 'us'} from "
                       f"{radius:.1f} mm to ≥ 2 mm",
                face_indices=faces,
                penalty=(10.0 if radius < TINY_RADIUS_CRIT else 5.0) + 1.0 * (n - 1),
                data={"radius_mm": radius, "depth_mm": depth, "count": n},
            ))
    return findings


def check_sharp_edges(edges: list[SharpConcaveEdge]) -> list[Finding]:
    """Zero-radius internal corners found by exact edge analysis."""
    if not edges:
        return []
    # Bucket by depth so one finding covers e.g. "the 4 corners of this pocket".
    groups: dict[float, list[SharpConcaveEdge]] = {}
    for e in edges:
        groups.setdefault(round(e.length, 0), []).append(e)

    findings = []
    for depth, grp in groups.items():
        n = len(grp)
        faces = sorted({fi for e in grp for fi in e.face_indices})
        count_note = f" ({n} corner edges like this)" if n > 1 else ""
        findings.append(Finding(
            rule="sharp_internal_corner",
            title="Sharp internal corner — not millable as drawn",
            severity=Severity.CRITICAL,
            detail=(
                f"Square (zero-radius) internal corner running {depth:.0f} mm deep"
                f"{count_note}. An end mill is a rotating cylinder — it physically cannot "
                "leave a sharp inside corner parallel to its own axis; the smallest corner "
                "it can produce equals the tool's radius. No orientation a 3-axis machine "
                "can reach lets a tool form these corners, so as drawn this feature cannot "
                "be milled at all. Producing it would mean wire/sinker EDM or broaching — "
                "typically 5–10x the cost of the milled feature plus days of lead time. "
                "This is the single most common error in parts designed without "
                "machining in mind: CAD makes square pockets effortless, machines don't."
            ),
            suggestion=(
                f"Pick one: (1) Add a corner radius — at {depth:.0f} mm deep, use at least "
                f"{max(depth / 4.0, 1.0):.1f} mm (radius ≥ depth/4) so a rigid tool fits. "
                "(2) If a square mating part must seat in this pocket, keep the radii and "
                "add 'dog-bone' reliefs: small drilled overcuts at each corner that give "
                "the mating part's sharp corners clearance (see drawing). (3) If the "
                "square corner only exists because the CAD sketch had square corners, "
                "fillet it and nobody will ever notice."
            ),
            action=f"Add ≥ {max(depth / 4.0, 1.0):.1f} mm radii to {n} square "
                   f"pocket corner{'s' if n > 1 else ''} (or dog-bone reliefs)",
            face_indices=faces,
            penalty=18.0 + 2.0 * (n - 1),
            data={"depth_mm": depth, "count": n},
        ))
    return findings


# ---------------------------------------------------------------------------
# Holes
# ---------------------------------------------------------------------------

def check_holes(holes: list[Hole]) -> list[Finding]:
    findings = []
    for h in holes:
        dia = 2.0 * h.radius
        ratio = h.depth / dia if dia > 1e-9 else 0.0
        kind = "through hole" if h.through else "blind hole"

        if dia < MICRO_HOLE_WARN:
            sev = Severity.CRITICAL if dia < MICRO_HOLE_CRIT else Severity.WARNING
            findings.append(Finding(
                rule="micro_hole",
                title=f"Micro hole (Ø{dia:.2f} mm)",
                severity=sev,
                detail=(
                    f"This Ø{dia:.2f} mm {kind} is in micro-drilling territory. Drills this "
                    "small wander on entry, snap from chip packing, and need peck cycles "
                    "with retract heights measured in tenths of a millimeter. Many shops "
                    "don't stock tooling below Ø1 mm, and broken-drill removal can scrap "
                    f"the whole part. At {ratio:.1f}:1 depth-to-diameter the risk compounds — "
                    "every extra diameter of depth roughly doubles the chance of a snapped "
                    "drill."
                    + (" Below Ø0.8 mm expect 'no-quote' responses from most job shops."
                       if dia < MICRO_HOLE_CRIT else "")
                ),
                suggestion=(
                    "Enlarge the hole to Ø1.5 mm or more if at all possible — that's where "
                    "standard drilling resumes. If the small bore is functional (dowel, vent, "
                    "nozzle), consider: (1) drilling the small diameter only partway and "
                    "opening the rest to a larger diameter (stepped hole); (2) specifying the "
                    "hole only in a thin region of the part; (3) moving the feature to a "
                    "post-process like laser drilling or EDM and noting that on the drawing."
                ),
                action=f"Enlarge the Ø{dia:.2f} mm hole to ≥ Ø1.5 mm "
                       "(or move it to a laser/EDM post-process)",
                face_indices=h.face_indices,
                penalty=(12.0 if dia < MICRO_HOLE_CRIT else 6.0),
                data={"diameter_mm": round(dia, 2), "depth_mm": round(h.depth, 2)},
            ))

        if ratio > 4.0:
            sev = Severity.CRITICAL if ratio > 10 else Severity.WARNING
            findings.append(Finding(
                rule="deep_hole",
                title=f"Deep hole — {ratio:.1f}:1 depth-to-diameter",
                severity=sev,
                detail=(
                    f"This Ø{dia:.2f} mm {kind} is {h.depth:.1f} mm deep ({ratio:.1f}:1). "
                    "Past ~4:1, chips stop evacuating on their own: the machinist must peck "
                    "(drill a little, fully retract, repeat), which multiplies cycle time "
                    "roughly linearly with depth. Past ~7:1 the drill needs interrupted "
                    "pecking and through-tool coolant; past ~10:1 you're into specialty "
                    "gun-drilling, a separate operation on different equipment that many "
                    "milling shops outsource. Straightness also suffers — expect the bore to "
                    "wander roughly 0.1 mm per 25 mm of depth in the best case."
                ),
                suggestion=(
                    "Options, best first: (1) Shorten the hole — if it's for a fastener, a "
                    "counterbore lets a standard-length screw do the job with a much "
                    "shallower tapped section. (2) Enlarge the diameter to bring the ratio "
                    "under 4:1. (3) For a through hole, drill from both sides — two 5:1 holes "
                    "are far cheaper than one 10:1 hole (allow a small mismatch tolerance at "
                    "the meeting point). (4) If a long small bore is truly required, note "
                    "'gun drill OK' on the drawing so shops can quote it sensibly."
                ),
                action=f"Shorten or counterbore the Ø{dia:.2f} × {h.depth:.0f} mm hole "
                       + ("(or drill from both sides)" if h.through else f"(target ≤ {4 * dia:.0f} mm deep)"),
                face_indices=h.face_indices,
                penalty=min(4.0 + 1.5 * ratio, 18.0),
                data={"diameter_mm": round(dia, 2), "depth_mm": round(h.depth, 2),
                      "depth_to_dia": round(ratio, 1)},
            ))

        nearest = min(STANDARD_DRILLS_MM, key=lambda s: abs(s - dia))
        if abs(nearest - dia) > 0.05 and dia < 26.0:
            findings.append(Finding(
                rule="nonstandard_hole_diameter",
                title=f"Non-standard hole diameter (Ø{dia:.2f} mm)",
                severity=Severity.INFO,
                detail=(
                    f"Ø{dia:.2f} mm doesn't match any standard metric drill size. A drilled "
                    "hole is one plunge; a non-standard diameter means the shop must either "
                    "helically mill the bore with an end mill (slower, leaves visible tool "
                    f"marks) or drill at Ø{nearest:.1f} mm and then bore/ream to size — an "
                    "extra operation and an extra tool. On a one-off part this adds a few "
                    "minutes; across a production run it adds up to real money."
                ),
                suggestion=(
                    f"If the diameter isn't functionally critical, change it to Ø{nearest:.1f} mm "
                    "(nearest standard drill). If it mates with a pin or bearing, check whether "
                    "a standard reamer size (H7 fits: 3, 4, 5, 6, 8, 10, 12 mm...) works — "
                    "reamed standard sizes are cheap and precise. Keep truly custom diameters "
                    "only where the design genuinely needs them."
                ),
                action=f"Change Ø{dia:.2f} mm to Ø{nearest:.1f} mm (standard drill size)",
                face_indices=h.face_indices,
                penalty=2.0,
                data={"diameter_mm": round(dia, 2), "nearest_standard_mm": nearest},
            ))

        if h.flat_bottom and not h.through:
            findings.append(Finding(
                rule="flat_bottom_hole",
                title=f"Flat-bottomed blind hole (Ø{dia:.2f} mm)",
                severity=Severity.WARNING,
                detail=(
                    f"This blind Ø{dia:.2f} mm hole has a dead-flat floor. A twist drill "
                    "naturally leaves a 118° or 135° cone at the bottom of every hole — "
                    "producing a flat floor means following the drill with a flat end mill "
                    "plunge (a second tool and operation), and end mills hate plunging: "
                    "they cut poorly straight down, so this is slow and hard on tooling. "
                    "Flat-bottom requirements on small or deep holes are a frequent and "
                    "avoidable cost driver."
                ),
                suggestion=(
                    "If the floor shape doesn't matter (clearance holes, weight reduction, "
                    "blind fastener holes), allow the natural drill point — add 'drill point "
                    "permissible' to the drawing or simply model the 118° cone. If something "
                    "must seat on a flat floor (spring, dowel, bearing), keep the flat but "
                    "make the hole as shallow as the function allows, and add a small corner "
                    "relief groove so the seat doesn't fight the corner radius of the end mill."
                ),
                action=f"Allow a 118° drill-point bottom on the Ø{dia:.2f} mm blind hole",
                face_indices=h.face_indices,
                penalty=3.0,
                data={"diameter_mm": round(dia, 2)},
            ))
    return findings


# ---------------------------------------------------------------------------
# Thin walls / narrow channels
# ---------------------------------------------------------------------------

def check_thin_regions(thin: list[ThinRegion], material_factor: float = 1.0) -> list[Finding]:
    findings = []
    min_t = MIN_WALL_METAL * material_factor
    warn_t = WARN_WALL_METAL * material_factor

    critical = [t for t in thin if t.thickness < min_t]
    warning = [t for t in thin if min_t <= t.thickness < warn_t]

    if critical:
        tmin = min(t.thickness for t in critical)
        findings.append(Finding(
            rule="thin_wall",
            title=f"Critically thin wall / floor ({tmin:.2f} mm)",
            severity=Severity.CRITICAL,
            detail=(
                f"Wall or floor sections as thin as {tmin:.2f} mm were measured at "
                f"{len(critical)} location(s). Below ~0.8 mm in metal, the material can no "
                "longer resist cutting forces: the wall deflects away from the tool, "
                "springs back, and chatters — leaving a wavy, out-of-tolerance surface — "
                "or simply tears off. Thin floors drum like a cymbal and crack. Even if "
                "one careful part survives, the scrap rate makes shops quote defensively "
                "or decline. Heat distortion during machining adds another failure mode."
            ),
            suggestion=(
                f"Thicken these sections to at least {warn_t:.1f} mm (aluminum/steel; use "
                "≥ 1.5 mm for plastics which deflect far more). If the design needs "
                "lightness: (1) add ribs or gussets perpendicular to the thin wall to "
                "stiffen it; (2) shorten the unsupported height — a 1 mm wall that's only "
                "3 mm tall is fine, the same wall 20 mm tall is not; (3) consider whether "
                "the pocket creating the thin wall can be made shallower or moved."
            ),
            action=f"Thicken {len(critical)} wall/floor region{'s' if len(critical) > 1 else ''} "
                   f"from {tmin:.1f} mm to ≥ {warn_t:.1f} mm (or add ribs)",
            face_indices=sorted({t.face_index for t in critical}),
            penalty=14.0 + 2.0 * (len(critical) - 1),
            data={"min_thickness_mm": round(tmin, 2), "count": len(critical)},
        ))
    if warning:
        tmin = min(t.thickness for t in warning)
        findings.append(Finding(
            rule="thin_wall",
            title=f"Thin wall / floor ({tmin:.2f} mm)",
            severity=Severity.WARNING,
            detail=(
                f"Wall or floor sections as thin as {tmin:.2f} mm were measured at "
                f"{len(warning)} location(s). This is machinable, but the machinist must "
                "leave the thin region for last, take spring passes (repeat finishing cuts "
                "to let the deflected wall return), and possibly support it with wax or "
                "backing material. Figure 2–3x normal machining time for these areas, plus "
                "a tolerance risk: thin walls move after the part is unclamped as internal "
                "stresses release."
            ),
            suggestion=(
                f"Thicken to ≥ {warn_t:.1f} mm where the design allows — even 0.3 mm more "
                "makes a measurable difference since stiffness scales with thickness cubed. "
                "Where it doesn't, keep the thin wall's height-to-thickness ratio under "
                "~10:1 and avoid putting tight tolerances or fine finishes on it."
            ),
            action=f"Thicken {len(warning)} wall/floor region{'s' if len(warning) > 1 else ''} "
                   f"to ≥ {warn_t:.1f} mm where possible",
            face_indices=sorted({t.face_index for t in warning}),
            penalty=6.0 + 1.0 * (len(warning) - 1),
            data={"min_thickness_mm": round(tmin, 2), "count": len(warning)},
        ))
    return findings


def check_narrow_gaps(gaps: list[NarrowGap]) -> list[Finding]:
    if not gaps:
        return []
    findings = []
    critical = [g for g in gaps if g.width < NARROW_GAP_CRIT]
    warning = [g for g in gaps if g.width >= NARROW_GAP_CRIT]

    if critical:
        wmin = min(g.width for g in critical)
        findings.append(Finding(
            rule="narrow_channel",
            title=f"Extremely narrow slot / channel ({wmin:.2f} mm)",
            severity=Severity.CRITICAL,
            detail=(
                f"Opposing walls are only {wmin:.2f} mm apart at {len(critical)} "
                "location(s). The widest tool that fits is under Ø1.2 mm — and a slot "
                "milled with a tool that exactly fits its width cuts with its full "
                "circumference engaged ('slotting'), the harshest condition a tool sees. "
                "Sub-millimeter end mills in full slot engagement break constantly. "
                "Channels this tight usually mean wire EDM or a redesign; most milling "
                "shops will not quote them as drawn."
            ),
            suggestion=(
                "Open the channel to at least 2 mm, ideally 3 mm — slot width should be "
                "≥ 1.5x the tool diameter so the tool can take side cuts rather than full "
                "slots. If the narrow gap exists to create a flexure or spring feature, "
                "note that wire EDM is the standard process for those and design the part "
                "so the EDM path can run straight through. If it's a clearance gap for "
                "another part, check whether the mating part can be relieved instead."
            ),
            action=f"Widen the {wmin:.1f} mm slot to ≥ 3 mm (or design for wire EDM)",
            face_indices=sorted({g.face_index for g in critical}),
            penalty=15.0 + 1.5 * (len(critical) - 1),
            data={"min_width_mm": round(wmin, 2), "count": len(critical)},
        ))
    if warning:
        wmin = min(g.width for g in warning)
        findings.append(Finding(
            rule="narrow_channel",
            title=f"Narrow slot / channel ({wmin:.2f} mm)",
            severity=Severity.WARNING,
            detail=(
                f"Opposing walls are {wmin:.2f} mm apart at {len(warning)} location(s). "
                "Cutting this requires an end mill of roughly Ø2 mm or smaller running in "
                "full slot engagement — fragile, slow (tiny depth per pass), and prone to "
                "tapering as the tool deflects. The deeper the channel relative to its "
                "width, the worse: past ~5:1 depth-to-width expect chatter marks on the "
                "walls and a surcharge on the quote."
            ),
            suggestion=(
                "Widen the channel to ≥ 3 mm if function allows — a Ø3 mm tool with side "
                "engagement cuts an order of magnitude faster than a Ø2 mm tool slotting. "
                "Keep channel depth under ~4x its width. If the channel routes a seal or "
                "o-ring, standard groove widths start around 2.4 mm — use catalog "
                "dimensions so shops can use standard groove tooling."
            ),
            action=f"Widen the {wmin:.1f} mm slot to ≥ 3 mm",
            face_indices=sorted({g.face_index for g in warning}),
            penalty=7.0 + 1.0 * (len(warning) - 1),
            data={"min_width_mm": round(wmin, 2), "count": len(warning)},
        ))
    return findings


# ---------------------------------------------------------------------------
# Accessibility / setups / freeform
# ---------------------------------------------------------------------------

def check_accessibility(access: AccessibilityResult, infos: list[FaceInfo]) -> list[Finding]:
    findings = []
    n_setups = len(access.chosen_setups)

    if access.unreachable_faces:
        findings.append(Finding(
            rule="unreachable_faces",
            title="Undercut features — unreachable on a 3-axis mill",
            severity=Severity.CRITICAL,
            detail=(
                f"{len(access.unreachable_faces)} face(s) cannot be reached by a tool "
                "approaching from any of the six box directions. These are undercuts: "
                "surfaces hidden behind other material, like T-slots, dovetails, "
                "side grooves inside pockets, or internal cavities. A standard end mill "
                "cuts only what it can 'see' from above. Undercuts force special cutters "
                "(T-slot, lollipop, dovetail cutters — each limited to specific geometry), "
                "5-axis machining, EDM, or splitting the part — all of which multiply cost."
            ),
            suggestion=(
                "Re-examine each highlighted face: (1) Can the feature be opened up so "
                "it's visible from one tool direction? (2) Can the part be split into two "
                "simpler parts that bolt or press together, each fully accessible? "
                "(3) If the undercut holds a seal or retaining ring, standard lollipop/"
                "T-slot cutters can often manage it — keep the groove profile to catalog "
                "cutter dimensions and note the cutter type on the drawing. (4) For "
                "internal cavities with no tool access at all, the part must be redesigned "
                "or made additively."
            ),
            action="Eliminate undercuts — open the hidden features to a tool "
                   "direction, or split into a two-piece assembly",
            face_indices=access.unreachable_faces,
            penalty=20.0,
            data={"count": len(access.unreachable_faces)},
        ))

    if n_setups >= 3:
        sev = Severity.WARNING if n_setups == 3 else Severity.CRITICAL
        names = [DIR_NAMES[d] for d in access.chosen_setups]
        findings.append(Finding(
            rule="many_setups",
            title=f"Requires ~{n_setups} machining setups",
            severity=sev,
            detail=(
                f"Machining this part requires tool access from {len(names)} directions "
                f"({', '.join(names)}). Each direction beyond the second means unclamping "
                "the part, re-fixturing it, re-indicating it (finding its exact position "
                "again), and re-running — typically 15–45 minutes of skilled labor per "
                "setup before a single chip is cut. Worse, every re-clamp stacks up "
                "positional error: features cut in different setups can drift 0.05–0.1 mm "
                "relative to each other, so tolerances across setup boundaries get "
                "expensive fast. Setup count is one of the biggest levers on a CNC quote."
            ),
            suggestion=(
                "Consolidate features onto fewer sides of the part. Common wins: "
                "(1) move side-entry holes to the top face, or convert them to through "
                "holes from above; (2) replace side pockets with through-cut features; "
                "(3) if two opposite faces both need work, design critical relationships "
                "to live within ONE setup and put only non-critical features on the flip "
                "side; (4) add a sacrificial fixturing tab or flange if it lets multiple "
                "faces be cut in one clamping."
            ),
            action=f"Consolidate features onto fewer sides (currently needs "
                   f"{n_setups} setups: {', '.join(names)})",
            penalty=6.0 * (n_setups - 2),
            data={"setups": n_setups, "directions": names},
        ))
    return findings


def check_freeform(infos: list[FaceInfo]) -> list[Finding]:
    total = sum(i.area for i in infos)
    ff = [i for i in infos if i.kind == SurfaceKind.FREEFORM]
    ff_area = sum(i.area for i in ff)
    if total <= 0 or not ff:
        return []
    frac = ff_area / total
    if frac < 0.02:
        return []
    sev = Severity.WARNING if frac < 0.25 else Severity.CRITICAL
    return [Finding(
        rule="freeform_surfaces",
        title=f"Sculpted surfaces ({frac * 100:.0f}% of part area)",
        severity=sev,
        detail=(
            f"{frac * 100:.0f}% of this part's surface is freeform (NURBS) geometry. "
            "Flat and cylindrical surfaces are cut in single sweeping passes; sculpted "
            "surfaces must be 3D-contoured with a ball-nose end mill tracing thousands "
            "of stepover passes — cycle time scales with surface area divided by "
            "stepover width, and a fine finish needs stepovers of 0.1–0.3 mm. A surface "
            "that takes 2 minutes as a flat face can take 2 hours sculpted. Complex "
            "curvature may also demand 5-axis work or multiple ball-nose sizes to reach "
            "concave details."
        ),
        suggestion=(
            "Audit every sculpted surface and ask what it's for: (1) If it's cosmetic "
            "styling on a functional part, replace it with planar, cylindrical, or "
            "ruled geometry — or move the styling to a cast/molded cover part. "
            "(2) If it's an ergonomic or aerodynamic surface that must stay, specify "
            "the loosest acceptable surface finish (e.g. 3.2 Ra instead of 0.8 Ra) — "
            "finish requirements drive ball-nose stepover and thus hours. (3) Large "
            "convex surfaces machine much faster than concave ones; avoid small concave "
            "radii inside sculpted regions since they force tiny ball-nose tools."
        ),
        action="Replace sculpted surfaces with planar/cylindrical geometry "
               "(or relax their surface-finish requirement)",
        face_indices=[i.index for i in ff],
        penalty=min(5.0 + 40.0 * frac, 25.0),
        data={"freeform_area_pct": round(frac * 100, 1)},
    )]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all_rules(
    corners: list[InternalCorner],
    holes: list[Hole],
    thin: list[ThinRegion],
    access: AccessibilityResult,
    infos: list[FaceInfo],
    integrity_findings: list[Finding] | None = None,
    narrow_gaps: list[NarrowGap] | None = None,
    sharp_edges: list[SharpConcaveEdge] | None = None,
) -> list[Finding]:
    findings: list[Finding] = list(integrity_findings or [])
    findings += check_sharp_edges(sharp_edges or [])
    findings += check_internal_corners(corners)
    findings += check_holes(holes)
    findings += check_thin_regions(thin)
    findings += check_narrow_gaps(narrow_gaps or [])
    findings += check_accessibility(access, infos)
    findings += check_freeform(infos)
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    findings.sort(key=lambda f: (order[f.severity], -f.penalty))
    return findings
