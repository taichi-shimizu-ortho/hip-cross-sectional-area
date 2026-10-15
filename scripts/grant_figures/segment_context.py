from pathlib import Path
import os
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hip_paths

ROOT = Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure'


def device():
    import torch
    if torch.cuda.is_available():
        return 'gpu'
    if torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'

if __name__ == '__main__':
    config = ROOT / 'totalseg_config'
    config.mkdir(exist_ok=True)
    (config / 'config.json').write_text(json.dumps({
        'totalseg_id': 'local_grant_figure',
        'send_usage_stats': False,
        'prediction_counter': 0
    }))
    os.environ['TOTALSEG_HOME_DIR'] = str(config)
    os.environ['TOTALSEG_WEIGHTS_PATH'] = str(Path.home() / '.totalsegmentator' / 'nnunet' / 'results')
    os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')  # needed on Apple Silicon
    from totalsegmentator.python_api import totalsegmentator
    from totalsegmentator.registry import requires_license
    assert not requires_license('total'), 'Only the open, no-license total model is permitted'
    extended='--extended' in sys.argv
    totalsegmentator(
        input=ROOT/'ct_pelvis_thigh.nii.gz' if extended else hip_paths.CT_PELVIS,
        output=ROOT / ('context_seg_extended' if extended else 'context_seg'),
        task='total',
        roi_subset=['femur_left', 'femur_right'] if extended else ['iliopsoas_left', 'iliopsoas_right'],
        device=device(), nr_thr_resamp=2, nr_thr_saving=2,
    )
