# DP1 시뮬레이션 Configuration

설계 문서: [`../dp1-heterogeneous-memory-data-placement.md`](../dp1-heterogeneous-memory-data-placement.md) §3

| 파일 | 역할 |
|---|---|
| **`memories_default.yaml`** | **원본.** 수치를 고치려면 여기를 고친다 |
| `memories_default.json` | 생성물. `to_json.py`가 YAML에서 만든다. 직접 고치지 말 것 |
| `to_json.py` | 변환기. `--check`로 stale 여부 검사 |

파일은 세 블록으로 나뉜다.

| 블록 | 내용 |
|---|---|
| `gpu:` | 기준 GPU의 대역폭·연산 성능. 시뮬레이션의 비교 기준 |
| `model:` | 가정 모델의 형상. **`num_heads / num_kv_heads`가 Attention 연산 강도를 정하므로**(설계 문서 §4.2) 모델을 바꾸면 오프로드 가능 여부도 바뀐다 |
| `memories:` | 6종 메모리 스펙 |

**성능 수치는 이 저장소에 없다.** 이 파일은 시뮬레이션의 입력이며, 어떤 구성에서 무엇이 얼마나 나오는지는 시뮬레이션이 산출한다.

```bash
python3 to_json.py           # JSON 재생성
python3 to_json.py --check   # JSON이 YAML과 어긋나면 실패 (CI용)
```

## 왜 YAML이 원본인가

**엄격한 JSON에는 주석 문법이 없다.** 이 설정의 값들은 단위(`# 512 GiB`)와 출처(`src: SPEC / PUBLIC / ASSUMED`)가 **값 옆에** 보여야 편집할 때 실수를 막을 수 있다. 그래서 주석이 되는 YAML을 원본으로 두고, JSON이 필요한 소비자를 위해 기계 판독용 사본을 생성한다.

JSON 쪽에서도 정보가 사라지지 않도록 `provenance`·`note`를 데이터 필드로 유지하고, 사람이 읽을 수 있게 `units` 블록을 덧붙인다.

```json
"units": {
  "capacity": "512 GiB",
  "ext_bw": "0.064 TB/s",
  "int_bw": "1.100 TB/s",
  "int_ext_asymmetry": "17.2x"
}
```

`pyyaml`은 vLLM의 공통 의존성(`requirements/common.txt`)이므로 추가 설치가 필요 없다.

## 출처 등급

| 등급 | 의미 |
|---|---|
| `SPEC` | 규격서 명시값 (PCIe, HBM4, OCP HBF 등) |
| `PUBLIC` | 벤더·논문이 공개한 플랫폼 수치 |
| `ASSUMED` | 공개 정량값이 없어 본 구성이 가정한 값 |

**`ASSUMED` 항목은 결론을 뒤집을 수 있다.** 설계 문서 §11.6의 Sweep 축에 반드시 포함해야 하는 것은 다음 셋이다.

- `custom_hbm.int_bw_bytes_per_s` — "Custom HBM에 연산을 보낼 값이 있는가"를 좌우
- `hbf.write_bw_bytes_per_s`, `hbf.endurance_budget_bytes` — "HBF를 왕복 매체로 쓸 수 있는가"를 좌우

## 현재 구성 요약

| 메모리 | 위치 | 용량 | 외부 BW | 내부 BW | 비대칭 | Attention 오프로드 |
|---|---|---:|---:|---:|---:|:---:|
| `hbm` | GPU on-package | 192 GiB | 8.000 TB/s | 8.000 TB/s | 1.0x | — |
| `custom_hbm` | **별도 노드 (fabric)** | 1.00 TiB | 0.900 TB/s | 8.000 TB/s | 8.9x | ✓ |
| `cxl_pnm` | CPU 측 (CXL) | 512 GiB | 0.064 TB/s | 1.100 TB/s | 17.2x | ✓ |
| `dram` | CPU 측 | 1.00 TiB | 0.064 TB/s | 0.400 TB/s | 6.2x | — |
| `hbf` | GPU on-package | 2.00 TiB | 1.000 TB/s | 1.000 TB/s | 1.0x | — |
| `ssd_pim` | CPU 측 (NVMe) | 16.00 TiB | 0.016 TB/s | 0.200 TB/s | 12.5x | — |

`ssd_pim`은 `int_bw`가 높지만 `supported_primitives`에 `SOFTMAX`가 없어 **Attention 오프로드 대상이 아니다.** "GEMV 지원 ≠ Attention 지원"을 구성 수준에서 강제하는 지점이다.
