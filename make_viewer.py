"""Generate a self-contained local 3D viewer for the reconstructed anatomy.

Reads the STL files written by reconstruct_3d.py, decimates them for the web,
and embeds the geometry directly in an HTML file. The patient-derived geometry
never leaves the machine — only the three.js runtime is fetched from a CDN.

    uv run python make_viewer.py --mesh-dir data/mesh --out data/mesh/viewer.html
"""

import argparse
import base64
import json
import urllib.request
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support

THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.min.js"
THREE_CACHE = Path(".cache/three.min.js")

BONE_COLOR = "#ddd2bd"

# (file stem, display name, colour, group). Muscles read as the subject; the
# bones are reference geometry that can be toggled off.
STRUCTURES = [
	("gluteus_medius_left", "Gluteus medius L", "#5b8dee", "muscle"),
	("gluteus_medius_right", "Gluteus medius R", "#2fb8a6", "muscle"),
	("gluteus_minimus_left", "Gluteus minimus L", "#e8543f", "muscle"),
	("gluteus_minimus_right", "Gluteus minimus R", "#f2a03d", "muscle"),
	("hip_left", "Hip bone L", BONE_COLOR, "pelvis"),
	("hip_right", "Hip bone R", BONE_COLOR, "pelvis"),
	("sacrum", "Sacrum", BONE_COLOR, "pelvis"),
	("femur_left", "Femur L", BONE_COLOR, "femur"),
	("femur_right", "Femur R", BONE_COLOR, "femur"),
]


def read_stl(path):
	r = vtk.vtkSTLReader()
	r.SetFileName(str(path))
	r.Update()
	return r.GetOutput()


def decimate(poly, target):
	n = poly.GetNumberOfPolys()
	if n <= target:
		return poly
	d = vtk.vtkQuadricDecimation()
	d.SetInputData(poly)
	d.SetTargetReduction(1.0 - target / n)
	d.Update()
	return d.GetOutput()


def weld(poly):
	"""Merge duplicate points so the geometry can be sent as an indexed mesh."""
	c = vtk.vtkCleanPolyData()
	c.SetInputData(poly)
	c.PointMergingOn()
	c.Update()
	return c.GetOutput()


def to_arrays(poly):
	verts = numpy_support.vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float32)
	faces = numpy_support.vtk_to_numpy(poly.GetPolys().GetData()).reshape(-1, 4)[:, 1:]
	return verts, faces.astype(np.uint32)


def b64(a):
	return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


