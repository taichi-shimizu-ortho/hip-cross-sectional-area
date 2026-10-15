from pathlib import Path
import json
import sys
import numpy as np
import SimpleITK as sitk
import pydicom
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import hip_paths

OUT=(Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure')/'deliverables'
OUT.mkdir(parents=True,exist_ok=True)
im=sitk.ReadImage(str(hip_paths.CT_PELVIS))
vol=sitk.GetArrayFromImage(im)
levels=[(150,'01_ilium','腸骨部（上前腸骨棘付近）'),(111,'02_midpoint','中間レベル'),(72,'03_greater_trochanter','大転子頂部付近')]
records=[]
for z,name,label in levels:
    xyz=im.TransformIndexToPhysicalPoint((0,0,z))
    # Series uses consecutive filenames, descending from z=-1057 mm.
    # Verify each selected file's physical coordinates and pixel values below.
    file_number=int(round(-1057-xyz[2]))+1
    f=hip_paths.DICOM_DIR/f'{file_number:06d}'
    ds=pydicom.dcmread(str(f))
    inst=ds.InstanceNumber
    assert abs(float(ds.ImagePositionPatient[2])-xyz[2])<.001
    pixels=ds.pixel_array.astype(np.float32)*float(ds.RescaleSlope)+float(ds.RescaleIntercept)
    diff=float(np.abs(pixels-vol[z]).max())
    assert diff==0, (f,diff)
    gray=np.uint8(np.clip((pixels+160)/400,0,1)*255)
    # Identical field of view for all panels; retain native pixels and body contour.
    # The posterior table is outside this fixed crop.
    Image.fromarray(gray[175:442,0:512]).save(OUT/f'ct_{name}_plain.png',dpi=(300,300))
    Image.fromarray(gray).save(OUT/f'ct_{name}_full.png',dpi=(300,300))
    records.append(dict(label=label,crop_slice_zero_based=z,full_volume_slice_zero_based=z+680,
                        dicom_filename=f.name,instance_number=int(inst),position_z_mm=xyz[2],
                        window_center_hu=40,window_width_hu=400,hu_max_difference_to_nifti=diff,
                        crop_xyxy=[0,175,512,442],orientation='radiological: patient right on image left'))
(OUT/'selected_ct_slices.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
volume_path=(Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure')/'ct_pelvis_thigh.nii.gz'
if not volume_path.exists():
    full=sitk.ReadImage(str(hip_paths.CT))
    sitk.WriteImage(full[:,:,560:940],str(volume_path),True)
print(json.dumps(records,ensure_ascii=False,indent=2))
