# RX Test Automation — 설계 (Blueway1721 RX)

작성일: 2026-06-25
대상 보드: Blueway1721 (RX) EVB, `config/bench_rx.toml`
참고 자료: `reference/Sivers_Satcom_Test Result_Rx.xlsx`,
`reference/250826_Doosan_Sivers Chip Evaluation Test_v1.9.pptx`

## 1. 목적

과거 유사 칩의 RX 검증 이력(reference Excel)과 거의 동일한 결과를 뽑기 위한
RX 측정 자동화. 채널을 바꿔가며(H0~V3) 동일 절차를 반복하고, 결과 CSV가
채널별로 자동 정리되어 나중에 한 번에 xlsx 후처리할 수 있게 한다.

핵심 원칙: **기존 함수를 최대한 재사용**하고 새 코드는 최소화한다. 측정 엔진은
모두 이미 존재하므로 신규 측정 코드는 사실상 없다.

## 2. 범위

### 이번 라운드 (in scope)
- reference 4개 테스트를 기존 엔진으로 매핑:
  - **Linearity (Rx)** → `ip1db` (CW Pin sweep, 매 포인트 전 레일 V/I + Idd 기록)
  - **Total PDC (Rx)** → 별도 측정 없음. Linearity CSV에서 추출(IP1dB 점 소비전력).
    Linearity 와 Total PDC 는 사실상 한 세트(하나의 ip1db 실행이 둘 다 커버).
  - **Gain Accuracy (Rx)** → `gain_index_accuracy` 를 **2회 실행**(2D = 두 축을
    각각 full sweep, cartesian 4096점 아님):
    1. common 축: `common_codes=range(0,64)`, `channel_codes=[0]`(채널 max gain 고정)
    2. channel 축: `common_codes=[0]`(common max gain 고정),
       `channel_codes=range(0,64)`, `channel_kind='beamtable'`
    각각 64점, 채널당 gain CSV 2개. `log_psu=False`(아래 참고).
  - **EVM bathtub (Rx)** → `evm(modulation='load', waveform_path=...)`
- 측정 단위는 **채널 1개**. 채널은 시작 시 인자로만 지정한다.
- 주파수는 **19.5 GHz 단일**(파라미터로 변경 가능, 기본값만 19.5e9).
- 출력은 **raw CSV 만**. 파일명은 기존 `_save_csv` 규칙으로 채널·빔·주파수가
  자동 포함되어 채널별로 자동 정리된다.
- 수동(개별 명령)과 자동(한 명령 `rx_suite`) 둘 다 가능해야 한다.

### 범위 밖 (out of scope, 나중에)
- 8채널 전체 ON 동시 Total PDC (별도 측정 — 채널 인자 변경으로 안 됨)
- ACP 측정 (reference EVM 시트에 컬럼 있으나 이번엔 제외)
- 온도 센서 읽기 (temp degC / data_temp_Pin adc 컬럼)
- per-rail 전력(V×I)·Psum·PAE·efficiency 계산 — CSV에 V/mA 가 다 있으므로
  xlsx 후처리 단계에서 계산
- xlsx 후처리/리포트 생성 (4개 테스트 데이터가 다 모인 뒤 별도 작업)
- 다중 주파수 sweep, 다중 채널 자동 루프

## 3. 현재 코드 자산 (재사용 대상)

| 자산 | 위치 | 상태 |
|---|---|---|
| `ip1db` | `test_items/ip1db.py` | Pin sweep + 전 레일 V/I + Idd 기록. 그대로 사용 |
| `gain_index_accuracy` | `test_items/gain_index_accuracy.py` | common 1D sweep(default) + 레일 기록 |
| `evm` | `test_items/evm.py` | `modulation='load'` + `waveform_path` 지원 |
| `_save_csv` | `runner.py` | 파일명 `<test>_<yymmdd>_<BEAM>_<CHANNEL>_<freq>[_g..]_<HHMMSS>.csv` |
| `_run_test` | `session.py` | 테스트 실행 후 CSV 저장 |
| `chan(ch, b)` | `manual.py` (namespace) | 단일 채널 bring-up. **active_channels 미갱신(=수정 대상)** |