HTML = """<!doctype html>
<meta charset="utf-8">
<title>Gluteal muscles 3D</title>
<style>
  :root {{
    --bg: #10141c; --panel: #161c27; --line: #263143;
    --fg: #e8edf5; --muted: #8e9cb3; --accent: #6ea8ff;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  #app {{ display: flex; height: 100%; }}
  #view {{ flex: 1; position: relative; min-width: 0; }}
  #view canvas {{ display: block; touch-action: none; }}
  #hint {{ position: absolute; left: 16px; bottom: 14px; color: var(--muted); font-size: 12px; }}
  #panel {{ width: 300px; flex: none; background: var(--panel); border-left: 1px solid var(--line);
    padding: 20px 18px; overflow-y: auto; }}
  h1 {{ font-size: 16px; margin: 0 0 2px; letter-spacing: .01em; }}
  .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 16px; }}
  h2 {{ font-size: 11px; text-transform: uppercase; letter-spacing: .09em;
    color: var(--muted); margin: 20px 0 7px; font-weight: 600; }}
  .row {{ display: flex; align-items: center; gap: 9px; padding: 7px 0;
    border-bottom: 1px solid var(--line); }}
  .row:last-child {{ border-bottom: 0; }}
  .row input[type=checkbox] {{ accent-color: var(--accent); width: 15px; height: 15px; flex: none; }}
  .row input[type=checkbox]:disabled {{ cursor: not-allowed; }}
  .sw {{ width: 13px; height: 13px; border-radius: 3px; flex: none; }}
  .nm {{ flex: 1; min-width: 0; }}
  .vol {{ font-variant-numeric: tabular-nums; color: var(--muted); font-size: 12px; }}
  .btns {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }}
  button {{ background: #1e2836; color: var(--fg); border: 1px solid var(--line);
    border-radius: 6px; padding: 7px 4px; font-size: 12px; cursor: pointer; font-family: inherit; }}
  button:hover {{ background: #273347; }}
  button.on {{ border-color: var(--accent); color: var(--accent); }}
  label.slider {{ display: block; color: var(--muted); font-size: 12px; margin-top: 12px; }}
  label.slider b {{ color: var(--fg); font-weight: 500; font-variant-numeric: tabular-nums; }}
  input[type=range] {{ width: 100%; accent-color: var(--accent); margin-top: 5px; }}
  .note {{ color: var(--muted); font-size: 11px; line-height: 1.6; margin-top: 20px;
    padding-top: 13px; border-top: 1px solid var(--line); }}
  #err {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 10px; padding: 40px;
    text-align: center; }}
  #err b {{ font-size: 15px; color: #ff9d8a; }}
  #err p {{ margin: 0; max-width: 460px; color: var(--muted); font-size: 13px; line-height: 1.7; }}
  #err code {{ color: var(--fg); background: #1e2836; padding: 1px 5px; border-radius: 4px; }}
</style>
<div id="app">
  <div id="view">
    <div id="hint">two-finger drag to rotate &middot; pinch to zoom &middot; &#8679;+two-finger to pan</div>
    <div id="err" hidden></div>
  </div>
  <div id="panel">
    <h1>Gluteal muscles</h1>
    <div class="sub">CT 3D reconstruction</div>

    <h2>Muscles</h2>
    <div id="muscles"></div>
    <label class="slider">Gluteus medius opacity <b id="mov">35%</b>
      <input type="range" id="mop" min="5" max="100" value="35"></label>

    <h2>Reference</h2>
    <div id="bones"></div>
    <label class="slider">Bone opacity <b id="bov">100%</b>
      <input type="range" id="bop" min="10" max="100" value="100"></label>

    <h2>View</h2>
    <div class="btns">
      <button data-v="A">Ant</button><button data-v="P">Post</button>
      <button data-v="S">Sup</button>
      <button data-v="L">Left</button><button data-v="R">Right</button>
      <button data-v="O">Oblique</button>
    </div>

    <div class="note">{note}</div>
  </div>
</div>
{three_tag}
<script>
const DATA = {data};

// A blank dark canvas is impossible to diagnose, so say what actually failed.
let failed = false;
function fail(title, detail) {{
  if (failed) return;
  failed = true;
  const box = document.getElementById('err');
  box.innerHTML = '<b>' + title + '</b><p>' + detail + '</p>';
  box.hidden = false;
  document.getElementById('hint').hidden = true;
}}
addEventListener('error', e => fail('Script error',
  String((e && (e.message || e.error)) || 'unknown') +
  ' &mdash; open the browser console for the full trace.'));

function webglOk() {{
  try {{
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  }} catch (_) {{ return false; }}
}}

if (typeof THREE === 'undefined') {{
  fail('three.js did not load',
       '{three_hint}');
}} else if (!webglOk()) {{
  fail('WebGL is not available',
       'This browser could not create a WebGL context. In Chrome, turn on ' +
       '<code>Settings &rarr; System &rarr; Use graphics acceleration</code> and ' +
       'check <code>chrome://gpu</code>.');
}} else {{
  boot();
}}

function boot() {{

const view = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x10141c);
const camera = new THREE.PerspectiveCamera(35, 1, 1, 12000);
let renderer;
try {{
  renderer = new THREE.WebGLRenderer({{antialias: true}});
}} catch (e) {{
  fail('WebGL context could not be created', String(e && e.message || e));
  return;
}}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.appendChild(renderer.domElement);

// three.js r155+ scales lights physically, so these run hot on purpose.
scene.add(new THREE.AmbientLight(0xffffff, 1.9));
const key = new THREE.DirectionalLight(0xffffff, 3.2); key.position.set(1, 1.1, 1.4);
const fill = new THREE.DirectionalLight(0xcfe0ff, 1.5); fill.position.set(-1, -0.4, -0.9);
const rim = new THREE.DirectionalLight(0xffffff, 1.1); rim.position.set(0, 0.4, -1.4);
scene.add(key, fill, rim);

const root = new THREE.Group(); scene.add(root);
const bb = new THREE.Box3();
const meshes = [];

function decode(s, Type) {{
  const bin = atob(s), buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Type(buf.buffer);
}}

DATA.structures.forEach(s => {{
  const pos = decode(s.verts, Float32Array);
  const idx = decode(s.faces, Uint32Array);
  // Patient LPS (x=left, y=posterior, z=superior) -> viewer (x=left, y=up, z=anterior)
  const p = new Float32Array(pos.length);
  for (let i = 0; i < pos.length; i += 3) {{
    p[i] = pos[i]; p[i + 1] = pos[i + 2]; p[i + 2] = -pos[i + 1];
  }}
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();

  const shell = s.name.includes('medius');   // drawn as a translucent skin
  const m = new THREE.Mesh(g, new THREE.MeshPhongMaterial({{
    color: new THREE.Color(s.color), shininess: s.group === 'muscle' ? 34 : 14,
    specular: s.group === 'muscle' ? 0x3d4a5e : 0x2b2f36,
    transparent: true, opacity: shell ? 0.35 : 1,
    side: THREE.FrontSide, depthWrite: !shell,
  }}));
  m.renderOrder = shell ? 1 : 0;
  m.userData = s;
  s.on = true;
  root.add(m); meshes.push(m);
  bb.expandByObject(m);
}});

root.position.sub(bb.getCenter(new THREE.Vector3()));

// --- camera ---------------------------------------------------------------
let theta = 0, phi = Math.PI / 2, dist = 1;
const target = new THREE.Vector3();
// [theta, phi] placing the camera on that side of the patient.
const VIEWS = {{
  A: [0, Math.PI / 2], P: [Math.PI, Math.PI / 2],
  L: [Math.PI / 2, Math.PI / 2], R: [-Math.PI / 2, Math.PI / 2],
  S: [0, 0.12], O: [Math.PI * 0.72, Math.PI * 0.38],
}};
const SIDE_OF_VIEW = {{L: 'left', R: 'right'}};

function place() {{
  camera.position.set(
    target.x + dist * Math.sin(phi) * Math.sin(theta),
    target.y + dist * Math.cos(phi),
    target.z + dist * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(target);
}}

/** Frame whatever is currently visible, fitting both screen axes. */
function fit() {{
  root.updateMatrixWorld(true);            // bbox below is world-space
  const box = new THREE.Box3();
  meshes.filter(m => m.visible).forEach(m => box.expandByObject(m));
  if (box.isEmpty()) return;
  box.getCenter(target);
  const r = box.getSize(new THREE.Vector3()).length() / 2;
  const vFov = camera.fov * Math.PI / 180;
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  dist = Math.max(r / Math.sin(vFov / 2), r / Math.sin(hFov / 2)) * 1.05;
  place();
}}

/** Visible = its group is on, its own box is ticked, and the side is in view. */
const groupOn = {{muscle: true, pelvis: true, femur: true}};
let onlySide = null;
function apply(refit) {{
  meshes.forEach(m => {{
    const s = m.userData;
    m.visible = groupOn[s.group] && s.on
      && (!onlySide || s.side === onlySide || s.side === null);
  }});
  // A row filtered out by the current view is dimmed, so a ticked-but-hidden
  // checkbox does not read as a bug.
  meshes.forEach(m => {{
    const row = m.userData.row;
    if (!row) return;
    const filtered = !!onlySide && m.userData.side !== onlySide && m.userData.side !== null;
    row.style.opacity = filtered ? 0.35 : 1;
    row.querySelector('input').disabled = filtered;
  }});
  if (refit) fit(); else place();
}}

function setView(k) {{
  [theta, phi] = VIEWS[k];
  onlySide = SIDE_OF_VIEW[k] || null;
  document.querySelectorAll('[data-v]').forEach(b =>
    b.classList.toggle('on', b.dataset.v === k));
  apply(true);
}}

let drag = null;
const cv = renderer.domElement;
cv.addEventListener('pointerdown', e => {{
  drag = {{x: e.clientX, y: e.clientY, pan: e.button === 2}};
  cv.setPointerCapture(e.pointerId);
}});
cv.addEventListener('pointerup', () => {{ drag = null; }});
cv.addEventListener('contextmenu', e => e.preventDefault());
cv.addEventListener('pointermove', e => {{
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (drag.pan) {{
    panBy(-dx, dy);
  }} else {{
    theta -= dx * 0.008;
    phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi - dy * 0.008));
  }}
  place();
}});
// --- trackpad ------------------------------------------------------------
// macOS sends a pinch as a wheel event with ctrlKey set and a two-finger swipe
// as a plain wheel event, usually carrying a deltaX or a fractional deltaY. A
// real mouse wheel sends line-mode or clean integer steps with deltaX === 0,
// so it keeps its familiar zoom. Signs follow the finger, matching a drag.
let trackpadSeen = false;

function zoomBy(factor) {{
  dist = Math.max(20, Math.min(6000, dist * factor));
  place();
}}

function panBy(dx, dy) {{
  const right = new THREE.Vector3(), up = new THREE.Vector3();
  camera.matrixWorld.extractBasis(right, up, new THREE.Vector3());
  const k = dist / 900;
  target.addScaledVector(right, dx * k).addScaledVector(up, dy * k);
}}

cv.addEventListener('wheel', e => {{
  e.preventDefault();
  if (e.deltaX !== 0 || !Number.isInteger(e.deltaY)) trackpadSeen = true;

  if (e.ctrlKey) {{                                  // pinch
    zoomBy(Math.exp(e.deltaY * 0.01));
  }} else if (e.deltaMode !== 0 || (!trackpadSeen && e.deltaX === 0)) {{
    zoomBy(1 + Math.sign(e.deltaY) * 0.11);          // mouse wheel
  }} else if (e.shiftKey) {{                          // two-finger swipe + shift
    panBy(e.deltaX, -e.deltaY);
    place();
  }} else {{                                          // two-finger swipe
    theta += e.deltaX * 0.005;
    phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi + e.deltaY * 0.005));
    place();
  }}
}}, {{passive: false}});

// Safari reports pinch through its own gesture events rather than ctrl+wheel.
let gestureScale = 1;
cv.addEventListener('gesturestart', e => {{ e.preventDefault(); gestureScale = e.scale; }});
cv.addEventListener('gesturechange', e => {{
  e.preventDefault();
  if (e.scale > 0) {{ zoomBy(gestureScale / e.scale); gestureScale = e.scale; }}
}});
cv.addEventListener('gestureend', e => e.preventDefault());
document.querySelectorAll('[data-v]').forEach(b => b.onclick = () => setView(b.dataset.v));

// --- panel ----------------------------------------------------------------
function addRow(host, m) {{
  const s = m.userData;
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<input type="checkbox" checked>
    <span class="sw" style="background:${{s.color}}"></span>
    <span class="nm">${{s.label}}</span>
    <span class="vol">${{s.volume_ml.toFixed(1)}} mL</span>`;
  row.querySelector('input').onchange = e => {{ s.on = e.target.checked; apply(true); }};
  m.userData.row = row;
  host.appendChild(row);
}}

function addGroupRow(host, group, label) {{
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<input type="checkbox" checked>
    <span class="sw" style="background:${{DATA.bone_color}}"></span>
    <span class="nm">${{label}}</span><span class="vol"></span>`;
  row.querySelector('input').onchange = e => {{ groupOn[group] = e.target.checked; apply(true); }};
  host.appendChild(row);
}}

meshes.filter(m => m.userData.group === 'muscle')
      .forEach(m => addRow(document.getElementById('muscles'), m));
addGroupRow(document.getElementById('bones'), 'pelvis', 'Pelvis (hip bones + sacrum)');
addGroupRow(document.getElementById('bones'), 'femur', 'Femur');

function bindOpacity(sliderId, valueId, match) {{
  const sl = document.getElementById(sliderId), out = document.getElementById(valueId);
  sl.oninput = () => {{
    const v = sl.value / 100;
    out.textContent = sl.value + '%';
    meshes.filter(m => match(m.userData)).forEach(m => {{
      m.material.opacity = v;
      m.material.depthWrite = v > 0.97;
      m.renderOrder = v > 0.97 ? 0 : 1;
    }});
  }};
}}
bindOpacity('mop', 'mov', s => s.name.includes('medius'));
bindOpacity('bop', 'bov', s => s.group !== 'muscle');

function resize() {{
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  fit();
}}
addEventListener('resize', resize);
resize(); setView('P');
(function loop() {{ requestAnimationFrame(loop); renderer.render(scene, camera); }})();

}}  // boot
</script>
"""


