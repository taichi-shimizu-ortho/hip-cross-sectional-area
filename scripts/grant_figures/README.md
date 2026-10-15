# Grant figure generation

Source for the CT / anterior-posterior 3D figure and its editable one-slide
PowerPoint. Patient-derived images, PPTX files, masks, model weights and temporary
dependencies stay in ignored `tmp/` and `output/` directories or the local Dropbox
project. Do not commit them.

These scripts preserve the local study workflow. Input locations, slice selection
and Windows font/runtime paths are specific to this workstation and dataset;
review them before applying the workflow to another scan.

## Local workflow

Run from the repository root with the existing imaging Python environment
(SimpleITK, pydicom, NumPy, SciPy, scikit-image, VTK, Pillow, TotalSegmentator).

1. `python scripts/grant_figures/export_ct.py` exports three plain CT panels,
   checks their HU values against the source DICOM, and prepares the extended crop.
2. `python scripts/grant_figures/segment_context.py` extracts iliopsoas using
   TotalSegmentator's free `total` task. The optional `--extended` extracts femurs
   for the longer reference view.
3. `python scripts/grant_figures/render_figure.py` renders the main figure from
   existing gluteal/bone masks and the additional iliopsoas masks.
4. Run `scripts/grant_figures/build_ppt.mjs` using the bundled artifact-tool Node
   runtime. Set `RUNTIME_NODE_MODULES` to its package directory. The script creates
   the editable deck and validates it with the installed Presentations utilities.
   Its final output must be a new filename if re-running the finalizer.

CT images and 3D views are independent embedded images in the PPTX. Text, arrow,
orientation markers and legend swatches are native editable objects. The 3D views
are rendered images, not interactive 3D models.

## Thigh version (hamstrings and adductors)

Needs `output/seg_thigh/` from the README's optional thigh step (TotalSegmentator
`thigh_shoulder_muscles`, licensed, plus `total` for the whole femur and iliopsoas).
Compartments, not single muscles: posterior = hamstrings, medial = adductors.
Runs on macOS with the project environment:

    uv run python scripts/grant_figures/render_figure.py --thigh --ct-dir <dir with ct_*_plain.png> --out <dir>
    uv run --with python-pptx python scripts/grant_figures/update_ppt.py --images <same dir>

`update_ppt.py` edits the hand-edited `output/grant figure.pptx` in place: it swaps
the two 3D pictures, rebuilds the legend and replaces the note line, and keeps a
copy of the previous deck in the image folder. The proximal tendinous part of the
hamstrings is not included in the compartment masks.

## Optional hamstrings reference

MuscleMap wholebody v1.4 was evaluated locally using its MIT-licensed model:
https://github.com/MuscleMap/MuscleMap and https://zenodo.org/records/21929873.
Place its segmentation at
`tmp/grant_figure/musclemap_seg/ct_pelvis_thigh_dseg.nii.gz`, then run
`qc_context.py` and `render_figure.py --hamstrings-reference`.

The proximal hamstrings were incompletely extracted in this scan. The main figure
therefore omits them. The separate reference figure explicitly labels the partial
extraction. Do not interpret automatically extracted voxel counts as validated
muscle volumes. The scripts do not interpolate missing anatomy.

The layout refers to Iwasa et al., Hip Joint 2025;51:51–55. The paper's image is not
copied; all anatomy views derive from the local CT. Study landmarks and automated
contours require researcher review before submission.