## 4. 설계

### 4.1 핵심 변경 — `chan()` 보강 (기존 동작을 건드리는 주 변경)

문제: `chan(ch, b)` 는 칩 라우팅(disable all → centerbias ON → route → beam_table
zero+up → common gain max)만 하고 `bench.board.active_channels` / `bench.board.beam`
은 갱신하지 않는다. 테스트 아이템(ip1db/gain/evm)은 채널 meta(→CSV 파일명)와
경로 손실 계산에 `bench.board.active_channels[0]` 와 `bench.board.beam` 을 참조하므로,
`chan('h1')` 후 측정하면 CSV 채널명·손실이 직전 값으로 틀어진다.

해결: `chan(ch, b)` 가 라우팅과 함께
`bench.board.active_channels = [ch]`, `bench.board.beam = bm` 을 갱신하게 한다.
이것이 "이 채널을 측정 대상으로 만든다"는 chan 의 의미와도 일치한다.

영향 범위: `chan` 은 `manual.py` 의 `build_namespace(bench, chip, beam)` 내부 클로저라
`bench` 에 접근 가능. TX `channel_gain_alignment` 는 자체 enable 로직을 쓰고 `chan`
을 호출하지 않으므로 영향 없음. 회귀는 pytest 로 확인한다.

### 4.2 오케스트레이터 — `rx_suite()` (얇은 신규 함수)

`session.py` 에 추가하고 namespace 에 주입한다.

```
rx_suite(channel='h0', freq_hz=19.5e9, beam=None, **overrides)
```

동작:
1. `chan(channel, beam)` 호출 (= 4.1 보강으로 active_channels/beam 갱신 포함)
2. 아래 **4개 측정 스텝**을 순서대로 `_run_test(test_id, params)` 로 실행 — 각 스텝이
   **각자 CSV 저장**(중간에 한 스텝이 실패해도 앞서 저장된 CSV 는 보존, 다음 스텝으로
   진행 후 마지막에 요약). Total PDC 는 스텝 1(Linearity) CSV 에서 후처리로 추출.
3. 각 스텝의 검증된 기본 파라미터(아래)를 적용하되 `overrides` 로 덮어쓰기 허용.

측정 스텝(채널 1개, 19.5 GHz):
1. **Linearity** = `ip1db`: `freq_hz=19.5e9, gain_code=0, pin_start_dbm=-54,
   pin_stop_dbm=-11, pin_step_db=1.0` (max gain = common 0, reference Pin 범위)
   → 이 CSV 가 Total PDC 도 커버.
2. **Gain Accuracy (common 축)** = `gain_index_accuracy`:
   `freq_hz=19.5e9, common_codes=range(0,64), channel_codes=[0], log_psu=False`
3. **Gain Accuracy (channel 축)** = `gain_index_accuracy`:
   `freq_hz=19.5e9, common_codes=[0], channel_codes=range(0,64),
   channel_kind='beamtable', log_psu=False` (`channel_quad`=None → active 채널서 자동)
4. **EVM** = `evm`: `freq_hz=19.5e9, modulation='load', waveform_path=<설정>` (검증 시 확정)

스텝 2·3 은 같은 `test_id`(gain_index_accuracy)라, 파일명에 **축 태그**를 넣어
구분한다(4.3 참고): `..._common_...csv` / `..._chan_...csv`.

수동 사용도 그대로 유지된다: `chan('h1')` 후 `ip1db(...)` / `gain_index_accuracy(...)`
/ `evm(...)` 개별 실행.

### 4.3 출력 + 축 태그 (두 번째 소규모 변경)

- 각 테스트 CSV 는 `out/` 에 기존 규칙으로 저장되어 채널·빔·주파수가 파일명에
  포함된다. 8채널을 돌리면 채널별 CSV 가 자동으로 쌓인다.
