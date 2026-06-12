import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { DIAGRAMS } from "/static/diagrams.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SEVERITY_COLORS = {
  critical: new THREE.Color(0xf0506e),
  warning: new THREE.Color(0xf5a623),
  info: new THREE.Color(0x4f8ef7),
};
const BASE_COLOR = new THREE.Color(0x8a93a6);
const DIM_COLOR = new THREE.Color(0x3a4150);

const SUBSCORE_LABELS = {
  integrity: "Geometry integrity",
  features: "Feature difficulty",
  setups: "Setup count",
  accessibility: "Tool accessibility",
  thin_features: "Thin features",
  surface_finish: "Surface finish demand",
};

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const uploadView = $("upload-view");
const resultView = $("result-view");
const dropzone = $("dropzone");
const fileInput = $("file-input");
const loadingEl = $("loading");
const loadingText = $("loading-text");
const errorEl = $("upload-error");

let viewer = null;
let currentData = null;
let activeFinding = null;

// ---------------------------------------------------------------------------
// Upload handling
// ---------------------------------------------------------------------------

$("browse-btn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) analyzeFile(fileInput.files[0]);
});

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files[0];
  if (f) analyzeFile(f);
});

async function loadDemo(name) {
  const resp = await fetch(`/demo/${name}.step`);
  if (!resp.ok) return;
  const blob = await resp.blob();
  analyzeFile(new File([blob], `${name}.step`));
}

document.querySelectorAll(".demo-links a").forEach((a) =>
  a.addEventListener("click", (e) => {
    e.preventDefault();
    loadDemo(a.dataset.demo);
  })
);

// Allow ?demo=name for quick links / testing.
const demoParam = new URLSearchParams(location.search).get("demo");
if (demoParam) loadDemo(demoParam.replace(/[^a-z0-9_]/gi, ""));

$("new-upload").addEventListener("click", () => {
  resultView.classList.add("hidden");
  uploadView.classList.remove("hidden");
  $("new-upload").classList.add("hidden");
  $("file-meta").textContent = "";
  errorEl.classList.add("hidden");
  fileInput.value = "";
});

async function analyzeFile(file) {
  dropzone.classList.add("hidden");
  errorEl.classList.add("hidden");
  loadingEl.classList.remove("hidden");

  const phases = [
    "Parsing B-rep geometry…",
    "Classifying surfaces…",
    "Detecting holes, corners, thin walls…",
    "Ray-casting tool accessibility…",
    "Scoring manufacturability…",
  ];
  let phase = 0;
  loadingText.textContent = phases[0];
  const ticker = setInterval(() => {
    phase = Math.min(phase + 1, phases.length - 1);
    loadingText.textContent = phases[phase];
  }, 1300);

  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/api/analyze", { method: "POST", body: form });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Analysis failed (HTTP ${resp.status})`);
    }
    currentData = await resp.json();
    showResults(currentData);
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
    dropzone.classList.remove("hidden");
  } finally {
    clearInterval(ticker);
    loadingEl.classList.add("hidden");
  }
}

// ---------------------------------------------------------------------------
// Results UI
// ---------------------------------------------------------------------------

function gradeFor(score) {
  if (score >= 90) return ["Excellent", "This part is straightforward to mill. Expect competitive quotes."];
  if (score >= 75) return ["Good", "Minor issues that add some cost but nothing a shop will reject."];
  if (score >= 55) return ["Fair", "Several features will add machining time and cost. Worth a revision pass."];
  if (score >= 35) return ["Difficult", "This part has serious manufacturability problems. Expect high quotes or pushback."];
  return ["Very difficult", "As designed, many shops would no-quote this part. Redesign recommended."];
}

function scoreColor(score) {
  if (score >= 75) return "#3fb27f";
  if (score >= 55) return "#f5a623";
  return "#f0506e";
}

