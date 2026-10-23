# Hip Cross-Sectional Area & 3D Reconstruction Pipeline

A pipeline for segmenting gluteal muscles (gluteus medius, minimus, and maximus) from pelvic CT scans, calculating cross-sectional area (CSA) and volume, and building interactive 3D surface meshes.

This tool uses [TotalSegmentator](https://github.com/wasserth/TotalSegmentator) for automated anatomical segmentation and provides downstream scripts for quantitative muscle analysis and 3D visualization.

## Features

- **Automated Segmentation**: Uses TotalSegmentator to segment gluteal muscles and pelvic bones from CT series.
- **Cross-Sectional Area (CSA)**: Calculates the CSA profile of each muscle. Measurements are anchored to a reproducible anatomical landmark (the apex of the femoral head) to ensure consistency between subjects without picking slices by hand.
- **3D Surface Reconstruction**: Generates smoothed STL meshes from the segmentation masks and renders standard anatomical views.
- **Interactive 3D Viewer**: Builds a self-contained, patient-safe local HTML viewer for inspecting the 3D reconstructed anatomy.

## Setup

This project uses `uv` for Python environment management.

### Installation

Run `uv sync` to create a `.venv` with Python 3.11 and install all dependencies pinned in `uv.lock`. You can then run scripts using `uv run python <script>.py`.

PyTorch is selected automatically based on your platform:
- **macOS (Apple Silicon)**: Uses the official PyPI build with Metal (MPS) acceleration.
- **Linux / Windows**: Uses the CUDA 12.8 build.

*Note for macOS users*: The scripts pick the device in the order CUDA > MPS > CPU. Apple's MPS backend does not support mixed precision the way CUDA does, so do not use `--amp`.

## Data Management

**Patient data must never be committed to the repository.**
By default, the code expects data to be located in a Dropbox folder outside this repository (configured in [`hip_paths.py`](hip_paths.py)).

```
~/Dropbox/Hip_cross-sectional_area/
├── input/
│   └── sampleDATA/          DICOM series (read only)
└── output/
    ├── ct.nii.gz            whole series as NIfTI
    ├── ct_pelvis.nii.gz     cropped to the gluteal region
    ├── seg/                 TotalSegmentator masks
    ├── seg_thigh/           thigh compartments + whole femur (full-length CT)
    ├── mesh/                STL, rendered views, volumes.json
    ├── area/                CSA profile, summary, figures
    └── viewer.html          interactive 3D viewer
```

All scripts read and write from these paths by default. You can override them by passing arguments like `--seg-dir` and `--out-dir`.

## Workflow

### JOA study settings

To record the JOA application's cohort and sample-size settings before analyzing
clinical spreadsheets, run:

```bash
uv run python configure_joa_study.py
```

The script reads the single `JOA*.docx` in `input/` (or `--application PATH`),
checks the application's original settings, and independently reproduces the
two-sample t-test sample size. The authoritative English analysis plan is saved
as `input/joa_analysis_plan.json`, with a summary in `output/joa/study_setup.md`.
The plan records the user-amended period of 2016-11-01 through 2026-10-31 and
age/sex matching without BMI. Unspecified outcome-analysis choices remain unset.
Use `--check-only` to validate without writing files. Source documents and
workbooks are never modified.

Export the workbook before cleaning it (the extraction script additionally
needs `openpyxl`; the bundled artifact runtime already provides it):

```bash
uv run --with openpyxl python excel_to_json.py raw
uv run --with openpyxl python excel_to_json.py clean \
  --clean-json ~/Dropbox/Hip_cross-sectional_area/output/joa/surgery_schedule.normalized.json
uv run python match_joa_cohorts.py --check-only
uv run python match_joa_cohorts.py
```

Raw/normalized JSON exports are preserved. The final `surgery_schedule.cleaned.json`
contains explicit hip-site records within the requested period. Ambiguous rows
and exclusion references are retained in `hip_cases.review.json`. Propensity
scores, pairs and balance diagnostics are in `cohort_matching.json`, with methods
and limitations in `matching_report.md`. Matching is provisional until clinical
eligibility and surgery completion have been checked. The matching script uses
one index operation per identified patient, exact sex, a 0.2 SD logit caliper,
and matching without replacement within sex-specific common support.

### 1. DICOM to NIfTI Conversion

Convert the input DICOM series into a NIfTI volume and crop it to the gluteal region. The crop range is specific to the series—pick it from the CT so it spans the iliac crest down past the greater trochanter.

```bash
uv run python - <<'EOF'
import SimpleITK as sitk
import hip_paths as P
P.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
r = sitk.ImageSeriesReader(); r.SetFileNames(r.GetGDCMSeriesFileNames(str(P.DICOM_DIR)))
img = r.Execute(); sitk.WriteImage(img, str(P.CT), useCompression=True)
# Example crop:
sitk.WriteImage(img[:, :, 680:940], str(P.CT_PELVIS), useCompression=True)
EOF
```

### 2. Segmentation with TotalSegmentator

Segment the muscles and bones. On the first run, this will download the pre-trained weights (~880 MB).

```bash
OUT=~/Dropbox/Hip_cross-sectional_area/output

# Segment gluteal muscles and reference bones
PYTORCH_ENABLE_MPS_FALLBACK=1 uv run TotalSegmentator \
  -i "$OUT/ct_pelvis.nii.gz" -o "$OUT/seg" -d mps -s -sx \
  -rs gluteus_medius_left gluteus_medius_right \
      gluteus_minimus_left gluteus_minimus_right \
      gluteus_maximus_left gluteus_maximus_right \
      hip_left hip_right sacrum femur_left femur_right

# Optional: thigh compartments and the whole femur, on the full-length CT
PYTORCH_ENABLE_MPS_FALLBACK=1 uv run TotalSegmentator \
  -i "$OUT/ct.nii.gz" -o "$OUT/seg_thigh" -d mps -ta thigh_shoulder_muscles
PYTORCH_ENABLE_MPS_FALLBACK=1 uv run TotalSegmentator \
  -i "$OUT/ct.nii.gz" -o "$OUT/seg_thigh" -d mps -rs femur_left femur_right
```

The `thigh_shoulder_muscles` task needs a TotalSegmentator license (free for non-commercial use; register it with `totalseg_set_license -l <number>`). It segments compartments rather than individual muscles: `thigh_posterior_compartment` is the hamstrings, `thigh_medial_compartment` the adductors. Quadriceps femoris and sartorius come with it. If `seg_thigh/` is absent, the later steps simply skip the thigh.

> **Hardware acceleration**: Use `-d mps` on Apple Silicon, `-d gpu` on a CUDA machine, or `-d cpu` if no accelerator is available. Note that `PYTORCH_ENABLE_MPS_FALLBACK=1` is required for TotalSegmentator to run successfully on macOS.

### 3. 3D Mesh Reconstruction

Convert the segmentation masks into smoothed 3D surface meshes (STLs) and render standard anatomical views.

```bash
uv run python reconstruct_3d.py
```

Outputs are saved in `output/mesh/`, including the individual `.stl` files and static PNG renders from multiple angles (`gluteal_muscles_3d.png`, plus `hip_thigh_muscles_3d.png` when thigh masks exist).

### 4. Interactive 3D Viewer

Generate a self-contained, interactive HTML 3D viewer for the reconstructed anatomy.

```bash
uv run python make_viewer.py
```

This builds `output/viewer.html`. You can open this file in any web browser to interactively inspect the 3D meshes. The geometry is embedded securely within the file, and patient data never leaves your machine.

### 5. Quantitative Area & Volume Measurement

Calculate the cross-sectional area (CSA) and 3D volume for each segmented muscle.

```bash
uv run python measure_area.py
```

`measure_area.py` outputs a per-slice CSA profile (`csa_profile.csv`), a JSON summary (`area_summary.json`), and visualization plots to `output/area/`. By default, it reports the CSA at the apex of the femoral head (read automatically from the femur masks) to ensure consistent craniocaudal leveling. Pass `--level <slice_index>` to measure at a manual height instead.

Note that a muscle running past the edge of the crop is truncated: its CSA is still valid, its volume is not. Gluteus maximus is often cut off inferiorly for exactly this reason.

---

**Research use only — not for diagnosis.** The masks are model output and have not been reviewed by a clinician. Patient data lives in the Dropbox folder above, outside the repository; `sampleDATA/` and `data/` stay gitignored in case a stray copy lands here.
