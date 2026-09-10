"""Build 3D surface models of the gluteal muscles from TotalSegmentator masks.

Reads the NIfTI masks produced by TotalSegmentator, turns each one into a
smoothed triangle mesh with marching cubes, and writes an STL per structure
plus a set of rendered views.

    uv run python reconstruct_3d.py --seg-dir data/seg --out-dir data/mesh
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Labels are Japanese; fall back through the CJK faces macOS ships with.
matplotlib.rcParams["font.family"] = [
	"Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic", "Arial Unicode MS", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False
import SimpleITK as sitk
import vtk
from scipy import ndimage
from skimage import measure
from vtk.util import numpy_support

# Structures to reconstruct, in draw order (deepest first), with display colours.
STRUCTURES = [
	("gluteus_minimus_left", "小殿筋 (左)", "#e8543f"),
	("gluteus_minimus_right", "小殿筋 (右)", "#f2a03d"),
	("gluteus_medius_left", "中殿筋 (左)", "#3d7ff2"),
	("gluteus_medius_right", "中殿筋 (右)", "#3fbfae"),
]


def load_mask(path):
	"""Return (bool array in (z, y, x), spacing as (sz, sy, sx), origin as (x, y, z))."""
	img = sitk.ReadImage(str(path))
	arr = sitk.GetArrayFromImage(img).astype(np.uint8)
	sx, sy, sz = img.GetSpacing()
	return arr > 0, (sz, sy, sx), img.GetOrigin()


def largest_component(mask):
	"""Drop stray blobs; muscles are single connected structures."""
	lab, n = ndimage.label(mask)
	if n <= 1:
		return mask
	sizes = ndimage.sum(mask, lab, range(1, n + 1))
	return lab == (int(np.argmax(sizes)) + 1)


def mask_to_mesh(mask, spacing, origin, smooth_sigma=1.0):
	"""Marching cubes on a blurred mask -> vertices in patient (LPS) mm, plus faces."""
	vol = ndimage.gaussian_filter(mask.astype(np.float32), sigma=smooth_sigma)
	verts, faces, _, _ = measure.marching_cubes(vol, level=0.5, spacing=spacing)
	# marching_cubes works in (z, y, x); convert to physical (x, y, z).
	xyz = np.empty_like(verts)
	xyz[:, 0] = verts[:, 2] + origin[0]
	xyz[:, 1] = verts[:, 1] + origin[1]
	xyz[:, 2] = verts[:, 0] + origin[2]
	return xyz, faces


def to_vtk(verts, faces):
	points = vtk.vtkPoints()
	points.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(verts, dtype=np.float64)))
	cells = np.hstack([np.full((len(faces), 1), 3, dtype=np.int64), faces.astype(np.int64)])
	tris = vtk.vtkCellArray()
	tris.SetCells(len(faces), numpy_support.numpy_to_vtkIdTypeArray(cells.ravel(), deep=True))
	poly = vtk.vtkPolyData()
	poly.SetPoints(points)
	poly.SetPolys(tris)
	return poly


def from_vtk(poly):
	verts = numpy_support.vtk_to_numpy(poly.GetPoints().GetData())
	faces = numpy_support.vtk_to_numpy(poly.GetPolys().GetData()).reshape(-1, 4)[:, 1:]
	return verts, faces


def refine(poly, target_triangles, smooth_iterations=30):
	"""Taubin-smooth, then decimate down to roughly target_triangles."""
	smoother = vtk.vtkWindowedSincPolyDataFilter()
	smoother.SetInputData(poly)
	smoother.SetNumberOfIterations(smooth_iterations)
	smoother.SetPassBand(0.05)
	smoother.NonManifoldSmoothingOn()
	smoother.NormalizeCoordinatesOn()
	smoother.Update()
	poly = smoother.GetOutput()

	n = poly.GetNumberOfPolys()
	if n > target_triangles:
		deci = vtk.vtkDecimatePro()
		deci.SetInputData(poly)
		deci.SetTargetReduction(1.0 - target_triangles / n)
		deci.PreserveTopologyOn()
		deci.Update()
		poly = deci.GetOutput()
	return poly


def write_stl(poly, path):
	w = vtk.vtkSTLWriter()
	w.SetFileName(str(path))
	w.SetInputData(poly)
	w.SetFileTypeToBinary()
	w.Write()


# Camera directions in patient (LPS) space: +x = left, +y = posterior, +z = superior.
# `side` limits a view to one side's muscles so the pair does not overlap.
VIEWS = [
	("後面 posterior", (0, 1, 0), (0, 0, 1), None),
	("前面 anterior", (0, -1, 0), (0, 0, 1), None),
	("左外側 left lateral", (1, 0, 0), (0, 0, 1), "left"),
	("右外側 right lateral", (-1, 0, 0), (0, 0, 1), "right"),
]


def crop_to_content(tile, margin=14, bg=250):
	"""Trim the white surround so the muscles fill the tile."""
	ink = (tile[:, :, :3].min(axis=2) < bg)
	if not ink.any():
		return tile
	rows, cols = np.where(ink.any(1))[0], np.where(ink.any(0))[0]
	r0, r1 = max(rows[0] - margin, 0), min(rows[-1] + margin + 1, tile.shape[0])
	c0, c1 = max(cols[0] - margin, 0), min(cols[-1] + margin + 1, tile.shape[1])
	return tile[r0:r1, c0:c1]


def render(meshes, out_path, title, size=(900, 780)):
	"""Shaded VTK renders from four viewpoints, tiled into one PNG."""
	allv = np.vstack([m["verts"] for m in meshes])
	center = (allv.max(0) + allv.min(0)) / 2
	radius = np.linalg.norm(allv.max(0) - allv.min(0)) / 2

	tiles = []
	for _, direction, up, side in VIEWS:
		shown = [m for m in meshes if side is None or m["side"] == side]
		ren = vtk.vtkRenderer()
		ren.SetBackground(1, 1, 1)
		ren.SetUseDepthPeeling(True)
		ren.SetMaximumNumberOfPeels(12)
		ren.SetOcclusionRatio(0.0)

		for m in shown:
			mapper = vtk.vtkPolyDataMapper()
			mapper.SetInputData(m["poly"])
			mapper.ScalarVisibilityOff()
			actor = vtk.vtkActor()
			actor.SetMapper(mapper)
			p = actor.GetProperty()
			p.SetColor(*matplotlib.colors.to_rgb(m["color"]))
			p.SetOpacity(m["alpha"])
			p.SetSpecular(0.28)
			p.SetSpecularPower(22)
			p.SetDiffuse(0.85)
			p.SetAmbient(0.18)
			ren.AddActor(actor)

		d = np.array(direction, dtype=float)
		d /= np.linalg.norm(d)
		up_v = np.array(up, dtype=float)
		right_v = np.cross(d, up_v)
		right_v /= np.linalg.norm(right_v)
		up_v = np.cross(right_v, d)

		# Frame from the actual extent projected onto this view's screen axes.
		sub = np.vstack([m["verts"] for m in shown])
		sub_center = (sub.max(0) + sub.min(0)) / 2
		half_w = np.abs((sub - sub_center) @ right_v).max()
		half_h = np.abs((sub - sub_center) @ up_v).max()
		aspect = size[0] / size[1]
		scale = max(half_h, half_w / aspect) * 1.08

		cam = ren.GetActiveCamera()
		cam.SetFocalPoint(*sub_center)
		cam.SetPosition(*(sub_center - d * radius * 4.0))
		cam.SetViewUp(*up)
		cam.SetParallelProjection(True)
		cam.SetParallelScale(scale)
		ren.ResetCameraClippingRange()

		rw = vtk.vtkRenderWindow()
		rw.SetOffScreenRendering(1)
		rw.SetAlphaBitPlanes(True)
		rw.SetMultiSamples(0)          # required for depth peeling
		rw.AddRenderer(ren)
		rw.SetSize(*size)
		rw.Render()

		w2i = vtk.vtkWindowToImageFilter()
		w2i.SetInput(rw)
		w2i.Update()
		vtk_img = w2i.GetOutput()
		w, h, _ = vtk_img.GetDimensions()
		arr = numpy_support.vtk_to_numpy(vtk_img.GetPointData().GetScalars())
		tiles.append(crop_to_content(arr.reshape(h, w, -1)[::-1]))
		rw.Finalize()

	# 2x2 grid; imshow preserves each cropped tile's aspect inside its cell.
	fig, axes = plt.subplots(2, 2, figsize=(13, 10))
	for ax, tile, (name, _, _, _) in zip(axes.ravel(), tiles, VIEWS):
		ax.imshow(tile)
		ax.set_title(name, fontsize=12, pad=6)
		ax.axis("off")
	handles = [plt.Line2D([], [], marker="s", ls="", markersize=12,
						  color=m["color"], label=m["label"]) for m in meshes]
	fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=12)
	fig.suptitle(title, fontsize=15)
	fig.tight_layout(rect=[0, 0.05, 1, 0.965])
	fig.savefig(out_path, dpi=105, bbox_inches="tight", facecolor="white")
	plt.close(fig)


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--seg-dir", default="data/seg", type=Path)
	ap.add_argument("--out-dir", default="data/mesh", type=Path)
	ap.add_argument("--target-triangles", default=60000, type=int)
	ap.add_argument("--smooth-sigma", default=1.0, type=float)
	args = ap.parse_args()
	args.out_dir.mkdir(parents=True, exist_ok=True)

	meshes, report = [], []
	for name, label, color in STRUCTURES:
		path = args.seg_dir / f"{name}.nii.gz"
		if not path.exists():
			print(f"skip (not found): {path}")
			continue

		mask, spacing, origin = load_mask(path)
		n_vox = int(mask.sum())
		if n_vox == 0:
			print(f"skip (empty mask): {name}")
			continue
		mask = largest_component(mask)
		volume_ml = n_vox * float(np.prod(spacing)) / 1000.0

		verts, faces = mask_to_mesh(mask, spacing, origin, args.smooth_sigma)
		poly = refine(to_vtk(verts, faces), args.target_triangles)
		verts, faces = from_vtk(poly)

		stl = args.out_dir / f"{name}.stl"
		write_stl(poly, stl)

		# minimus sits deep to medius, so draw it opaque and medius translucent
		alpha = 1.0 if "minimus" in name else 0.35
		meshes.append(dict(verts=verts, faces=faces, poly=poly, color=color,
						   alpha=alpha, label=label,
						   side="left" if name.endswith("_left") else "right"))
		report.append(dict(structure=name, label=label, voxels=n_vox,
						   volume_ml=round(volume_ml, 1), triangles=len(faces),
						   stl=str(stl)))
		print(f"{label:<12} {volume_ml:7.1f} mL  {len(faces):>6d} triangles  -> {stl}")

	if not meshes:
		raise SystemExit("no masks found in " + str(args.seg_dir))

	png = args.out_dir / "gluteal_muscles_3d.png"
	render(meshes, png, "小殿筋・中殿筋 3D reconstruction")
	(args.out_dir / "volumes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
	print(f"\nrender  -> {png}")
	print(f"volumes -> {args.out_dir / 'volumes.json'}")


if __name__ == "__main__":
	main()
