"""Reproducible, data-derived grant figures. No generative image processing."""
from pathlib import Path
import json
import sys
import numpy as np
import SimpleITK as sitk
import vtk
from vtk.util import numpy_support as ns
from scipy import ndimage
from skimage import measure
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure'
BASE=Path(r'C:\Users\a2189\Dropbox\Hip_cross-sectional_area\output')
OUT=ROOT/'deliverables'; OUT.mkdir(exist_ok=True)
CT_OUT=OUT
WITH_HAM='--hamstrings-reference' in sys.argv
if WITH_HAM:
    OUT=OUT/'hamstrings_reference'; OUT.mkdir(exist_ok=True)
CACHE=ROOT/'mesh_cache'; CACHE.mkdir(exist_ok=True)
COLORS={'bone':(0.88,0.86,0.80),'medius':(0.20,0.48,0.73),'minimus':(0.87,0.31,0.23),'context':(0.61,0.64,0.67)}

def mesh(name,path,label=None):
    cache=CACHE/(name+'.vtp')
    if cache.exists():
        reader=vtk.vtkXMLPolyDataReader();reader.SetFileName(str(cache));reader.Update();return reader.GetOutput()
    im=sitk.ReadImage(str(path));a=sitk.GetArrayFromImage(im)
    mask=a>0 if label is None else np.isin(a,label)
    cc,n=ndimage.label(mask)
    sizes=np.bincount(cc.ravel());sizes[0]=0
    # Retain meaningful components for grouped bilateral/context muscles.
    mask=np.isin(cc,np.where(sizes>max(100,sizes.max()*.008))[0])
    if not mask.any(): return None
    smooth=ndimage.gaussian_filter(mask.astype(np.float32),sigma=(.7,1.,1.))
    v,f,_,_=measure.marching_cubes(smooth,.5)
    xyz=v[:,::-1]*np.array(im.GetSpacing())
    xyz=xyz@np.array(im.GetDirection()).reshape(3,3).T+np.array(im.GetOrigin())
    pts=vtk.vtkPoints();pts.SetData(ns.numpy_to_vtk(xyz,deep=True))
    cells=np.column_stack([np.full(len(f),3,dtype=np.int64),f]).astype(np.int64)
    tris=vtk.vtkCellArray();tris.SetCells(len(f),ns.numpy_to_vtkIdTypeArray(cells.ravel(),deep=True))
    p=vtk.vtkPolyData();p.SetPoints(pts);p.SetPolys(tris)
    sm=vtk.vtkWindowedSincPolyDataFilter();sm.SetInputData(p);sm.SetNumberOfIterations(25);sm.SetPassBand(.06);sm.BoundarySmoothingOff();sm.NormalizeCoordinatesOn();sm.Update()
    dec=vtk.vtkDecimatePro();dec.SetInputConnection(sm.GetOutputPort());dec.SetTargetReduction(max(0,1-65000/len(f)));dec.PreserveTopologyOn();dec.Update()
    norm=vtk.vtkPolyDataNormals();norm.SetInputConnection(dec.GetOutputPort());norm.SplittingOff();norm.ConsistencyOn();norm.AutoOrientNormalsOn();norm.Update()
    p=norm.GetOutput()
    writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(cache));writer.SetInputData(p);writer.Write()
    return p

def render(entries,view,size=(1500,1800)):
    ren=vtk.vtkRenderer();ren.SetBackground(1,1,1);ren.SetUseDepthPeeling(True);ren.SetMaximumNumberOfPeels(100);ren.SetOcclusionRatio(.05)
    for poly,kind in entries:
        if poly is None: continue
        mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(poly);mapper.ScalarVisibilityOff()
        actor=vtk.vtkActor();actor.SetMapper(mapper)
        p=actor.GetProperty();p.SetColor(*COLORS[kind]);p.SetOpacity(.82 if kind=='medius' else 1.)
        p.SetInterpolationToPhong();p.SetAmbient(.24);p.SetDiffuse(.78);p.SetSpecular(.16);p.SetSpecularPower(25)
        ren.AddActor(actor)
    verts=np.vstack([ns.vtk_to_numpy(p.GetPoints().GetData()) for p,k in entries if p is not None])
    low,high=verts.min(0),verts.max(0);center=(low+high)/2
    direction=np.array((0,-1,.02) if view=='anterior' else (0,1,.02),float);direction/=np.linalg.norm(direction)
    cam=ren.GetActiveCamera();cam.SetFocalPoint(*center);cam.SetPosition(*(center+direction*1500));cam.SetViewUp(0,0,1);cam.ParallelProjectionOn()
    cam.SetParallelScale(max((high[2]-low[2])/2,(high[0]-low[0])/2/(size[0]/size[1]))*1.07)
    ren.ResetCameraClippingRange()
    rw=vtk.vtkRenderWindow();rw.SetOffScreenRendering(1);rw.SetAlphaBitPlanes(1);rw.SetMultiSamples(0);rw.AddRenderer(ren);rw.SetSize(*size);rw.Render()
    w=vtk.vtkWindowToImageFilter();w.SetInput(rw);w.SetInputBufferTypeToRGB();w.ReadFrontBufferOff();w.Update()
    a=ns.vtk_to_numpy(w.GetOutput().GetPointData().GetScalars()).reshape(size[1],size[0],3)[::-1].copy();rw.Finalize()
    return Image.fromarray(a)