function showResults(data) {
  uploadView.classList.add("hidden");
  resultView.classList.remove("hidden");
  $("new-upload").classList.remove("hidden");
  $("file-meta").textContent = data.filename;

  // Score ring
  const score = data.score;
  const circumference = 2 * Math.PI * 52;
  const ring = $("ring-fill");
  ring.style.stroke = scoreColor(score);
  requestAnimationFrame(() => {
    ring.style.strokeDashoffset = circumference * (1 - score / 100);
  });
  $("score-value").textContent = Math.round(score);
  const [grade, caption] = gradeFor(score);
  $("score-grade").textContent = grade;
  $("score-grade").style.color = scoreColor(score);
  $("score-caption").textContent = caption;

  // Subscores
  const sub = $("subscores");
  sub.innerHTML = "<h2>Score breakdown</h2>";
  for (const [key, label] of Object.entries(SUBSCORE_LABELS)) {
    const v = data.subscores[key] ?? 100;
    const row = document.createElement("div");
    row.className = "subscore";
    row.innerHTML = `
      <div class="subscore-head"><span class="name">${label}</span><span class="val">${Math.round(v)}</span></div>
      <div class="bar"><div style="width:0%;background:${scoreColor(v)}"></div></div>`;
    sub.appendChild(row);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        row.querySelector(".bar > div").style.width = `${v}%`;
      })
    );
  }

  // Stats
  const s = data.part_stats;
  const grid = $("stats-grid");
  const bbox = s.bbox_mm.map((v) => v.toFixed(0)).join(" × ");
  const stats = [
    ["Bounding box", `${bbox} mm`],
    ["Volume", `${(s.volume_mm3 / 1000).toFixed(1)} cm³`],
    ["Material removed", s.material_removal_pct != null ? `${s.material_removal_pct}%` : "–"],
    ["Est. setups", data.setup_info.estimated_setups],
    ["Holes", s.num_holes],
    ["Tapped", s.num_tapped_holes ?? 0],
    ["Faces", s.num_faces],
    ["Bodies", s.num_bodies ?? 1],
    ["Watertight", s.watertight ? "Yes" : `No (${s.free_edges} naked edges)`],
  ];
  grid.innerHTML = stats
    .map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`)
    .join("");

  // Design changes (ranked by score impact)
  renderChanges(data);

  // Findings
  const list = $("findings-list");
  list.innerHTML = "";
  $("finding-count").textContent = data.findings.length ? `(${data.findings.length})` : "";
  if (!data.findings.length) {
    list.innerHTML = `<div class="no-findings">No DFM issues detected — this part looks easy to machine.</div>`;
  }
  data.findings.forEach((f, i) => {
    const card = document.createElement("div");
    card.className = `finding ${f.severity}`;
    const diagram = DIAGRAMS[f.rule];
    card.innerHTML = `
      <div class="finding-head">
        <span class="finding-title">${f.title}</span>
        <span class="badge ${f.severity}">${f.severity}</span>
      </div>
      <div class="finding-detail">${f.detail}</div>
      <div class="finding-fix"><strong>Fix:</strong> ${f.suggestion}</div>
      ${diagram ? `
        <button class="diagram-toggle" type="button">Show drawing example</button>
        <div class="finding-diagram hidden">
          ${diagram.svg}
          <div class="diagram-caption">${diagram.caption}</div>
        </div>` : ""}`;
    card.addEventListener("click", () => toggleFinding(i, card));
    const toggle = card.querySelector(".diagram-toggle");
    if (toggle) {
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const dia = card.querySelector(".finding-diagram");
        dia.classList.toggle("hidden");
        toggle.textContent = dia.classList.contains("hidden")
          ? "Show drawing example"
          : "Hide drawing example";
      });
    }
    list.appendChild(card);
  });

  // Auto-expand the drawing example on the most severe finding.
  const firstToggle = list.querySelector(".diagram-toggle");
  if (firstToggle) firstToggle.click();

  initViewer(data);
}

const CHANGES_PREVIEW = 5;

function renderChanges(data) {
  const card = $("changes-card");
  const list = $("changes-list");
  const more = $("changes-more");
  const recs = data.recommendations || [];
  list.innerHTML = "";
  if (!recs.length) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");

  recs.forEach((r, rank) => {
    const row = document.createElement("div");
    row.className = `change-row ${r.severity}`;
    if (rank >= CHANGES_PREVIEW) row.classList.add("hidden", "overflow-change");
    row.innerHTML = `
      <span class="change-rank">${rank + 1}</span>
      <span class="change-action">${r.action}</span>
      <span class="change-impact">
        <span class="change-gain">+${r.solo_gain} pts</span>
        <span class="change-proj">then → ${Math.round(r.score_after)}</span>
      </span>`;
    row.addEventListener("click", () => {
      document.querySelectorAll(".change-row").forEach((el) => el.classList.remove("active"));
      const findingCard = $("findings-list").children[r.finding_index];
      if (activeFinding === r.finding_index) {
        toggleFinding(r.finding_index, findingCard); // toggles off
        return;
      }
      toggleFinding(r.finding_index, findingCard);
      row.classList.add("active");
      findingCard?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    list.appendChild(row);
  });

  if (recs.length > CHANGES_PREVIEW) {
    more.classList.remove("hidden");
    let expanded = false;
    more.textContent = `Show all ${recs.length} changes`;
    more.onclick = () => {
      expanded = !expanded;
      document.querySelectorAll(".overflow-change").forEach((el) =>
        el.classList.toggle("hidden", !expanded)
      );
      more.textContent = expanded ? "Show fewer" : `Show all ${recs.length} changes`;
    };
  } else {
    more.classList.add("hidden");
  }
}

function toggleFinding(index, card) {
  document.querySelectorAll(".finding").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".change-row").forEach((el) => el.classList.remove("active"));
  if (activeFinding === index) {
    activeFinding = null;
    $("clear-highlight").classList.add("hidden");
    colorMesh(currentData, null);
    return;
  }
  activeFinding = index;
  card.classList.add("active");
  $("clear-highlight").classList.remove("hidden");
  colorMesh(currentData, index);
}

$("clear-highlight").addEventListener("click", () => {
  activeFinding = null;
  document.querySelectorAll(".finding").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".change-row").forEach((el) => el.classList.remove("active"));
  $("clear-highlight").classList.add("hidden");
  colorMesh(currentData, null);
});

// ---------------------------------------------------------------------------
// Three.js viewer
// ---------------------------------------------------------------------------

function initViewer(data) {
  const container = $("viewer");

  if (viewer) {
    viewer.renderer.dispose();
    viewer.renderer.domElement.remove();
    cancelAnimationFrame(viewer.raf);
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1117);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
  camera.up.set(0, 0, 1); // CAD convention: Z is up (spindle axis)
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x30363f, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(1, 2, 1.5);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-1.5, -1, -1);
  scene.add(fill);

  // Geometry
  const m = data.mesh;
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(m.vertices, 3));
  geom.setIndex(m.triangles);
  geom.computeVertexNormals();
  const colors = new Float32Array(m.vertices.length);
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.25,
    roughness: 0.55,
    side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(geom, material);
  scene.add(mesh);

  // Center & frame
  geom.computeBoundingSphere();
  const { center, radius } = geom.boundingSphere;
  mesh.position.sub(center);
  camera.position.set(radius * 1.7, -radius * 1.7, radius * 1.3);
  camera.near = radius / 100;
  camera.far = radius * 20;
  camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);

  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(geom, 25),
    new THREE.LineBasicMaterial({ color: 0x0d1117, transparent: true, opacity: 0.35 })
  );
  mesh.add(edges);

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);
  resize();

  viewer = { scene, camera, renderer, controls, mesh, geom, raf: 0 };

  colorMesh(data, null);

  (function animate() {
    viewer.raf = requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  })();
}

/**
 * Color the mesh by severity. If findingIndex != null, highlight only that
 * finding's faces and dim everything else.
 */
function colorMesh(data, findingIndex) {
  if (!viewer) return;
  const m = data.mesh;
  const triFace = m.tri_face_index;
  const colorsAttr = viewer.geom.getAttribute("color");
  const indices = viewer.geom.getIndex().array;

  // face index -> severity (worst wins)
  const rank = { info: 1, warning: 2, critical: 3 };
  const faceSeverity = new Map();
  const findings = findingIndex == null ? data.findings : [data.findings[findingIndex]];
  for (const f of findings) {
    for (const fi of f.face_indices || []) {
      const prev = faceSeverity.get(fi);
      if (!prev || rank[f.severity] > rank[prev]) faceSeverity.set(fi, f.severity);
    }
  }

  const dim = findingIndex != null;
  for (let t = 0; t < triFace.length; t++) {
    const sev = faceSeverity.get(triFace[t]);
    const color = sev ? SEVERITY_COLORS[sev] : dim ? DIM_COLOR : BASE_COLOR;
    for (let k = 0; k < 3; k++) {
      const vi = indices[t * 3 + k];
      colorsAttr.setXYZ(vi, color.r, color.g, color.b);
    }
  }
  colorsAttr.needsUpdate = true;
}
