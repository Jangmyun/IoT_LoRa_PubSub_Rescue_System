# Bath All-Buoys Model v1

Tracked deployment copy of the bath experiment model used by the Raspberry Pi gateway.

Default server path:

```text
detection_ml_v1/models/bath_all_buoys_cv_v1/model.joblib
```

Source training artifact:

```text
detection_ml_v1/artifacts/bath_all_buoys_cv_v1/model.joblib
```

Training summary:

- Labels: `CALM`, `ENVIRONMENTAL_WAVE`, `DUMMY_SPLASH`
- Model: `random_forest`
- Window: `10s`
- Stride: `5s`
- CV: stratified 5-fold
- CV macro F1: `0.864916`

Override at runtime:

```bash
ML_MODEL_PATH=/path/to/model.joblib ./run.sh
```
