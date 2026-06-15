# Bath Accel-Only v2

Model for Raspberry Pi live inference using acceleration-derived features only.

- Source runs:
  - `csv_result_002_idle.csv`, `csv_result_005.csv`: `CALM`
  - `csv_result_003_wave.csv`, `csv_result_006.csv`: `ENVIRONMENTAL_WAVE`
  - `csv_result_004_victim.csv`, `csv_result_007.csv`: `DUMMY_SPLASH`
- Training rows after trim: 743
- Windowing: 10 seconds, 5 seconds stride
- Features: `accel_z`, `accel_mean_ms2`, `accel_rms_2s`, `accel_range_2s`, `accel_jerk_2s`
- Best model: `random_forest`
- 5-fold CV accuracy: 0.8723
- 5-fold CV macro F1: 0.8490

Server mapping:

- `CALM`, `ENVIRONMENTAL_WAVE` -> `NORMAL`
- `DUMMY_SPLASH` or ambiguous victim probability above threshold -> `SUSPECT`

Re-train command:

```bash
python detection_ml_v1/prepare_labeled_dataset.py \
  --run detection_ml_v1/tests/csv_result_002_idle.csv=CALM \
  --run detection_ml_v1/tests/csv_result_003_wave.csv=ENVIRONMENTAL_WAVE \
  --run detection_ml_v1/tests/csv_result_004_victim.csv=DUMMY_SPLASH \
  --run detection_ml_v1/tests/csv_result_005.csv=CALM \
  --run detection_ml_v1/tests/csv_result_006.csv=ENVIRONMENTAL_WAVE \
  --run detection_ml_v1/tests/csv_result_007.csv=DUMMY_SPLASH \
  --trim-start-seconds 5 \
  --trim-end-seconds 2 \
  --output detection_ml_v1/example_data/bath_accel_labeled_v2.csv

python detection_ml_v1/train.py \
  --csv detection_ml_v1/example_data/bath_accel_labeled_v2.csv \
  --output-dir detection_ml_v1/artifacts/bath_accel_only_v2 \
  --feature-set accel \
  --cv-folds 5
```
