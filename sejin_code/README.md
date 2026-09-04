# cloudchaser

CloudChaser **Stampede2731 (TX) / Blueway1721 (RX) EVB** 실험 자동화 코드.

**전원 인가 → 보드 bring-up → 계측기(SG/SA/PSU×2) 셋업 → 측정**까지를 코드화한다.
측정 항목(OP1dB, 게인 인덱스, 채널 정렬, EVM/ACP)은 IPython 세션 또는 runner CLI 로
실행하고 결과를 CSV 로 저장한다.

> **실제 측정 방법은 [docs/SESSION.md](docs/SESSION.md) — "측정 매뉴얼"** 을 참고.
> 세션에서 **수동으로 명령을 복붙**할 땐 [docs/COMMANDS.md](docs/COMMANDS.md) — "커맨드 보관소"
> (레지스터/필드 표 포함). 이 README 는 설치/구조/CLI 개요만 다룬다.

## 개발 워크플로 (2-PC)

| PC | 역할 |
|----|------|
| **이 PC** (코드/디버그) | `--fake` 모드로 HW 없이 dry-run, git 관리 |
| **실험 PC** (구동) | FTDI D2XX 드라이버 + 실제 계측기 연결, 실제 구동 |

실험 PC에서 에러가 나면 → 이 PC에서 재현·디버깅 → 커밋/푸시 → 실험 PC pull.

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install vendor\sivers_unified_api-0.1.0-py3-none-any.whl   # 보드 제어 API
```

> 실험 PC는 추가로 **FTDI D2XX 드라이버**가 필요하다 (실제 SPI 통신용).
> 계측기 레이어는 표준 라이브러리 `socket` 만 쓰므로 VISA 설치는 불필요.

## 실행

```powershell
# 측정 직전까지 셋업만 (전원+bring-up+계측기 셋업)
python -m cloudchaser.setup_tx --fake     # 이 PC: 하드웨어 없이 dry-run
python -m cloudchaser.setup_tx            # 실험 PC: 실제 하드웨어

# 실제 측정은 IPython 세션(주력) 또는 runner CLI 로 — docs/SESSION.md 참고
cc.bat                                     # 세션 열기 → start() → op1db() 등
python -m cloudchaser.runner run op1db     # 비대화 배치 실행

# Sivers 레퍼런스 IC 와 레일 전류 맞추기 (RF 없이 DC 만 -> jacobian/solve)
python -m cloudchaser.bias_match jacobian --ambient-c 25
python -m cloudchaser.bias_match solve --ambient-c 25

