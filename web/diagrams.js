// Per-rule illustrative drawings: "as drawn" (red) vs "machinable" (green).
// All diagrams share a 340x150 viewBox: bad panel ~x0-155, good panel ~x185-340.

const C = {
  mat: "#232b3a",      // material fill
  line: "#8a93a6",     // outlines
  bad: "#f0506e",
  good: "#3fb27f",
  tool: "#4f8ef7",
  text: "#9aa4b2",
};

const FONT = `font-family="Inter,system-ui,sans-serif" font-size="9.5" fill="${C.text}"`;

function frame(badLabel, goodLabel, inner) {
  return `<svg viewBox="0 0 340 150" xmlns="http://www.w3.org/2000/svg">
    ${inner}
    <text x="77" y="146" text-anchor="middle" ${FONT}>${badLabel}</text>
    <text x="262" y="146" text-anchor="middle" ${FONT}>${goodLabel}</text>
    <text x="14" y="16" font-size="13" font-weight="700" fill="${C.bad}" font-family="Inter,sans-serif">✕</text>
    <text x="196" y="16" font-size="13" font-weight="700" fill="${C.good}" font-family="Inter,sans-serif">✓</text>
    <path d="M163 75 h12 m-4 -4 l4 4 l-4 4" stroke="${C.text}" stroke-width="1.4" fill="none"/>
  </svg>`;
}

const toolCircle = (cx, cy, r, color = C.tool) =>
  `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="1.3" stroke-dasharray="3 2.5"/>
   <circle cx="${cx}" cy="${cy}" r="1.6" fill="${color}"/>`;

