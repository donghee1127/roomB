# CLAUDE.md

CloudChaser **Stampede2731 (TX) EVB** 측정 자동화. 전원→bring-up→계측기 셋업→측정.
상세는 [README.md](README.md), 측정 방법은 [docs/SESSION.md](docs/SESSION.md).

## 코드 규칙
- **사용자에게 보이는 모든 텍스트는 영어로 작성**(콘솔 cp949 한글 깨짐 방지): print/log/raise 메시지 + `_ns`(session 네임스페이스)에 노출되는 함수 docstring(`help('fn')` 시 출력됨) 포함. 코드 주석·모듈 docstring은 한국어 OK.
- 설정값은 코드가 아니라 **`config/bench.toml`**(계측기 IP·레일·SG/SA·채널/게인)에서 바꾼다.
- 경로 손실 모델: `Loss_data/`의 VNA CSV 3개(SG_Cable / SA_Cable / Board_Trace)에서 읽는다. **주파수 범위·간격은 파일마다 다르므로 고정 가정 금지**(예: 260626=16–32GHz/50MHz, 260820=27–32GHz/100MHz). 주파수별 `loss = max(|S12|,|S21|)`(보수적), 종류별 최신 날짜 파일 자동 선택. **컬럼 위치는 `PNT,...` 헤더에서 이름으로 찾는다** — MS4644B 는 저장 설정에 따라 PHASE 열을 빼기도 해서 열 번호를 고정하면 주파수를 loss 로 읽는다. `in_loss = sg_cable + trace/2`, `out_loss = sa_cable + trace/2`(빔/채널·TX/RX 구분 없음). 표에 없는 주파수는 선형보간(범위 밖 끝점 clamp, **이때 경고 출력**). 셋업이 바뀌어 손실이 달라지면 **기존 CSV 를 고치지 말고 새 날짜 파일을 추가**한다(최신 날짜가 자동 선택된다). 재측정 없이 파생한 파일이면 헤더에 `!==== DERIVED FILE -- NOT A VNA MEASUREMENT ====` 블록으로 출처·변경량·사유를 밝힌다 — 예: `SA_Cable_Loss_260902.csv`(260821 + 1 dB, 커넥터 교체분). 간이 측정 시 `set_loss(in,out)`으로 수동 override, `set_loss()`로 해제. `Loss_data/*.csv`는 `.gitignore` 의 `!Loss_data/*.csv` 로 **추적된다**.
- 계측기 통신은 표준 `socket` SCPI(:5025), VISA 불필요. 측정값 읽기는 `query_float`(단위/잡문자 견고), 느린 SA sweep은 `wait_opc_poll`.

## 개발 워크플로
- Python 3.13. 테스트: 프로젝트 venv로 `python -m pytest` (이 PC는 `.venv`). **커밋 전 pytest 통과 확인.**
- `--fake` 모드로 하드웨어 없이 dry-run 가능(계측기·SPI 전송만 가짜, 레지스터 변환은 실제와 동일).
- **커밋·푸시는 확인 없이 자동 진행**(사용자 지시). 흐름: 작업 브랜치 생성 → 커밋 → 푸시 → main 머지 → main 푸시 → 작업 브랜치 삭제. origin=github.com/paulbari/cloudchaser. 단 테스트 통과·검증 후에만, 파괴적 작업은 확인.
- 커밋 메시지는 PowerShell here-string(`@'...'@`) 사용 시 닫는 `'@`를 줄 맨 앞에 두고, em-dash(—)·`§` 등 비ASCII는 피한다(cp949 콘솔에서 깨짐).

## 새 측정 항목(Test Item) 추가 시
1. `src/cloudchaser/test_items/`에 `TestItem` 상속 모듈 작성(파라미터는 `Param` 선언형).
2. `test_items/__init__.py`의 `_ALL`에 등록.
3. **문서 동기화(필수): `docs/SESSION.md` §6 + `README.md` 테스트 목록**에 항목 추가.
4. `tests/`에 fake 테스트 추가(인터랙티브 항목은 비대화 인자로 — 예: channel_gain_alignment의 `channels_script`).

## 측정 항목
op1db · gain_index_accuracy · channel_gain_alignment · evm · acp · ip1db(RX). 채널 단위 묶음은 `tx_suite`/`rx_suite`. 사용 예시는 SESSION.md §6.

## 보드 하드웨어 현황 (중요)
- **전원 시퀀스는 Sivers 확정 타이밍 다이어그램을 따른다**(2026-09-03 회의).
  파워업 3스테이지(①`VDD_DIG` 1.0V → ②1.8V 군 = FE2/FE3/DIST/ANA/IO, 여기서 SPI active
  → ③`FE1` 4V), 파워다운 3plateau(4→1.8→1.0→0V), **각 단계 사이 최소 500 ms**.
  `bench.toml` 의 `power_up_stages` / `power_down_stages` / `stage_delay_s` 로 바꾼다.
