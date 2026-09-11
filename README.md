![image_example](https://user-images.githubusercontent.com/65467285/185387844-6766e2ce-43e0-40e9-a380-9eb92a7239b8.png)

# Pytorch Bayesian UNet model for segmentation and uncertainty prediction 

> Derived from [tha-santacruz/BayesianUNet](https://github.com/tha-santacruz/BayesianUNet)
> (GPL-3.0). This copy adds a CT pipeline for the gluteal muscles; the upstream
> example images are not carried over, so the history is small.

This repository provides the well-known UNet model [[1]](#1) converted to a Bayesian UNet model.
This model has been coded using Pytorch. This code is a modified version of the original the original implementation of UNet model in Pytorch by milesial (https://github.com/milesial/Pytorch-UNet).
The model has been implemented using the Monte Carlo Dropout method [[2]](#2).
It consists of adding a dropout layer at the end of each convolution layer, which is used both during training and testing times.
This Bayesian model provides different scores (entropy and mutual information) that characterize uncertainty in predictions. 

## To set up the Python environment :

### With uv (recommended, works on Linux/Windows + macOS)
Run ```uv sync```. This creates a `.venv` with Python 3.11 and every dependency pinned in `uv.lock`,
then run scripts with ```uv run python train.py```.

PyTorch is selected per platform automatically:
- **Linux / Windows** : the CUDA 12.8 build from the `pytorch-cu128` index.
- **macOS (Apple Silicon)** : the official PyPI build, which uses the Metal (MPS) backend.

The scripts pick the device in the order CUDA > MPS > CPU, so no changes are needed on a Mac.
Note that Apple's MPS backend does not support mixed precision the way CUDA does — leave `--amp` off on macOS.

### Legacy instructions
1.	If you use conda, execute ```conda env create --name envname --file=environment.yml```. If you have a ResolvePackageNotFound error, edit the environment.yml file to place the mentionned packages under the pip section.
2.	If you use pip, execute ```pip3 install -r requirements.txt```
3.	Install pytorch by following the instructions of the Pytorch documentation : 		https://pytorch.org/get-started/locally/

## CT muscle segmentation (gluteus medius / minimus)

A separate pipeline from the Potsdam UNet above: it segments the gluteal muscles in a
CT series with TotalSegmentator and reconstructs them as 3D surface meshes.

```bash
# 1. DICOM series -> NIfTI, cropped to the gluteal region
uv run python - <<'EOF'
import SimpleITK as sitk
r = sitk.ImageSeriesReader(); r.SetFileNames(r.GetGDCMSeriesFileNames("sampleDATA"))
img = r.Execute(); sitk.WriteImage(img, "data/ct.nii.gz", useCompression=True)
sitk.WriteImage(img[:, :, 680:940], "data/ct_pelvis.nii.gz", useCompression=True)
EOF

# 2. segment (downloads pretrained weights on first run, ~880 MB)
PYTORCH_ENABLE_MPS_FALLBACK=1 uv run TotalSegmentator \
  -i data/ct_pelvis.nii.gz -o data/seg -d mps -s -sx \
  -rs gluteus_medius_left gluteus_medius_right \
      gluteus_minimus_left gluteus_minimus_right \
      hip_left hip_right sacrum femur_left femur_right

# 3. meshes + STL + rendered views (muscles in colour, bone as reference)
uv run python reconstruct_3d.py --seg-dir data/seg --out-dir data/mesh

# 4. interactive local viewer (data/mesh/viewer.html)
uv run python make_viewer.py
```

### Cross-sectional area

`measure_area.py` turns the same masks into cross-sectional areas. It counts the
mask voxels on every axial slice, scales them by the in-plane pixel area, and
reports each muscle at a reproducible craniocaudal level — the apex of the
femoral head, read from the femur mask, so no slice is picked by hand.

```bash
uv run python measure_area.py --seg-dir data/seg --ct data/ct_pelvis.nii.gz
```

Writes to `data/area/`: `csa_profile.csv` (CSA of every muscle on every slice),
`area_summary.json` (CSA at the reference level, peak CSA and its offset, mean
CSA, volume, craniocaudal length and mean HU per muscle), plus a CSA-versus-level
plot and an overlay of the reference slice. Pass `--level <slice>` to measure at
a different height.

Note that a muscle running past the edge of the crop is truncated: its CSA is
still valid, its volume is not. Gluteus maximus in the sample series is cut off
inferiorly for exactly this reason.

The crop range in step 1 is specific to this series — pick it from the CT so it spans
the iliac crest down past the greater trochanter.

The hip bones, sacrum and femurs are segmented purely as anatomical reference: they
show the origin on the gluteal surface of the ilium and the insertion on the greater
trochanter. The femurs are cut off by the inferior edge of the crop. In the viewer the
bone can be dimmed or switched off, and the lateral views isolate one side.

`-d mps` uses the Apple GPU; use `-d gpu` on a CUDA machine or `-d cpu` anywhere.

**Research use only — not for diagnosis.** The masks are model output and have not been
reviewed by a clinician. Patient data lives under `sampleDATA/` and `data/`, both
gitignored; keep it that way.

## To create tiles : 
1.	Create a "Potsdam_data/" directory in the BayesianUNet directory.
2.	Download the Potsdam Dataset (International Society for Photogrammetry and Remote Sensing, 2022) from this URL:
	https://www.isprs.org/education/benchmarks/UrbanSemLab/Default.aspx
3.	Uncompress it, and place the folders "1_DSM/", "4_Ortho_RGBIR/" and "5_Labels_all/" 
	into the "Potsdam_data/" directory
4.	Run ```python make_tiles.py```. It will create input and target tiles in "Potsdam_data/tiles/"

## To train a model :
1.	Run ```python train.py``` with the desired parameters. 
	Refer to the arguments parser in the code to see the possible settings.
2.	Training can be monitored using the Weights and Biases tool (see https://docs.wandb.ai/quickstart).
	The URL to follow the training is provided in the console once validation occurs

## To test a model :
1.	Run ```python test.py``` with the desired parameters. 
2.	Metrics are printed in the console and the confusion matrix is saved as an image

## To predict an image :
1.	Run ```python predict.py``` by specifing the model and the image(s) to predict.
2.	If needed, try to expand the image(s) to create a batch of the size that has been used to train the model.
	This offers better results.
3.	If a ground truth is provided, "innacurate but certain" maps are produced
4.	Resulting predictions and maps are saved in the "predictions/" repository

**Update:** After the publication of this repository, a paper developing a similar approach has been published by Fisher et al [[3]](#3).

## References

<a id="1">[1]</a>  RONNEBERGER, Olaf, FISCHER, Philipp, et BROX, Thomas. U-net: Convolutional networks for biomedical image segmentation. In : International Conference on Medical image computing and computer-assisted intervention. Springer, Cham, 2015. p. 234-241. 

<a id="2">[2]</a> GAL, Yarin et GHAHRAMANI, Zoubin. Dropout as a bayesian approximation: Representing model uncertainty in deep learning. In : international conference on machine learning. PMLR, 2016. p. 1050-1059. [2]

<a id="3">[3]</a> Fisher, T.; Gibson, H.; Liu, Y.; Abdar, M.; Posa, M.; Salimi-Khorshidi, G.; Hassaine, A.; Cai, Y.; Rahimi, K.; Mamouei, M. Uncertainty-Aware Interpretable Deep Learning for Slum Mapping and Monitoring. Remote Sens. 2022, 14, 3072. https://doi.org/10.3390/rs14133072 