def font(size,bold=False):
    return ImageFont.truetype(str(Path('C:/Windows/Fonts')/('meiryob.ttc' if bold else 'meiryo.ttc')),size)

def textcenter(d,xy,txt,size=40,bold=False,color='#1d2730'):
    d.text(xy,txt,font=font(size,bold),fill=color,anchor='mt')

def compose(front,back):
    # Panels deliberately avoid patient metadata; CT panels retain radiological orientation.
    w,h=3300,1700;can=Image.new('RGB',(w,h),'white');d=ImageDraw.Draw(can)
    textcenter(d,(455,30),'CT画像（3断面）',52,True)
    ct_names=['01_ilium','02_midpoint','03_greater_trochanter'];titles=['腸骨部','中間レベル','大転子頂部付近']
    for i,(name,title) in enumerate(zip(ct_names,titles)):
        y=120+i*500
        textcenter(d,(455,y),f'{i+1}  {title}',37)
        tile=Image.open(CT_OUT/f'ct_{name}_plain.png').convert('RGB').resize((820,428),Image.Resampling.LANCZOS)
        can.paste(tile,(45,y+52))
        d.text((62,y+65),'R',font=font(28),fill='white');d.text((822,y+65),'L',font=font(28),fill='white')
    # Quiet, compact workflow arrow.
    d.polygon([(940,730),(1100,730),(1100,668),(1215,805),(1100,942),(1100,880),(940,880)],fill='#eef1f3',outline='#59646e',width=5)
    textcenter(d,(1058,748),'AIによる',32,True);textcenter(d,(1058,795),'筋抽出',32,True)
    textcenter(d,(2250,30),'股関節周囲筋の三次元表示',52,True)
    for x,label,img in [(1250,'前面',front),(2260,'後面',back)]:
        textcenter(d,(x+500,114),label,39)
        img=img.resize((1000,1200),Image.Resampling.LANCZOS);can.paste(img,(x,180))
    legend=[('中殿筋','medius'),('小殿筋','minimus'),('腸腰筋・ハムストリングス' if WITH_HAM else '腸腰筋','context')]
    for x,(label,kind) in zip([1320,1810,2310],legend):
        col=tuple(round(c*255) for c in COLORS[kind]);d.rectangle((x,1460,x+44,1504),fill=col);d.text((x+65,1454),label,font=font(34),fill='#1d2730')
    textcenter(d,(2250,1540),'参考版：ハムストリングスは部分抽出（近位部の抽出が不十分）' if WITH_HAM else '骨盤・大腿骨を位置関係の参照として表示',30,color='#59646e')
    can.save(OUT/'grant_workflow_CT_3D.png',dpi=(300,300))
    can.resize((1650,850),Image.Resampling.LANCZOS).save(OUT/'grant_workflow_preview.png')
    pair=Image.new('RGB',(3100,2050),'white');pd=ImageDraw.Draw(pair)
    pair.paste(front,(0,100));pair.paste(back,(1600,100));textcenter(pd,(750,10),'前面',52,True);textcenter(pd,(2350,10),'後面',52,True)
    for x,(label,kind) in zip([230,980,1720],legend):
        pd.rectangle((x,1940,x+55,1995),fill=tuple(round(c*255) for c in COLORS[kind]));pd.text((x+82,1935),label,font=font(43),fill='#1d2730')
    pair.save(OUT/'gluteal_context_3D_pair.png',dpi=(300,300))

def main():
    entries=[]
    for name in ['hip_left','hip_right','sacrum']:
        entries.append((mesh(name,BASE/f'seg/{name}.nii.gz'),'bone'))
    for name in ['femur_left','femur_right']:
        entries.append((mesh(name+'_extended' if WITH_HAM else name,ROOT/f'context_seg_extended/{name}.nii.gz' if WITH_HAM else BASE/f'seg/{name}.nii.gz'),'bone'))
    for kind in ['medius','minimus']:
        for side in ['left','right']:
            n=f'gluteus_{kind}_{side}';entries.append((mesh(n,BASE/f'seg/{n}.nii.gz'),kind))
    for side in ['left','right']:
        n=f'iliopsoas_{side}';entries.append((mesh(n,ROOT/f'context_seg/{n}.nii.gz'),'context'))
    mm=ROOT/'musclemap_seg/ct_pelvis_thigh_dseg.nii.gz'
    if WITH_HAM: assert mm.exists(), 'Hamstrings segmentation must exist before composing the labeled figure.'
    if WITH_HAM:
        for side,labels in [('left',[7161,7171,7181,7191]),('right',[7162,7172,7182,7192])]:
            entries.append((mesh('hamstrings_'+side,mm,labels),'context'))
    front=render(entries,'anterior');back=render(entries,'posterior')
    front.save(OUT/'gluteal_context_anterior.png',dpi=(300,300));back.save(OUT/'gluteal_context_posterior.png',dpi=(300,300))
    compose(front,back)
    print('Saved grant figures to',OUT)

if __name__=='__main__': main()