- **축 태그**: Gain Accuracy 의 common/channel 두 sweep 을 파일명으로 구분하기 위해,
  - `gain_index_accuracy.run()` 이 `result.meta["axis"]` 를 설정한다:
    한 축만 변하면 `"common"`(channel 고정) / `"chan"`(common 고정),
    둘 다 변하면 `"2d"`, 둘 다 단일이면 미설정(None).
  - `_save_csv()` 가 meta 에 `axis`(또는 범용 `tag`)가 있으면 파일명에 삽입한다:
    `{test_id}_{ymd}_{beam}_{channel}_{freq}{gtag}_{axis}_{hms}.csv`.
    다른 테스트는 `axis` 가 없으므로 파일명 영향 없음(하위호환).
- Total PDC 는 Linearity(ip1db) CSV 의 레일 V/mA 컬럼에서 후처리로 추출한다
  (이번 라운드는 추출 코드 없이 CSV 보존만; 데이터가 다 모인 뒤 일괄 후처리).

## 5. 점진적 실행 순서

순서대로 진행하며 각 단계 검증 후 다음으로 넘어간다(중간 에러 최소화).

1. **A 적용**: `chan()` 보강 + pytest 통과 확인.
2. **H0 Linearity 검증**: `chan('h0'); ip1db(freq_hz=19.5e9, gain_code=0,
   pin_start_dbm=-54, pin_stop_dbm=-11)` → CSV 가 reference Linearity 시트
   내용(Pin/Pout/Gain + 전 레일 V/I)과 정합하는지 확인. (= Total PDC 동시 확인)
3. **H0 Gain Accuracy 검증**: 2회 실행 —
   (a) common 축: `gain_index_accuracy(freq_hz=19.5e9, common_codes=list(range(64)),
   channel_codes=[0], log_psu=False)`,
   (b) channel 축: `gain_index_accuracy(freq_hz=19.5e9, common_codes=[0],
   channel_codes=list(range(64)), channel_kind='beamtable', log_psu=False)`
   → reference Gain Accuracy 시트(코드별 gain)와 정합 확인.
4. **H0 EVM 검증**: `evm(modulation='load', waveform_path=..., freq_hz=19.5e9)`
   → EVM vs Pin 곡선 확인. (waveform 경로/포맷 검증 포함)
5. **자동화 마감**: `rx_suite()` 추가(검증된 파라미터 적용) + namespace 주입 +
   workbook RX 섹션 + `docs/SESSION.md` §6 / `README.md` 갱신 + fake 테스트 추가.

각 채널 확장은 SG 케이블을 해당 포트로 옮기고 채널 인자만 바꿔 반복한다(코드 변경 없음).

## 6. 테스트 / 검증

- `chan()` 보강: fake 모드에서 `chan('h0')` 후 `bench.board.active_channels==['h0']`,
  `bench.board.beam` 갱신을 단위 테스트로 확인. 기존 workbook smoke 테스트 통과 유지.
- 축 태그: fake 모드에서 common/chan 두 sweep 의 `meta["axis"]` 가 각각
  `"common"`/`"chan"` 으로 설정되고 CSV 파일명에 태그가 들어가 서로 다른 이름이
  되는지 확인. `axis` 없는 다른 테스트의 파일명은 불변(하위호환) 확인.
- `rx_suite()`: `--fake` 로 4개 스텝이 순차 실행되고 CSV 4개(linearity, gain_common,
  gain_chan, evm)가 생성되는지, 한 스텝 실패 시에도 나머지가 진행되고 요약이
  나오는지 fake 테스트로 확인.
- 실 측정 검증(2~4단계)은 실험 PC에서 reference 시트 대조로 수동 확인.

## 7. 열린 질문 / 가정

- EVM waveform 파일 경로·포맷은 4단계(EVM 검증) 시 실물로 확정한다.
- reference Linearity 의 Pin sweep 은 2 dB(거침) + 1 dB(압축점 부근) 혼합 step
  이지만, 이번엔 균일 1 dB step 으로 시작한다(필요 시 조정).
- 메모리/CLAUDE.md 의 "H0/V0/H2 driver 불량" 은 **TX(Stampede) 보드 전용**이며
  RX(Blueway) 는 전 채널 정상(workbook 명시). RX H0 로 진행 확정.