def three_js():
	"""three.min.js source, cached under .cache/ so we fetch it at most once."""
	if THREE_CACHE.exists():
		return THREE_CACHE.read_text(encoding="utf-8")
	print(f"fetching {THREE_URL}")
	with urllib.request.urlopen(THREE_URL, timeout=60) as r:
		src = r.read().decode("utf-8")
	THREE_CACHE.parent.mkdir(parents=True, exist_ok=True)
	THREE_CACHE.write_text(src, encoding="utf-8")
	return src


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--mesh-dir", default="data/mesh", type=Path)
	ap.add_argument("--out", default="data/mesh/viewer.html", type=Path)
	ap.add_argument("--target-triangles", default=16000, type=int)
	ap.add_argument("--inline-three", action="store_true",
					help="embed three.js instead of loading it from a CDN, so the "
						 "page needs no network and no CDN can be blocked")
	args = ap.parse_args()

	volumes = {v["structure"]: v["volume_ml"]
			   for v in json.loads((args.mesh_dir / "volumes.json").read_text())}

	structures, total = [], 0
	for name, label, color, group in STRUCTURES:
		stl = args.mesh_dir / f"{name}.stl"
		if not stl.exists():
			print(f"skip (not found): {stl}")
			continue
		verts, faces = to_arrays(weld(decimate(read_stl(stl), args.target_triangles)))
		total += len(faces)
		side = ("left" if name.endswith("_left")
				else "right" if name.endswith("_right") else None)
		structures.append(dict(name=name, label=label, color=color, group=group,
							   side=side, volume_ml=volumes.get(name, 0.0),
							   verts=b64(verts), faces=b64(faces)))
		print(f"{label:<18} {len(verts):>6d} verts  {len(faces):>6d} tris")

	note = ("Automatic segmentation (TotalSegmentator v2). Research use only — "
			"not for diagnosis. Patient-derived data: keep this file local.")
	if args.inline_three:
		three_tag = "<script>" + three_js() + "</script>"
		three_hint = ("three.js is embedded in this file, so this should not happen. "
					  "The file may be truncated &mdash; regenerate it.")
	else:
		three_tag = f'<script src="{THREE_URL}"></script>'
		three_hint = ("This page pulls three.js from <code>cdnjs.cloudflare.com</code>. "
					  "A content blocker, an extension, an enterprise policy, or simply "
					  "being offline will stop it. Check the Network tab for that "
					  "request, or rebuild with <code>--inline-three</code>.")

	args.out.write_text(
		HTML.format(data=json.dumps(dict(structures=structures, bone_color=BONE_COLOR)),
					note=note, three_tag=three_tag, three_hint=three_hint),
		encoding="utf-8")
	print(f"\n{total} triangles total -> {args.out} "
		  f"({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
	main()
