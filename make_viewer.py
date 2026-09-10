"""Generate a self-contained local 3D viewer for the reconstructed muscles.

Reads the STL files written by reconstruct_3d.py, decimates them for the web,
and embeds the geometry directly in an HTML file. The patient-derived geometry
never leaves the machine — only the three.js runtime is fetched from a CDN.

    uv run python make_viewer.py --mesh-dir data/mesh --out data/mesh/viewer.html
"""

import argparse
import base64
import json
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support

STRUCTURES = [
	("gluteus_medius_left", "中殿筋 (左)", "Gluteus medius L", "#5b8dee"),
	("gluteus_medius_right", "中殿筋 (右)", "Gluteus medius R", "#2fb8a6"),
	("gluteus_minimus_left", "小殿筋 (左)", "Gluteus minimus L", "#e8543f"),
	("gluteus_minimus_right", "小殿筋 (右)", "Gluteus minimus R", "#f2a03d"),
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
<title>小殿筋・中殿筋 3D</title>
<style>
  :root {{
    --bg: #10141c; --panel: #161c27; --line: #263143;
    --fg: #e8edf5; --muted: #8e9cb3;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font: 14px/1.55 -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif; }}
  #app {{ display: flex; height: 100%; }}
  #view {{ flex: 1; position: relative; min-width: 0; }}
  #view canvas {{ display: block; }}
  #hint {{ position: absolute; left: 16px; bottom: 14px; color: var(--muted); font-size: 12px; }}
  #panel {{ width: 290px; flex: none; background: var(--panel); border-left: 1px solid var(--line);
    padding: 20px 18px; overflow-y: auto; }}
  h1 {{ font-size: 16px; margin: 0 0 2px; letter-spacing: .02em; }}
  .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 18px; }}
  h2 {{ font-size: 11px; text-transform: uppercase; letter-spacing: .09em;
    color: var(--muted); margin: 22px 0 9px; font-weight: 600; }}
  .row {{ display: flex; align-items: center; gap: 9px; padding: 7px 0;
    border-bottom: 1px solid var(--line); }}
  .row:last-of-type {{ border-bottom: 0; }}
  .row input {{ accent-color: #6ea8ff; width: 15px; height: 15px; flex: none; }}
  .sw {{ width: 13px; height: 13px; border-radius: 3px; flex: none; }}
  .nm {{ flex: 1; min-width: 0; }}
  .nm small {{ display: block; color: var(--muted); font-size: 11px; }}
  .vol {{ font-variant-numeric: tabular-nums; color: var(--muted); font-size: 12px; }}
  .btns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }}
  button {{ background: #1e2836; color: var(--fg); border: 1px solid var(--line);
    border-radius: 6px; padding: 7px 4px; font-size: 12px; cursor: pointer; font-family: inherit; }}
  button:hover {{ background: #273347; border-color: #38496380; }}
  label.slider {{ display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }}
  input[type=range] {{ width: 100%; accent-color: #6ea8ff; margin-top: 5px; }}
  .note {{ color: var(--muted); font-size: 11px; line-height: 1.6; margin-top: 22px;
    padding-top: 14px; border-top: 1px solid var(--line); }}
</style>
<div id="app">
  <div id="view"><div id="hint">ドラッグ=回転 / ホイール=拡大縮小 / 右ドラッグ=平行移動</div></div>
  <div id="panel">
    <h1>小殿筋・中殿筋</h1>
    <div class="sub">CT 3D reconstruction</div>
    <h2>表示</h2>
    <div id="list"></div>
    <label class="slider">中殿筋の不透明度 <span id="opv">35%</span>
      <input type="range" id="op" min="5" max="100" value="35">
    </label>
    <h2>視点</h2>
    <div class="btns">
      <button data-v="A">前面 A</button><button data-v="P">後面 P</button>
      <button data-v="L">左外側 L</button><button data-v="R">右外側 R</button>
      <button data-v="S">頭側 S</button><button data-v="O">斜位</button>
    </div>
    <div class="note">{note}</div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.min.js"></script>
<script>
const DATA = {data};

const view = document.getElementById('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x10141c);
const camera = new THREE.PerspectiveCamera(35, 1, 1, 8000);
const renderer = new THREE.WebGLRenderer({{antialias: true}});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.appendChild(renderer.domElement);

// three.js r155+ lights are physically scaled, so these run hot on purpose.
scene.add(new THREE.AmbientLight(0xffffff, 1.9));
const key = new THREE.DirectionalLight(0xffffff, 3.2); key.position.set(1, 1.1, 1.4);
const fill = new THREE.DirectionalLight(0xcfe0ff, 1.5); fill.position.set(-1, -0.4, -0.9);
const rim = new THREE.DirectionalLight(0xffffff, 1.1); rim.position.set(0, 0.4, -1.4);
scene.add(key, fill, rim);

// Patient LPS (x=left, y=posterior, z=superior) -> viewer (x=left, y=up, z=towards anterior)
const root = new THREE.Group(); scene.add(root);
const bb = new THREE.Box3();
const meshes = [];

function decode(b64, Type) {{
  const bin = atob(b64), buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Type(buf.buffer);
}}

DATA.structures.forEach(s => {{
  const pos = decode(s.verts, Float32Array);
  const idx = decode(s.faces, Uint32Array);
  const g = new THREE.BufferGeometry();
  // swap axes: LPS(x, y, z) -> (x, z, -y)
  const p = new Float32Array(pos.length);
  for (let i = 0; i < pos.length; i += 3) {{
    p[i] = pos[i]; p[i + 1] = pos[i + 2]; p[i + 2] = -pos[i + 1];
  }}
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  const deep = s.name.includes('minimus');
  const m = new THREE.Mesh(g, new THREE.MeshPhongMaterial({{
    color: new THREE.Color(s.color), shininess: 34, specular: 0x3d4a5e,
    transparent: true, opacity: deep ? 1 : 0.35,
    side: THREE.FrontSide, depthWrite: deep,   // single blend layer for the shell
  }}));
  m.renderOrder = deep ? 0 : 1;
  m.userData = s;
  root.add(m); meshes.push(m);
  bb.expandByObject(m);
}});

const center = bb.getCenter(new THREE.Vector3());
root.position.sub(center);

// --- camera orbit ---------------------------------------------------------
let theta = 0, phi = Math.PI / 2, dist = 1;
const target = new THREE.Vector3();
const VIEWS = {{
  A: [0, Math.PI / 2], P: [Math.PI, Math.PI / 2],
  L: [Math.PI / 2, Math.PI / 2], R: [-Math.PI / 2, Math.PI / 2],
  S: [0, 0.12], O: [Math.PI * 0.72, Math.PI * 0.38],
}};

function place() {{
  camera.position.set(
    target.x + dist * Math.sin(phi) * Math.sin(theta),
    target.y + dist * Math.cos(phi),
    target.z + dist * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(target);
}}

/** Frame whatever is currently visible, fitting both screen axes. */
function fit() {{
  root.updateMatrixWorld(true);   // bbox below is world-space
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

// Lateral views isolate that side; every other view brings both sides back.
const SIDE_OF_VIEW = {{L: 'left', R: 'right'}};
function setView(k) {{
  [theta, phi] = VIEWS[k];
  const only = SIDE_OF_VIEW[k] || null;
  meshes.forEach((m, i) => {{
    const on = !only || m.userData.name.endsWith('_' + only);
    m.visible = on;
    const cb = document.getElementById('c' + i);
    if (cb) cb.checked = on;
  }});
  fit();
}}

let drag = null;
renderer.domElement.addEventListener('pointerdown', e => {{
  drag = {{x: e.clientX, y: e.clientY, pan: e.button === 2}};
  renderer.domElement.setPointerCapture(e.pointerId);
}});
renderer.domElement.addEventListener('pointerup', () => {{ drag = null; }});
renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
renderer.domElement.addEventListener('pointermove', e => {{
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (drag.pan) {{
    const right = new THREE.Vector3(), up = new THREE.Vector3();
    camera.matrixWorld.extractBasis(right, up, new THREE.Vector3());
    const k = dist / 900;
    target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
  }} else {{
    theta -= dx * 0.008;
    phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi - dy * 0.008));
  }}
  place();
}});
renderer.domElement.addEventListener('wheel', e => {{
  e.preventDefault();
  dist = Math.max(20, Math.min(4000, dist * (1 + Math.sign(e.deltaY) * 0.11)));
  place();
}}, {{passive: false}});
document.querySelectorAll('[data-v]').forEach(b =>
  b.onclick = () => setView(b.dataset.v));

// --- panel ---------------------------------------------------------------
const list = document.getElementById('list');
meshes.forEach((m, i) => {{
  const s = m.userData;
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<input type="checkbox" checked id="c${{i}}">
    <span class="sw" style="background:${{s.color}}"></span>
    <span class="nm">${{s.label}}<small>${{s.en}}</small></span>
    <span class="vol">${{s.volume_ml.toFixed(1)}} mL</span>`;
  row.querySelector('input').onchange = e => {{ m.visible = e.target.checked; fit(); }};
  list.appendChild(row);
}});
const op = document.getElementById('op'), opv = document.getElementById('opv');
op.oninput = () => {{
  const v = op.value / 100; opv.textContent = op.value + '%';
  meshes.filter(m => m.userData.name.includes('medius'))
        .forEach(m => {{ m.material.opacity = v; m.material.depthWrite = v > 0.97; }});
}};

function resize() {{
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  fit();
}}
addEventListener('resize', resize);
resize(); setView('P');
(function loop() {{ requestAnimationFrame(loop); renderer.render(scene, camera); }})();
</script>
"""


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--mesh-dir", default="data/mesh", type=Path)
	ap.add_argument("--out", default="data/mesh/viewer.html", type=Path)
	ap.add_argument("--target-triangles", default=20000, type=int)
	args = ap.parse_args()

	volumes = {v["structure"]: v["volume_ml"]
			   for v in json.loads((args.mesh_dir / "volumes.json").read_text())}

	structures, total_tris = [], 0
	for name, label, en, color in STRUCTURES:
		stl = args.mesh_dir / f"{name}.stl"
		if not stl.exists():
			print(f"skip (not found): {stl}")
			continue
		verts, faces = to_arrays(weld(decimate(read_stl(stl), args.target_triangles)))
		total_tris += len(faces)
		structures.append(dict(name=name, label=label, en=en, color=color,
							   volume_ml=volumes.get(name, 0.0),
							   verts=b64(verts), faces=b64(faces)))
		print(f"{label:<12} {len(verts):>6d} verts  {len(faces):>6d} tris")

	note = ("TotalSegmentator v2 による自動セグメンテーション。研究用途であり "
			"診断には使用できません。患者由来データのため、このファイルは "
			"ローカル限定です。")
	html = HTML.format(data=json.dumps(dict(structures=structures)),
					   note=note)
	args.out.write_text(html, encoding="utf-8")
	size_mb = args.out.stat().st_size / 1e6
	print(f"\n{total_tris} triangles total -> {args.out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
	main()
