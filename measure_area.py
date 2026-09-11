"""Measure gluteal muscle cross-sectional area (CSA) from TotalSegmentator masks.

Counts the mask voxels on every axial slice and scales them by the in-plane
pixel area, so each slice gives a CSA in cm^2. The craniocaudal reference level
is taken from the bone masks (apex of the femoral head), which makes the
measurement reproducible between subjects without hand-picking a slice.

    uv run python measure_area.py --seg-dir data/seg --ct data/ct_pelvis.nii.gz

Writes a per-slice CSV profile, a summary JSON, a CSA-versus-level plot and an
overlay of the reference slice.
"""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import SimpleITK as sitk

# (file stem, display name, colour) — same colours as the 3D reconstruction.
MUSCLES = [
	("gluteus_maximus_left", "Gluteus maximus L", "#8e6fd8"),
	("gluteus_maximus_right", "Gluteus maximus R", "#c86fd8"),
	("gluteus_medius_left", "Gluteus medius L", "#3d7ff2"),
	("gluteus_medius_right", "Gluteus medius R", "#3fbfae"),
	("gluteus_minimus_left", "Gluteus minimus L", "#e8543f"),
	("gluteus_minimus_right", "Gluteus minimus R", "#f2a03d"),
]


def side_of(name):
	return "left" if name.endswith("_left") else "right" if name.endswith("_right") else None


def load(path):
	img = sitk.ReadImage(str(path))
	return sitk.GetArrayFromImage(img), img


def femoral_head_apex(seg_dir, side):
	"""Most superior slice of the femur mask = apex of the femoral head."""
	path = seg_dir / f"femur_{side}.nii.gz"
	if not path.exists():
		return None
	arr, _ = load(path)
	z = np.where((arr > 0).any(axis=(1, 2)))[0]
	return int(z.max()) if len(z) else None