- **1.8V 레일 배선(2026-09-03 재배선)**: 칩의 1.8V 넷 5개를 PSU 2채널로 묶되
  Sivers 레퍼런스 CSV 컬럼과 1:1 이 되게 물린다 --
  `IO_ANA_1V8`(PSU1 CH3) = IO_SOUTH + IO_NORTH + ANA(5핀) = 저쪽 `IDC_1p8`,
  `DIST_1V8`(PSU2 CH1) = DIST 2핀(K9/K27) = 저쪽 `IDC_Dist`.
  `DIST_1V8` 의 옛 이름 `DIG_1V8` 은 EVB 실크에서 온 오칭이었다(디지털은 1.0V `CORE_1V0`).
- **`VDD_1p8V_IO` 는 1.8V 다**(`IO_ANA_1V8`). 예전에 쓰던 1.3V 는 틀린 값이었고, 1.8V 에서
  칩이 오동작한 원인은 GlobalFoundries 이슈가 아니라 **EVB CHIP ID 핀 10k 풀다운 배선**
  문제였다 — CID 풀다운을 GND 로 쇼트하는 보드 리워크가 전제다.
  ⚠️ **리워크 안 된 보드에 1.8V 를 걸면 예전 오동작 조건 그대로다.** chip auto-detect 는
  `detect_v`(1.3V)로 먼저 켜서 `version_id` 를 확인하므로, 실패하면 FE 레일은 안 올라간다.
  ⚠️ **2026-08-21~09-02 의 측정 결과는 전부 IO=1.3V 에서 잰 값이라 재측정 대상이다**
  (확정 bias 코드·게인·OP1dB·"Psat 이 min 미달" 결론 포함).
- **RX(`config/bench_rx.toml`)의 `IO_1V3` 는 건드리지 말 것.** 위 1.8V 건은 Stampede TX
  EVB 의 CHIP ID 배선 문제이고, Blueway RX EVB 도 같은지는 Sivers 가 검증 전이다
  (2026-09-03 결정: **Sivers 컨펌 후 진행**). `docs/CloudChaser EVBs User Manual.pdf`
  p6 Table 2(전원 커넥터 표)는 **틀린 정보**라 근거로 쓰면 안 된다 -- 레일 정의는
  데이터시트(`docs/260410_..._Stampede_2731_TX_BFIC-V5.pdf` p12 Table 1/2)가 기준이다.
- 구(舊) TX EVB 는 H0/V0/H2 driver단 RF 경로 불량이 있었다(레지스터 덤프로 확정). **새 TX EVB 로 교체됨 — 전 채널 사용 가능(재검증 진행 중, `biasscan_compare` 로 확인 가능).**
- bring-up 은 **raw 레지스터 기입**이다(`board/firehawk.py` FH 엔진). 벤더 `sivers_api` 는
  SPI 전송 계층으로만 쓰고, `fields.wr`/`path`/`commit`/`beam_table` 같은 고수준 쓰기 API 는
  쓰지 않는다 — 근거는 `docs/superpowers/specs/2026-08-20-cloudchaser-raw-register-bringup-design.md`.
  읽기(`fields.rd`)는 HW 를 직접 읽으므로 진단용으로 계속 쓴다.
- bias 는 v4 시트(`bias_v4.py`)의 TX `Casper` / RX `NF_OPTIM` 을 기본 적용한다
  (`bench.toml` 의 `optimized_bias`).
- 게인 조작은 필드 이름이 아니라 타깃(`common`/`fe`/`beamtable`)으로 지정한다.
  per-path 는 `beamtable`(RTPS)이 실동작이고 `fe`(구 `gain_control_*`)는 이 칩에서 DEAD.
- raw route_channels()(= `enable()`)만으로는 center 마스터 바이어스가 안 켜지므로
  `centerbias_en`/`centermirror_en`(0x1008) 수동 ON 이 필요할 수 있다(bring_up_tx/rx
  와 `chan()` 은 자동으로 켠다). RTPS = beam table(zero_table + beam_up + phase-cal RAM,
  9-bit). common_gain은 감쇠 코드(0=최대 게인).
- RTPS = Reflective-Type Phase Shifter (Sivers SPI Spec/EVB Manual/firehawk.m 용어).
- `scripts/cc_quickstart.py` / `scripts/tx_test.py` 는 아직 마이그레이션 전이라
  `chip.path.enable`/`chip.path.active`(벤더 쓰기 API)를 직접 호출한다 — 새 코드의
  참고용으로 쓰지 말 것.

## 문서 역할
- `README.md` = 첫 페이지(개요/설치/구조/CLI). `docs/SESSION.md` = 측정 매뉴얼(살아있는 문서, 코드 바뀌면 갱신).
- `docs/sivers_unified_api_v0.1.0/`(getting_started·cloudchaser_setups + register map + whl 원본 패키지), `docs/Cloudchaser_drv-v1.0.0/` = sivers_api(vendor) 레퍼런스 — **우리 코드 아님, 건드리지 말 것.**

## PPT 생성
PPT 생성 요청은 반드시 `C:\claude_code\PPT_create` 프로젝트에 위임한다.
(`python -m ppt_creator generate` 또는 `/ppt` 명령 사용)
