from pathlib import Path
import os
import json
import sys

ROOT = Path(__file__).resolve().parents[2] / 'tmp' / 'grant_figure'

if __name__ == '__main__':
    config = ROOT / 'totalseg_config'
    config.mkdir(exist_ok=True)
    (config / 'config.json').write_text(json.dumps({
        'totalseg_id': 'local_grant_figure',
        'send_usage_stats': False,
        'prediction_counter': 0
    }))
    os.environ['TOTALSEG_HOME_DIR'] = str(config)
    os.environ['TOTALSEG_WEIGHTS_PATH'] = r'C:\Users\a2189\.totalsegmentator\nnunet\results'
    from totalsegmentator.python_api import totalsegmentator
    from totalsegmentator.registry import requires_license
    assert not requires_license('total'), 'Only the open, no-license total model is permitted'
    extended='--extended' in sys.argv
    totalsegmentator(
        input=ROOT/'ct_pelvis_thigh.nii.gz' if extended else r'C:\Users\a2189\Dropbox\Hip_cross-sectional_area\output\ct_pelvis.nii.gz',
        output=ROOT / ('context_seg_extended' if extended else 'context_seg'),
        task='total',
        roi_subset=['femur_left', 'femur_right'] if extended else ['iliopsoas_left', 'iliopsoas_right'],
        device='gpu', nr_thr_resamp=2, nr_thr_saving=2,
    )