# 채널 하나의 bias 코드를 한 번에 확정 (세션 안에서. 결과는 bench.toml 에 기입)
#   find_bias('h1')
```

설정은 코드가 아니라 **`config/bench.toml`**(TX) / **`config/bench_rx.toml`**(RX) 에서 바꾼다.
경로 손실은 **`Loss_data/`** 의 VNA CSV 파일(SG_Cable / SA_Cable / Board_Trace)에서 자동 로드된다.

## 계측기 구성

**TX (bench.toml):**

| 역할 | 모델 | IP |
|------|------|-----|
| PSU1 | Keysight E36313A | 192.168.5.18 |
| PSU2 | Keysight E36313A | 192.168.5.19 |
| SG   | R&S SMW200A | 192.168.5.14 (28 GHz) |
| SA   | R&S FSVA3030 | 192.168.5.12 |

TX 레일 배선 (2026-09-03 재배선 — Sivers 레퍼런스 CSV 컬럼과 1:1):

| PSU | CH | 레일명 | 전압 | 칩 핀 | Sivers 컬럼 |
|-----|----|--------|------|-------|-------------|
| PSU1 | 1 | `FE1_4V0` | 4.0V | `VDD_FE1_CH0~3` (PA) | `IDC_FE1` |
| PSU1 | 2 | `CORE_1V0` | 1.0V | `VDD_DIG` (6핀) | `IDC_1p0` |
| PSU1 | 3 | `IO_ANA_1V8` | 1.8V | `VDD_1p8V_IO_SOUTH` + `IO_NORTH` + `VDD_1p8V_ANA`(5핀) | `IDC_1p8` |
| PSU2 | 1 | `DIST_1V8` | 1.8V | `VDD_1p8V_DIST` (K9, K27) | `IDC_Dist` |
| PSU2 | 2 | `FE2_1V8` | 1.8V | `VDD_FE2_CH0~3` (driver) | `IDC_FE2` |
| PSU2 | 3 | `FE3_1V8` | 1.8V | `VDD_FE3_CH0~3` (combiner) | `IDC_FE3` |

`IO_ANA_1V8` 은 CHIP ID 리워크(CID 풀다운 GND 쇼트) 후에만 1.8V 로 쓸 수 있다 — 상세는 [CLAUDE.md](CLAUDE.md).

**RX (bench_rx.toml) — 동일 PSU, 전압만 변경:**

| PSU | CH | 레일명 | 전압 | 칩 핀 |
|-----|----|--------|------|-------|
| PSU1 | 1 | FE_1V0 | 1.0V | VDD_FE1 (LNA) |
| PSU1 | 2 | DIG_1V0 | 1.0V | VDD_DIG |
| PSU1 | 3 | IO_1V3 | 1.3V | VDD_1p8V_IO (EVB 1.3V 유지 — Sivers 컨펌 대기) |
| PSU2 | 1 | ANA_1V8 | 1.8V | VDD_1p8V_ANA |
| PSU2 | 2 | FE3_1V5 | 1.5V | VDD_FE3 (splitter) |
| PSU2 | 3 | DIST_1V5 | 1.5V | VDD_1p5V_DIST (combiner) |

## 구조

```
src/cloudchaser/
  instruments/   scpi.py, psu_e36313a.py, sg_smw200a.py, sa_fsva3030.py, vna_ms4644b.py
  board/         bringup.py            # TX/RX bring-up (raw 레지스터 시퀀스, 20/10단계)
                 firehawk.py           # FH 레지스터 엔진 -- 주소 상수 + 비트팩 + wr/rd/wr_verify
                 bias_v4.py            # v4 시트 Casper(TX)/NF_OPTIM(RX) bias 코드 테이블
                 gain_map.py           # 게인/위상 타깃(common/fe/beamtable) -> 레지스터 매핑
  test_items/    op1db, gain_index_accuracy, channel_gain_alignment, evm, acp, ip1db, phase_index_accuracy
  bench.py       # bench.toml 로딩 + 계측기 통합 관리
  setup_tx.py    # 측정 직전까지 셋업 오케스트레이션
  runner.py      # 테스트 항목 비대화 실행 + CSV 저장 (CLI 백엔드)
  session.py     # IPython 인터랙티브 세션 (측정 주력 진입점)
  manual.py      # 수동 콘솔 헬퍼(chan/rf/peak/vi 등)
  regdump.py     # 레지스터 덤프 저장/로드/비교 CLI (Sivers 레퍼런스 xlsx 대조)
  bias_match.py  # Sivers 레퍼런스 IC 전류 매칭 (jacobian/solve/verify/dist-gain)
  bias_find.py   # 채널 하나의 bias 코드 확정 -> bench.toml 기입 (세션 find_bias())
  loss.py        # 경로 손실(VNA CSV 기반, cable + trace/2) 조회
config/          # bench.toml, bench_rx.toml
Loss_data/       # VNA CSV 파일(SG_Cable / SA_Cable / Board_Trace, git 추적됨)
docs/            # SESSION.md(측정 매뉴얼), BIAS_SEARCH.md(bias 탐색 알고리즘),
                 #   COMMANDS.md(커맨드 보관소), register map (+ vendor 레퍼런스)
scripts/         # cc_quickstart.py, tx_test.py, dump_register_map.py
                 #   (cc_quickstart.py / tx_test.py 는 아직 raw 레지스터로 마이그레이션되지
                 #   않았다 -- chip.path.enable/chip.path.active(벤더 쓰기 API)를 그대로
                 #   호출한다. 새 코드의 참고용으로 쓰지 말 것.)
vendor/          # sivers_unified_api wheel
tests/           # 오프라인(fake) 테스트
cc.bat           # 세션 런처(실험 PC)
```

> bring-up 쓰기는 raw 레지스터(`board/firehawk.py`)로 한다 — 벤더 `sivers_api` 는
> SPI 전송 계층만 쓴다(고수준 `fields.wr`/`path`/`commit`/`beam_table` API 미사용).
> 근거: [design spec](docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md) 2장.

## 테스트

```powershell
pip install pytest
pytest
```

## 테스트 아이템 실행 (Test Items)

Test Item(시험 항목)별로 모듈이 분리돼 있고(`src/cloudchaser/test_items/`), `runner`가
"전원→보드 bring-up→테스트 실행→결과 CSV 저장"을 자동으로 처리한다.

```powershell
python -m cloudchaser.runner list                              # 테스트 목록
python -m cloudchaser.runner info gain_index_accuracy          # 파라미터 보기
python -m cloudchaser.runner run gain_index_accuracy --fake    # 실행(dry-run)
python -m cloudchaser.runner run op1db --param gain_code=0x20 --param pin_stop_dbm=0

