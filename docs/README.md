# Docs

프로젝트 요구사항과 탐지 알고리즘 설계를 설명하는 문서 폴더입니다. 발표 자료나 최종 보고서에서 시스템 의도, 제한사항, 탐지 기준을 설명할 때 참고합니다.

## 구성

| 경로 | 설명 |
| --- | --- |
| `DETECTION_ALGORITHM_DESIGN.md` | 얕은 호수 인형 시연용 위험 수면 교란 감지 설계 |
| `assets/detection` | 탐지 알고리즘 설명용 SVG 그래프 |
| `generate_detection_graphs.py` | 합성 데이터 또는 측정 CSV로 설명 그래프 생성 |
| `requirements.txt` | 그래프 생성용 Python dependency |

## 탐지 설계 요약

이 프로젝트의 경보는 실제 익수 여부를 확정하는 것이 아니라, 부표 주변에서 평상시 환경 파동과 다른 국소 위험 수면 교란이 반복적으로 관측되었음을 알리는 신호입니다.

판정에서 고려하는 핵심 요소:

- sonar 거리 변화량과 변동성
- IMU 기반 부표 자체 흔들림
- 여러 부표가 동시에 반응하는지 여부
- sensor timeout, 비정상 범위, 단발 spike 같은 fault 처리
- 장기 baseline과 짧은 window 판정의 분리

## 그래프 재생성

합성 예시 데이터로 SVG를 다시 만들려면:

```bash
cd docs
pip install -r requirements.txt
python generate_detection_graphs.py
```

측정 CSV를 사용할 때:

```bash
cd docs
python generate_detection_graphs.py \
  --csv path/to/measured_detection.csv \
  --output-dir assets/detection
```

측정 CSV를 사용하는 경우 `timestamp_ms`, `buoy_id`, `sonar_cm`, `accel_mag_ms2`, `gyro_mag_rads`, `label` 열이 필요합니다.
현재 `detection_ml_v1`의 accel-only CSV에는 `gyro_mag_rads`가 없으므로 그대로 입력하면 안 됩니다.

## 참고

- 루트 요구사항 문서: [`../PRD.md`](../PRD.md)
- 탐지 알고리즘 상세 문서: [`DETECTION_ALGORITHM_DESIGN.md`](./DETECTION_ALGORITHM_DESIGN.md)