def main():
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--seg-dir", default="data/seg", type=Path)
	ap.add_argument("--ct", default="data/ct_pelvis.nii.gz", type=Path)
	ap.add_argument("--out-dir", default="data/area", type=Path)
	ap.add_argument("--level", type=int, default=None,
					help="slice index of the reference level; default is the femoral head apex")
	args = ap.parse_args()
	args.out_dir.mkdir(parents=True, exist_ok=True)

	ct_arr, ct_img = load(args.ct)
	sx, sy, sz = ct_img.GetSpacing()
	pixel_area_mm2 = sx * sy
	z0 = ct_img.GetOrigin()[2]
	n_slices = ct_arr.shape[0]

	apex = {s: femoral_head_apex(args.seg_dir, s) for s in ("left", "right")}
	found = [v for v in apex.values() if v is not None]
	if args.level is not None:
		ref = {"left": args.level, "right": args.level}
	elif found:
		ref = {s: (v if v is not None else int(round(np.mean(found)))) for s, v in apex.items()}
	else:
		raise SystemExit("no femur mask for the reference level; pass --level")

	profiles, summary = {}, []
	for name, label, color in MUSCLES:
		path = args.seg_dir / f"{name}.nii.gz"
		if not path.exists():
			print(f"skip (not found): {path}")
			continue
		arr, _ = load(path)
		mask = arr > 0
		counts = mask.sum(axis=(1, 2))
		csa = counts * pixel_area_mm2 / 100.0          # cm^2 per slice
		profiles[name] = csa

		z_idx = np.where(counts > 0)[0]
		peak = int(np.argmax(csa))
		side = side_of(name)
		level = int(np.clip(ref[side], 0, n_slices - 1))
		hu = ct_arr[level][mask[level]]

		summary.append(dict(
			structure=name, label=label, side=side, color=color,
			csa_at_reference_cm2=round(float(csa[level]), 2),
			peak_csa_cm2=round(float(csa[peak]), 2),
			peak_offset_mm=round(float((peak - level) * sz), 1),
			mean_csa_cm2=round(float(csa[z_idx].mean()), 2),
			volume_ml=round(float(counts.sum() * pixel_area_mm2 * sz / 1000.0), 1),
			length_mm=round(float(len(z_idx) * sz), 1),
			mean_hu_at_reference=round(float(hu.mean()), 1) if hu.size else None,
			reference_slice=level,
		))
		print(f"{label:<20} CSA@ref {csa[level]:6.2f} cm2   peak {csa[peak]:6.2f} cm2"
			  f"   volume {counts.sum() * pixel_area_mm2 * sz / 1000.0:7.1f} mL")

	if not profiles:
		raise SystemExit("no muscle masks found in " + str(args.seg_dir))

	# Per-slice profile, one row per slice.
	csv_path = args.out_dir / "csa_profile.csv"
	with csv_path.open("w", newline="") as f:
		w = csv.writer(f)
		w.writerow(["slice", "z_mm", "offset_from_reference_mm"] + list(profiles))
		for i in range(n_slices):
			w.writerow([i, round(z0 + i * sz, 1), round((i - ref["left"]) * sz, 1)]
					   + [round(float(p[i]), 3) for p in profiles.values()])

	meta = dict(
		ct=str(args.ct), seg_dir=str(args.seg_dir),
		voxel_mm=[round(sx, 4), round(sy, 4), round(sz, 4)],
		pixel_area_mm2=round(pixel_area_mm2, 4),
		reference="femoral head apex" if args.level is None else "manual slice",
		reference_slice=ref, muscles=summary,
	)
	(args.out_dir / "area_summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

	# CSA against craniocaudal level, zeroed on the reference slice.
	fig, ax = plt.subplots(figsize=(9, 5.2))
	for name, label, color in MUSCLES:
		if name not in profiles:
			continue
		offset = (np.arange(n_slices) - ref[side_of(name)]) * sz
		ax.plot(offset, profiles[name], color=color, lw=1.8,
				ls="--" if name.endswith("_right") else "-", label=label)
	ax.axvline(0, color="#444", lw=1, ls=":")
	ax.annotate("reference level\n(femoral head apex)", xy=(0, 0.5), xycoords=("data", "axes fraction"),
				xytext=(6, 0), textcoords="offset points", fontsize=9, color="#444")
	ax.set_xlabel("craniocaudal level relative to the femoral head apex (mm)")
	ax.set_ylabel("cross-sectional area (cm$^2$)")
	ax.set_title("Gluteal muscle CSA profile")
	ax.grid(alpha=0.25)
	fig.legend(loc="lower center", ncol=3, frameon=False, fontsize=9)
	fig.tight_layout(rect=[0, 0.13, 1, 1])
	fig.savefig(args.out_dir / "csa_profile.png", dpi=130, facecolor="white")
	plt.close(fig)

	# The reference slice itself, with the masks outlined on the CT.
	level = ref["left"]
	ct_slice = ct_arr[level]
	body = ct_slice > -500                              # trim the air around the patient
	rows, cols = np.where(body.any(1))[0], np.where(body.any(0))[0]
	r0, r1 = max(rows[0] - 8, 0), min(rows[-1] + 9, ct_slice.shape[0])
	c0, c1 = max(cols[0] - 8, 0), min(cols[-1] + 9, ct_slice.shape[1])

	by_name = {m["structure"]: m for m in summary}
	# Size the figure to the crop so the slice is not letterboxed, plus room for the legend.
	fig_w = 8.0
	fig, ax = plt.subplots(figsize=(fig_w, fig_w * (r1 - r0) / (c1 - c0) + 1.5))
	ax.imshow(ct_slice[r0:r1, c0:c1], cmap="gray", vmin=-160, vmax=240)
	handles = []
	for name, label, color in MUSCLES:
		path = args.seg_dir / f"{name}.nii.gz"
		if not path.exists():
			continue
		arr, _ = load(path)
		lv = ref[side_of(name)]
		if (arr[lv] > 0).any():
			ax.contour(arr[lv][r0:r1, c0:c1] > 0, levels=[0.5], colors=[color], linewidths=1.6)
		handles.append(plt.Line2D([], [], color=color, lw=2.5,
								  label=f"{label}  {by_name[name]['csa_at_reference_cm2']:.2f} cm$^2$"))
	ax.set_title(f"Reference slice (femoral head apex, index {level}) — CSA per muscle", fontsize=12)
	ax.axis("off")
	fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=9)
	fig.tight_layout(rect=[0, 1.15 / (fig_w * (r1 - r0) / (c1 - c0) + 1.5), 1, 1])
	fig.savefig(args.out_dir / "csa_reference_slice.png", dpi=130, facecolor="white")
	plt.close(fig)

	print(f"\nprofile -> {csv_path}")
	print(f"summary -> {args.out_dir / 'area_summary.json'}")
	print(f"plots   -> {args.out_dir / 'csa_profile.png'}, {args.out_dir / 'csa_reference_slice.png'}")


if __name__ == "__main__":
	main()
