import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import SimpleITK as sitk
import vtk
from scipy import ndimage
from skimage import measure
from vtk.util import numpy_support

import hip_paths

MEDIUS_COLOR = "#3d7ff2"
MINIMUS_COLOR = "#e8543f"
BONE_COLOR = "#ddd2bd"

MUSCLES = [
	("gluteus_minimus_left", "Gluteus minimus L", MINIMUS_COLOR),
	("gluteus_minimus_right", "Gluteus minimus R", MINIMUS_COLOR),
	("gluteus_medius_left", "Gluteus medius L", MEDIUS_COLOR),
	("gluteus_medius_right", "Gluteus medius R", MEDIUS_COLOR),
]

BONES = [
	("hip_left", "Hip bone L", BONE_COLOR),
	("hip_right", "Hip bone R", BONE_COLOR),
	("sacrum", "Sacrum", BONE_COLOR),
	("femur_left", "Femur L", BONE_COLOR),
	("femur_right", "Femur R", BONE_COLOR),
]

def load_mask(path):
	img = sitk.ReadImage(str(path))
	arr = sitk.GetArrayFromImage(img).astype(np.uint8)
	sx, sy, sz = img.GetSpacing()
	return arr > 0, (sz, sy, sx), img.GetOrigin()

def largest_component(mask):
	lab, n = ndimage.label(mask)
	if n <= 1:
		return mask
	sizes = ndimage.sum(mask, lab, range(1, n + 1))
	return lab == (int(np.argmax(sizes)) + 1)

def mask_to_mesh(mask, spacing, origin, smooth_sigma=1.0):
	vol = ndimage.gaussian_filter(mask.astype(np.float32), sigma=smooth_sigma)
	verts, faces, _, _ = measure.marching_cubes(vol, level=0.5, spacing=spacing)
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

def refine(poly, target_triangles=60000, smooth_iterations=30):
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

def render_single_view(meshes, out_path, title, direction, up, size=(1600, 1600)):
	allv = np.vstack([m["verts"] for m in meshes])
	center = (allv.max(0) + allv.min(0)) / 2
	radius = np.linalg.norm(allv.max(0) - allv.min(0)) / 2

	ren = vtk.vtkRenderer()
	ren.SetBackground(1, 1, 1)
	ren.SetUseDepthPeeling(True)
	ren.SetMaximumNumberOfPeels(12)
	ren.SetOcclusionRatio(0.0)

	for m in meshes:
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

	sub_center = center
	half_w = np.abs((allv - sub_center) @ right_v).max()
	half_h = np.abs((allv - sub_center) @ up_v).max()
	aspect = size[0] / size[1]
	scale = max(half_h, half_w / aspect) * 1.08

	cam = ren.GetActiveCamera()
	cam.SetFocalPoint(*sub_center)
	cam.SetPosition(*(sub_center + d * radius * 4.0))
	cam.SetViewUp(*up)
	cam.SetParallelProjection(True)
	cam.SetParallelScale(scale)
	ren.ResetCameraClippingRange()

	rw = vtk.vtkRenderWindow()
	rw.SetOffScreenRendering(1)
	rw.SetAlphaBitPlanes(True)
	rw.SetMultiSamples(0)
	rw.AddRenderer(ren)
	rw.SetSize(*size)
	rw.Render()

	w2i = vtk.vtkWindowToImageFilter()
	w2i.SetInput(rw)
	w2i.Update()
	vtk_img = w2i.GetOutput()
	w, h, _ = vtk_img.GetDimensions()
	arr = numpy_support.vtk_to_numpy(vtk_img.GetPointData().GetScalars())
	tile = arr.reshape(h, w, -1)[::-1]
	
	bg = 250
	ink = (tile[:, :, :3].min(axis=2) < bg)
	margin = 40
	if ink.any():
		rows, cols = np.where(ink.any(1))[0], np.where(ink.any(0))[0]
		r0, r1 = max(rows[0] - margin, 0), min(rows[-1] + margin + 1, tile.shape[0])
		c0, c1 = max(cols[0] - margin, 0), min(cols[-1] + margin + 1, tile.shape[1])
		tile = tile[r0:r1, c0:c1]

	rw.Finalize()

	fig, ax = plt.subplots(figsize=(10, 10))
	ax.imshow(tile)
	ax.axis("off")
	
	handles = [
		plt.Line2D([], [], marker="s", ls="", markersize=15, color=MEDIUS_COLOR, label="Gluteus Medius"),
		plt.Line2D([], [], marker="s", ls="", markersize=15, color=MINIMUS_COLOR, label="Gluteus Minimus")
	]
	fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=16)
	fig.tight_layout(rect=[0, 0.08, 1, 1])
	fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
	plt.close(fig)

def main():
	seg_dir = hip_paths.SEG_DIR
	out_dir = hip_paths.OUTPUT_DIR / "grant_images"
	out_dir.mkdir(parents=True, exist_ok=True)

	meshes = []
	for kind, group in (("muscle", MUSCLES), ("bone", BONES)):
		for name, label, color in group:
			path = seg_dir / f"{name}.nii.gz"
			if not path.exists():
				print(f"skip (not found): {path}")
				continue

			mask, spacing, origin = load_mask(path)
			n_vox = int(mask.sum())
			if n_vox == 0:
				continue
			mask = largest_component(mask)

			verts, faces = mask_to_mesh(mask, spacing, origin, 1.0)
			poly = refine(to_vtk(verts, faces), 60000)
			verts, faces = from_vtk(poly)

			alpha = 0.4 if "medius" in name else 1.0
			meshes.append(dict(verts=verts, faces=faces, poly=poly, color=color, alpha=alpha, label=label))
			print(f"Processed {name}")

	if not meshes:
		print("No meshes to render.")
		return

	png1 = out_dir / "gluteal_muscles_posterior.png"
	render_single_view(meshes, png1, "Posterior View", direction=(0, 1, 0.1), up=(0, 0, 1))
	print(f"Saved {png1}")

	png2 = out_dir / "gluteal_muscles_anterior.png"
	render_single_view(meshes, png2, "Anterior View", direction=(0, -1, -0.1), up=(0, 0, 1))
	print(f"Saved {png2}")

if __name__ == "__main__":
	main()
