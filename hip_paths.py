"""Where this project's patient data lives.

Inputs and outputs are kept in Dropbox, outside the repository, so nothing
patient-derived can be committed. Every path is built from Path.home() so the
code carries no user-specific absolute path.

    DATA_ROOT   ~/Dropbox/Hip_cross-sectional_area, or $HIP_DATA_ROOT when set
                (on macOS ~/Dropbox is Dropbox's link to ~/Library/CloudStorage/Dropbox)
    INPUT_DIR   DATA_ROOT/input            DICOM series (read only)
    OUTPUT_DIR  DATA_ROOT/output           everything the pipeline writes
"""

import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("HIP_DATA_ROOT")
				 or Path.home() / "Dropbox" / "Hip_cross-sectional_area").expanduser()
INPUT_DIR = DATA_ROOT / "input"
OUTPUT_DIR = DATA_ROOT / "output"

DICOM_DIR = INPUT_DIR / "sampleDATA"
CT = OUTPUT_DIR / "ct.nii.gz"
CT_PELVIS = OUTPUT_DIR / "ct_pelvis.nii.gz"
SEG_DIR = OUTPUT_DIR / "seg"
SEG_THIGH_DIR = OUTPUT_DIR / "seg_thigh"   # full-length CT: thigh muscles, whole femur
MESH_DIR = OUTPUT_DIR / "mesh"
AREA_DIR = OUTPUT_DIR / "area"
VIEWER = OUTPUT_DIR / "viewer.html"
JOA_DIR = OUTPUT_DIR / "joa"              # study settings and clinical-data analysis
JOA_ANALYSIS_PLAN = INPUT_DIR / "joa_analysis_plan.json"


def from_home(path):
	"""Path as a string with the home directory shown as ~, for records written to disk."""
	path = Path(path).expanduser().absolute()
	try:
		return "~/" + path.relative_to(Path.home()).as_posix()
	except ValueError:
		return str(path)
