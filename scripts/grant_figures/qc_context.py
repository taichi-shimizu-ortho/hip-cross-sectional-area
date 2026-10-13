from pathlib import Path
import json
import numpy as np
import SimpleITK as sitk
from PIL import Image, ImageDraw,ImageFont

R=(Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure')
ct=sitk.ReadImage(str(R/'ct_pelvis_thigh.nii.gz'));a=sitk.GetArrayFromImage(ct)
mm=sitk.ReadImage(str(R/'musclemap_seg/ct_pelvis_thigh_dseg.nii.gz'))
assert mm.GetSize()==ct.GetSize()
assert np.allclose(mm.GetOrigin(),ct.GetOrigin())
assert np.allclose(mm.GetDirection(),ct.GetDirection())
seg=sitk.GetArrayFromImage(mm)
label_names={7161:'semimembranosus_left',7162:'semimembranosus_right',7171:'semitendinosus_left',7172:'semitendinosus_right',7181:'biceps_femoris_long_head_left',7182:'biceps_femoris_long_head_right',7191:'biceps_femoris_short_head_left',7192:'biceps_femoris_short_head_right'}
stats={};supp=R/'deliverables/supporting_data';supp.mkdir(exist_ok=True)
for label,name in label_names.items():
    mask=seg==label
    if mask.any():
        z,y,x=np.where(mask)
        stats[name]={'label':label,'voxels':int(mask.sum()),'z_index_range':[int(z.min()),int(z.max())],
                     'z_mm_range':[ct.TransformIndexToPhysicalPoint((0,0,int(z.min())))[2],ct.TransformIndexToPhysicalPoint((0,0,int(z.max())))[2]]}
for side in ['left','right']:
    labels=[k for k,v in label_names.items() if v.endswith(side)]
    mask=np.isin(seg,labels)
    im=sitk.GetImageFromArray(mask.astype(np.uint8));im.CopyInformation(ct);sitk.WriteImage(im,str(supp/f'hamstrings_{side}.nii.gz'),True)
zs=[20,60,100,125,145,165,192,231,270]
colors={7161:[230,50,60],7162:[230,50,60],7171:[50,210,80],7172:[50,210,80],7181:[50,140,250],7182:[50,140,250],7191:[230,160,30],7192:[230,160,30]}
panel=Image.new('RGB',(3*610,3*405),'white');d=ImageDraw.Draw(panel)
for i,z in enumerate(zs):
    g=np.uint8(np.clip((a[z]+160)/400,0,1)*255)
    rgb=np.repeat(g[...,None],3,axis=2)
    for k,c in colors.items():
        m=seg[z]==k;rgb[m]=np.uint8(.55*rgb[m]+.45*np.array(c))
    tile=Image.fromarray(rgb[165:455]).resize((600,340))
    x,y=(i%3)*610,(i//3)*405;panel.paste(tile,(x,y+40));d.text((x+10,y+8),f'z={z}, physical={ct.GetOrigin()[2]+z} mm',fill='black')
panel.save(R/'hamstrings_qc.png')
(R/'deliverables/segmentation_summary.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
print(json.dumps(stats,indent=2))