python -m cloudchaser.regdump --fake --save out\regs.csv                          # 레지스터 덤프 저장
python -m cloudchaser.regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx # Sivers 레퍼런스와 대조
```

> `python -m cloudchaser.regdump` (및 다른 `python -m cloudchaser.*` CLI)를 pytest
> 밖에서 직접 실행할 때 `ModuleNotFoundError: No module named 'cloudchaser'` 가 나면
> editable install 이 안 된 환경이다 — `pip install -e .` 하거나 세션에
> `$env:PYTHONPATH="src"` 를 설정한다. 상세: [docs/SESSION.md §8](docs/SESSION.md).

결과는 `out/<test_id>_<timestamp>.csv` 로 저장된다(메타정보 주석 + 데이터 표).
각 항목의 목적·파라미터·사용 예시는 **[docs/SESSION.md](docs/SESSION.md) §6** 참고.

**현재 테스트 아이템:**
- `op1db` — [TX] 고정 게인에서 CW 전력 sweep, 출력 1dB 압축점(OP1dB) 측정
- `gain_index_accuracy` — [TX] SG 고정, 공통/per-path(RTPS) 게인 인덱스 sweep
- `channel_gain_alignment` — [TX] 게인 최대 고정, 채널별 출력 전력으로 채널 간 정렬 (인터랙티브)
- `evm` — [TX] 5G NR 변조 인가, SG 파워 sweep, EVM[dB] vs 출력
- `acp` — [TX] 5G NR 변조 인가, SG 파워 sweep, 인접채널전력비(ACP, dBc)
- `vdd_sensitivity` — [TX] OP1dB sweep 을 FE1 공급전압(4.0~2.2V) 계단마다 반복, 전압 민감도 측정 (측정 후 4.0V 자동 복구)
- `tx_suite` — [TX] 측정 묶음: 테스트 항목·순서·주파수를 골라 순차 실행 (`tx_suite()` 대화형 / `steps=`·`freqs=` 지정 / 인자만 주면 예전 4단계 프리셋). 스텝별 CSV (세션 명령)
- `ip1db` — [RX] 고정 게인에서 CW 전력 sweep, 입력 1dB 압축점(IP1dB) 측정 (Blueway 전용)
- `phase_index_accuracy` — [TX/RX] RTPS 위상 인덱스(9-bit, 0..511; 기본 128점 sweep) sweep, VNA(MS4644B) S21 gain/phase 기록 (VNA 수동 cal 필수)
- `rx_suite` — [RX] 채널 1개 측정 묶음(Linearity + Gain Accuracy 2축 + EVM), 채널별 CSV (세션 명령)
- `gain_index_accuracy_common` / `gain_index_accuracy_channel` — [RX] Gain Accuracy 단일축 편의 함수(RX 기본값, CSV 축 태그)
- `evm_rx` — [RX] EVM bathtub 편의 함수(SG ARB 파형 로드 + 입력파워 sweep, SA 수동 설정 기본)

**새 테스트 추가:** `test_items/`에 `TestItem` 상속 모듈 하나 작성 → `test_items/__init__.py`의
`_ALL`에 등록. 끝(runner·세션이 자동 인식). 파라미터는 `Param`으로 선언한다.
> 새 항목을 추가/변경하면 **docs/SESSION.md(§6)와 위 목록도 같이 갱신**할 것.

> 큰 그림: 나중에 GUI에서 계측기/IP/테스트/파라미터를 선택하고 Run 하면 `runner.run_test()`를
> 호출해 자동화한다. 그래서 테스트는 파라미터를 선언형으로 정의하고, runner가 백엔드 역할을 한다.

## 다음 단계 (예정)
- 측정 항목 합격 기준(pass/fail) 추가
- Loss_data/ VNA CSV 실측 데이터 확보 후 재검증
- Blueway 필드명 확인 후 bring_up_rx() 세부 조정 (경고 메시지 확인)
- 실칩 검증: `regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx` 잔차 확인,
  `optimized_bias`(TX 는 FE bias 만 갈린다)·`dist_st2_1_ptat` A/B (docs/SESSION.md §8·§9).
  eFuse 트림은 `run_efuse_init` A/B 가 아니라 bring-up 전 리드백으로 확인한다(§9-1).
- GUI 프런트엔드(runner 백엔드 재사용)
