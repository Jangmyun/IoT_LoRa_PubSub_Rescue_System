# Detection ML v1

Raspberry Pi gateway에서 돌릴 수 있는 scikit-learn 기반 위험 수면 교란 분류 실험 폴더입니다.

## Labels

- `CALM`
- `ENVIRONMENTAL_WAVE`
- `DUMMY_SPLASH`
- `SENSOR_FAULT`

`SENSOR_FAULT`는 ML 모델보다 먼저 rule-based로 분리합니다. ML 후보 모델은 non-fault window만 학습하고, 예측 단계에서 rule-based fault가 먼저 override됩니다.

## Input CSV

필수 열:

```csv
timestamp_ms,buoy_id,sonar_cm,accel_mag_ms2,label
0,A,82.1,9.80,CALM
100,A,82.0,9.82,CALM
```

예측 CSV에는 `label`이 없어도 됩니다. 선택 열 `sonar_valid`, `sonar_timeout`이 있으면 fault rule에 반영합니다.

## Features

기본 window는 2초, stride는 1초, baseline은 최근 30분입니다.

- `sonar_z`
- `accel_z`
- `sonar_rms_2s`
- `sonar_range_2s`
- `accel_rms_2s`
- `accel_jerk_2s`

`sonar_z`와 `accel_z`는 최근 30분 baseline window의 median/MAD 대비 robust z-score입니다.

## Run

```bash
python detection_ml_v1/generate_synthetic_data.py
python detection_ml_v1/train.py --csv detection_ml_v1/example_data/synthetic_measurements.csv
python detection_ml_v1/predict.py \
  --csv detection_ml_v1/example_data/synthetic_measurements.csv \
  --model detection_ml_v1/artifacts/model.joblib
```

결과:

- `detection_ml_v1/artifacts/feature_windows.csv`
- `detection_ml_v1/artifacts/metrics.csv`
- `detection_ml_v1/artifacts/model.joblib`
- `detection_ml_v1/artifacts/predictions.csv`

## Hardware assumptions

- TTGO LoRa32: ESP32 + SX1276 LoRa transport
- AJ-SR04M: waterproof ultrasonic distance as `sonar_cm`
- MPU6050: acceleration magnitude as `accel_mag_ms2`

학습 데이터 수집 단계에서는 가능하면 raw sample을 CSV로 저장합니다. LoRa payload가 작으면 운영 단계에서 ESP32가 2초 feature를 계산하고 Pi가 inference만 수행하는 구조로 줄입니다.

## Serial collection

펌웨어는 학습 데이터 수집을 위해 `CSV,` prefix가 붙은 raw sample line을 출력합니다. 시나리오별로 라벨을 붙여 저장합니다.

```bash
python detection_ml_v1/collect_serial_csv.py \
  --port /dev/ttyACM0 \
  --output detection_ml_v1/example_data/calm.csv \
  --label CALM \
  --seconds 300
```

권장 수집 순서:

- `CALM`: 부표를 가만히 두고 5분 이상
- `ENVIRONMENTAL_WAVE`: 인위적/자연 파동만 만들고 5분 이상
- `DUMMY_SPLASH`: 부표 근처 인형 첨벙임 trial
- `SENSOR_FAULT`: 센서 timeout/물방울/반사 실패 상황

오프라인 저장 파일을 나중에 라벨링할 때는 숫자 label을 사용할 수 있습니다.

| 숫자 | Label |
| ---: | --- |
| 0 | `CALM` |
| 1 | `ENVIRONMENTAL_WAVE` |
| 2 | `DUMMY_SPLASH` |
| 3 | `SENSOR_FAULT` |

```bash
python detection_ml_v1/prepare_labeled_dataset.py \
  --run csv_result_1.csv=0 \
  --run csv_result_2.csv=1 \
  --run csv_result_3.csv=2 \
  --run csv_result_4.csv=3 \
  --trim-start-seconds 5 \
  --trim-end-seconds 2 \
  --output detection_ml_v1/example_data/lake_labeled.csv

python detection_ml_v1/train.py --csv detection_ml_v1/example_data/lake_labeled.csv
```

Gateway 웹 UI의 `Start CSV` / `Stop` 버튼으로 저장한 파일은 기본적으로
`rpi-gateway-server/server/recordings/csv_result_001.csv` 형식으로 생성됩니다.
현재 LoRa raw publish 간격이 길다면 2초 window보다 긴 window로 학습합니다.

```bash
python detection_ml_v1/prepare_labeled_dataset.py \
  --run rpi-gateway-server/server/recordings/csv_result_001.csv=0 \
  --run rpi-gateway-server/server/recordings/csv_result_002.csv=1 \
  --run rpi-gateway-server/server/recordings/csv_result_003.csv=2 \
  --run rpi-gateway-server/server/recordings/csv_result_004.csv=3 \
  --trim-start-seconds 5 \
  --trim-end-seconds 2 \
  --output detection_ml_v1/example_data/lake_labeled.csv

python detection_ml_v1/train.py \
  --csv detection_ml_v1/example_data/lake_labeled.csv
```