export const DIAGRAMS = {
  // -------------------------------------------------------------- corners --
  sharp_internal_corner: {
    caption:
      "Top view of a pocket. A rotating end mill always leaves its own radius (blue). " +
      "Either accept a corner radius, or add drilled dog-bone reliefs if a square part must seat.",
    svg: frame("square corner — tool can't reach", "filleted corners or dog-bone relief", `
      <!-- bad: square pocket, tool circle leaves material in corner -->
      <rect x="22" y="28" width="110" height="84" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="40" y="44" width="74" height="52" fill="#0d1117" stroke="${C.line}" stroke-width="1.3"/>
      ${toolCircle(56, 60, 13)}
      <path d="M40 44 l9 0 m-9 0 l0 9" stroke="${C.bad}" stroke-width="2.4"/>
      <path d="M114 44 l-9 0 m9 0 l0 9" stroke="${C.bad}" stroke-width="2.4"/>
      <path d="M40 96 l9 0 m-9 0 l0 -9" stroke="${C.bad}" stroke-width="2.4"/>
      <path d="M114 96 l-9 0 m9 0 l0 -9" stroke="${C.bad}" stroke-width="2.4"/>

      <!-- good: rounded pocket + dogbone detail -->
      <rect x="200" y="28" width="110" height="84" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="216" y="44" width="58" height="52" rx="12" fill="#0d1117" stroke="${C.good}" stroke-width="1.4"/>
      ${toolCircle(230, 58, 10, C.good)}
      <!-- dogbone variant, right side -->
      <rect x="285" y="52" width="20" height="36" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="285" cy="52" r="4.5" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="305" cy="52" r="4.5" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="285" cy="88" r="4.5" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="305" cy="88" r="4.5" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <text x="295" y="116" text-anchor="middle" ${FONT}>dog-bone</text>
      <text x="245" y="116" text-anchor="middle" ${FONT}>r ≥ depth/4</text>
    `),
  },

  deep_small_corner_radius: {
    caption:
      "Side view. The corner radius sets the tool diameter; the pocket depth sets its stickout. " +
      "Small radius + deep pocket = a long skinny tool that deflects and chatters.",
    svg: frame("Ø small, hanging far out — deflects", "bigger radius — short rigid tool", `
      <!-- bad: deep pocket, skinny long tool, bend -->
      <path d="M14 40 h28 v76 h56 v-76 h28 v92 h-112 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="62" y="18" width="12" height="22" fill="${C.tool}" rx="1"/>
      <path d="M68 40 q-1 30 -7 54" stroke="${C.bad}" stroke-width="5" fill="none" stroke-linecap="round"/>
      <path d="M82 52 q8 6 0 14" stroke="${C.bad}" stroke-width="1.2" fill="none"/>
      <path d="M86 70 l-3 -4 m3 4 l-4 1" stroke="${C.bad}" stroke-width="1.2" fill="none"/>
      <text x="95" y="60" ${FONT}>deflection</text>

      <!-- good: shallower engagement, fat tool -->
      <path d="M192 40 h28 v50 h70 v-50 h28 v92 h-126 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="240" y="14" width="26" height="30" fill="${C.tool}" rx="1"/>
      <rect x="240" y="44" width="26" height="44" fill="${C.good}" rx="2"/>
      <text x="296" y="36" ${FONT}>stiff: Ø ≥ depth/2</text>
    `),
  },

  tiny_corner_radius: {
    caption:
      "The largest tool that fits a corner is twice the corner radius. Sub-2 mm corners force " +
      "micro end mills that cut in 0.1 mm sips and snap without warning.",
    svg: frame("r 0.5 mm → Ø1 mm micro tool", "r ≥ 2 mm → standard tooling", `
      <rect x="22" y="30" width="110" height="82" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="42" y="48" width="70" height="46" rx="2.5" fill="#0d1117" stroke="${C.line}"/>
      ${toolCircle(50, 56, 3.2, C.bad)}
      <path d="M55 62 l14 14" stroke="${C.bad}" stroke-width="1.1"/>
      <text x="71" y="84" ${FONT}>Ø1 mm</text>

      <rect x="200" y="30" width="110" height="82" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="220" y="48" width="70" height="46" rx="9" fill="#0d1117" stroke="${C.good}" stroke-width="1.3"/>
      ${toolCircle(232, 60, 9, C.good)}
      <text x="262" y="84" ${FONT}>Ø4 mm+</text>
    `),
  },

  // ---------------------------------------------------------------- holes --
  deep_hole: {
    caption:
      "Cross-section. Past 4:1 depth-to-diameter, chips jam and the drill wanders. " +
      "Counterbore to shorten the small bore, or drill a through hole from both sides.",
    svg: frame("12:1 — pecking, wander, breakage", "counterbore / drill from both sides", `
      <rect x="18" y="32" width="120" height="86" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="72" y="32" width="9" height="74" fill="#0d1117" stroke="${C.bad}" stroke-width="1.2"/>
      <path d="M72 106 l4.5 6 l4.5 -6" fill="#0d1117" stroke="${C.bad}" stroke-width="1.2"/>
      <path d="M60 38 q-8 30 2 60" stroke="${C.bad}" stroke-width="1" fill="none" stroke-dasharray="3 2"/>
      <text x="46" y="106" ${FONT}>wander</text>

      <rect x="196" y="32" width="120" height="86" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <!-- counterbored: wide top, short narrow bottom -->
      <rect x="222" y="32" width="22" height="42" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <rect x="229" y="74" width="8" height="26" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <path d="M229 100 l4 5 l4 -5" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <!-- both sides -->
      <rect x="282" y="32" width="9" height="40" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <rect x="282" y="78" width="9" height="40" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <path d="M275 75 h23" stroke="${C.text}" stroke-width="0.8" stroke-dasharray="2 2"/>
      <text x="234" y="124" ${FONT}>c'bore</text>
      <text x="287" y="124" ${FONT}>2 sides</text>
    `),
  },

  micro_hole: {
    caption:
      "Drills under Ø1.5 mm snap from chip packing and wander on entry. " +
      "If a tiny bore is functional, step-drill: keep the micro section short in a thin region.",
    svg: frame("Ø0.6 mm full depth — snapped drill", "Ø ≥ 1.5 mm, or short micro section", `
      <rect x="18" y="34" width="120" height="80" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="74" y="34" width="3.5" height="40" fill="#0d1117" stroke="${C.bad}" stroke-width="1"/>
      <path d="M76 74 l-5 8 l8 -3 l-6 9" stroke="${C.bad}" stroke-width="1.6" fill="none"/>
      <text x="92" y="86" ${FONT}>snap</text>

      <rect x="196" y="34" width="120" height="80" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="222" y="34" width="11" height="68" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <!-- stepped micro -->
      <rect x="276" y="34" width="14" height="48" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <rect x="281" y="82" width="4" height="16" fill="#0d1117" stroke="${C.good}" stroke-width="1"/>
      <text x="227" y="124" ${FONT}>Ø1.5+</text>
      <text x="284" y="124" ${FONT}>stepped</text>
    `),
  },

  flat_bottom_hole: {
    caption:
      "A twist drill leaves a 118° cone for free. A flat floor needs a second operation with " +
      "an end mill plunging — slow and hard on tools. Allow the drill point if nothing seats there.",
    svg: frame("flat floor — extra end mill op", "118° drill point — one drill cycle", `
      <rect x="18" y="32" width="120" height="84" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="62" y="32" width="30" height="60" fill="#0d1117" stroke="${C.line}" stroke-width="1.2"/>
      <path d="M62 92 h30" stroke="${C.bad}" stroke-width="2.6"/>
      <text x="102" y="98" ${FONT}>+1 op</text>

      <rect x="196" y="32" width="120" height="84" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <rect x="240" y="32" width="30" height="56" fill="#0d1117" stroke="${C.line}" stroke-width="1.2"/>
      <path d="M240 88 l15 14 l15 -14" fill="#0d1117" stroke="${C.good}" stroke-width="1.6"/>
      <text x="284" y="100" ${FONT}>118°</text>
    `),
  },

  nonstandard_hole_diameter: {
    caption:
      "Standard drill diameters are one plunge; odd diameters mean boring, reaming, or helical " +
      "milling — an extra tool and operation for a dimension that often doesn't matter.",
    svg: frame("Ø7.30 — must be milled/reamed", "Ø7.5 — standard drill, one plunge", `
      <circle cx="77" cy="68" r="30" fill="#0d1117" stroke="${C.bad}" stroke-width="1.6"/>
      <text x="77" y="72" text-anchor="middle" font-size="12" fill="${C.bad}" font-family="Inter,sans-serif">Ø7.30</text>
      <path d="M50 110 q27 12 54 0" stroke="${C.bad}" stroke-width="1" fill="none" stroke-dasharray="3 2"/>
      <text x="77" y="128" text-anchor="middle" ${FONT}>helical mill path</text>

      <circle cx="262" cy="68" r="30" fill="#0d1117" stroke="${C.good}" stroke-width="1.6"/>
      <text x="262" y="72" text-anchor="middle" font-size="12" fill="${C.good}" font-family="Inter,sans-serif">Ø7.5</text>
      <text x="262" y="128" text-anchor="middle" ${FONT}>standard drill chart size</text>
    `),
  },

  // ------------------------------------------------------- walls/channels --
  thin_wall: {
    caption:
      "Cross-section. Thin walls deflect away from the cutter, spring back, and chatter; " +
      "stiffness scales with thickness cubed, so even +0.3 mm helps enormously.",
    svg: frame("0.8 mm wall — flexes & chatters", "≥ 1.5 mm, or ribbed for stiffness", `
      <path d="M16 116 v-78 h36 v54 h6 v-54 h2 v54 h6 v-54 h72 v78 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <path d="M60 38 q4 -10 8 0" stroke="${C.bad}" stroke-width="1.3" fill="none"/>
      <path d="M58 32 q6 -14 12 0" stroke="${C.bad}" stroke-width="1" fill="none" stroke-dasharray="2 2"/>
      <text x="92" y="32" ${FONT}>vibration</text>

      <path d="M194 116 v-78 h36 v54 h16 v-54 h74 v78 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <path d="M230 92 h16" stroke="${C.good}" stroke-width="2.2"/>
      <text x="252" y="60" ${FONT}>thicker, shorter,</text>
      <text x="252" y="71" ${FONT}>or gusseted</text>
    `),
  },

  narrow_channel: {
    caption:
      "A slot as wide as its tool forces full-circumference 'slotting' — the harshest cut there is. " +
      "Width ≥ 1.5x tool diameter lets the tool take healthy side cuts instead.",
    svg: frame("1 mm slot — Ø1 tool, full slotting", "≥ 3 mm — room for a real tool", `
      <path d="M16 114 v-76 h50 v58 h4 v-58 h50 v76 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      ${toolCircle(68, 48, 2.5, C.bad)}
      <text x="84" y="52" ${FONT}>Ø = width</text>

      <path d="M194 114 v-76 h44 v58 h28 v-58 h50 v76 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      ${toolCircle(248, 52, 8, C.good)}
      <path d="M258 52 h8" stroke="${C.good}" stroke-width="1"/>
      <text x="284" y="56" ${FONT}>clearance</text>
    `),
  },

  // ---------------------------------------------------------- reach/setup --
  unreachable_faces: {
    caption:
      "Cross-section. Surfaces hidden behind material (undercuts) can't be reached by a tool " +
      "from any direction. Open the feature, split the part, or design to a standard T-slot/lollipop cutter.",
    svg: frame("undercut — hidden from every axis", "open profile, or two-piece assembly", `
      <path d="M18 116 v-80 h44 v22 h-14 v34 h36 v-34 h-14 v-22 h44 v80 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <path d="M48 58 h-14 m52 0 h14" stroke="${C.bad}" stroke-width="2.4"/>
      <path d="M77 20 v12 m-3 -4 l3 4 l3 -4" stroke="${C.tool}" stroke-width="1.3" fill="none"/>
      <text x="96" y="66" ${FONT}>hidden</text>

      <path d="M196 116 v-80 h44 v56 h36 v-56 h44 v80 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <path d="M258 20 v12 m-3 -4 l3 4 l3 -4" stroke="${C.good}" stroke-width="1.3" fill="none"/>
      <path d="M196 121 h124" stroke="${C.text}" stroke-width="0.8" stroke-dasharray="3 2"/>
      <text x="258" y="133" text-anchor="middle" ${FONT}>or split into two bolted parts</text>
    `),
  },

  many_setups: {
    caption:
      "Every tool direction beyond the second means unclamping, re-fixturing, and re-indicating — " +
      "skilled labor before any cutting, plus 0.05–0.1 mm of alignment drift per flip.",
    svg: frame("features on 4 sides — 4 setups", "consolidated on top — 1–2 setups", `
      <rect x="38" y="48" width="78" height="54" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <path d="M77 22 v16 m-4 -5 l4 5 l4 -5" stroke="${C.bad}" stroke-width="1.4" fill="none"/>
      <path d="M77 128 v-16 m-4 5 l4 -5 l4 5" stroke="${C.bad}" stroke-width="1.4" fill="none"/>
      <path d="M12 75 h16 m-5 -4 l5 4 l-5 4" stroke="${C.bad}" stroke-width="1.4" fill="none"/>
      <path d="M142 75 h-16 m5 -4 l-5 4 l5 4" stroke="${C.bad}" stroke-width="1.4" fill="none"/>

      <rect x="222" y="48" width="78" height="54" fill="${C.mat}" stroke="${C.line}" stroke-width="1.5"/>
      <circle cx="244" cy="62" r="4" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="262" cy="62" r="4" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <circle cx="280" cy="62" r="4" fill="#0d1117" stroke="${C.good}" stroke-width="1.2"/>
      <path d="M261 22 v16 m-4 -5 l4 5 l4 -5" stroke="${C.good}" stroke-width="1.4" fill="none"/>
      <text x="261" y="120" text-anchor="middle" ${FONT}>everything from above</text>
    `),
  },

  // -------------------------------------------------------------- surface --
  freeform_surfaces: {
    caption:
      "Sculpted surfaces are traced by a ball-nose tool in hundreds of fine stepover passes; " +
      "flat and cylindrical faces are single sweeping cuts. Keep freeform only where it's functional.",
    svg: frame("freeform — thousands of passes", "prismatic — one face pass", `
      <path d="M18 112 v-44 q18 -22 34 -2 q16 20 32 -4 q16 -22 32 2 v48 z" fill="${C.mat}" stroke="${C.bad}" stroke-width="1.5"/>
      ${Array.from({ length: 9 }, (_, i) =>
        `<path d="M${26 + i * 11} ${58 + (i % 2) * 4} q4 -5 8 0" stroke="${C.tool}" stroke-width="0.8" fill="none"/>`
      ).join("")}
      <text x="78" y="34" text-anchor="middle" ${FONT}>0.2 mm stepovers</text>

      <rect x="196" y="62" width="120" height="50" fill="${C.mat}" stroke="${C.good}" stroke-width="1.5"/>
      <path d="M200 50 h100 m-8 -4 l8 4 l-8 4" stroke="${C.good}" stroke-width="1.3" fill="none"/>
      <text x="256" y="38" text-anchor="middle" ${FONT}>face mill, one pass</text>
    `),
  },

  // ------------------------------------------------------------ integrity --
  open_geometry: {
    caption:
      "The model's surfaces don't close into a solid — like a box with no lid. Shops can't quote " +
      "surface models; stitch the faces into a watertight solid and re-export.",
    svg: frame("open shell — not a solid", "stitched & closed — quotable", `
      <path d="M30 56 l45 -18 l50 14 l-45 18 z" fill="none" stroke="${C.bad}" stroke-width="1.4" stroke-dasharray="4 3"/>
      <path d="M30 56 v40 l45 18 v-40 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.4"/>
      <path d="M75 114 l50 -18 v-40 l-50 18 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.4"/>
      <text x="78" y="28" text-anchor="middle" ${FONT}>missing face / naked edges</text>

      <path d="M208 56 l45 -18 l50 14 l-45 18 z" fill="${C.mat}" stroke="${C.good}" stroke-width="1.4"/>
      <path d="M208 56 v40 l45 18 v-40 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.4"/>
      <path d="M253 114 l50 -18 v-40 l-50 18 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.4"/>
    `),
  },

  multiple_bodies: {
    caption:
      "One STEP file should contain one part. Disconnected bodies are an assembly export, " +
      "leftover reference geometry, or pieces that were never unioned.",
    svg: frame("two bodies in one file", "one file per part (or union them)", `
      <path d="M26 96 v-30 l32 -13 l36 10 v30 l-32 13 z" fill="${C.mat}" stroke="${C.bad}" stroke-width="1.4"/>
      <path d="M104 102 v-22 l24 -10 l26 8 v22 l-24 10 z" fill="${C.mat}" stroke="${C.bad}" stroke-width="1.4"/>

      <rect x="198" y="44" width="56" height="66" rx="5" fill="none" stroke="${C.good}" stroke-width="1.2" stroke-dasharray="4 3"/>
      <path d="M208 88 v-22 l20 -8 l22 6 v22 l-20 8 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.3"/>
      <text x="226" y="122" text-anchor="middle" ${FONT}>a.step</text>
      <rect x="262" y="44" width="56" height="66" rx="5" fill="none" stroke="${C.good}" stroke-width="1.2" stroke-dasharray="4 3"/>
      <path d="M272 86 v-18 l18 -7 l20 5 v18 l-18 7 z" fill="${C.mat}" stroke="${C.line}" stroke-width="1.3"/>
      <text x="290" y="122" text-anchor="middle" ${FONT}>b.step</text>
    `),
  },
};
