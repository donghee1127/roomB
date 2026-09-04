# CloudChaser raw-register bring-up + v4 optimized bias — 설계

- 작성일: 2026-08-20
- 대상 repo: `C:\claude_code\cloudchaser`
- 참조 구현: `C:\claude_code\Sivers_EVB\evb_full.py` (Sivers 뉴욕 출장 2026-07-26~08-01 산출물)
- 상태: 승인됨 (구현 대기)

---

## 1. 목표

1. cloudchaser의 bring-up 결과 **레지스터 상태**를 `Sivers_EVB/evb_full.py`의 `bringup()`과 동일하게 만든다.
2. bias는 eFuse 기본값이 아니라 Sivers가 준 **최적화 코드**(`Cloudchaser_ES1_BiasMapping_Tuning_Bits_v4.xlsx`)를 명시적으로 기입한다. TX는 `Casper` 열, RX는 `NF_OPTIM` 열.
3. 벤더 `sivers_api`의 **고수준 API 의존을 쓰기 경로에서 제거**한다. SPI 전송 계층만 남긴다.
4. 기존 측정 항목(op1db · ip1db · gain_index_accuracy · channel_gain_alignment · evm · acp · phase_index_accuracy)이 동일하게 동작한다.

### 비목표

- 계측기 제어(`instruments/`), 경로손실(`loss.py`), 결과 저장(`runner.py` CSV) 은 건드리지 않는다.
- 코드 구조를 `evb_full.py`와 똑같이 만들지 않는다. **레지스터 결과만 같으면 된다.**
- 실칩 검증은 이 작업 범위 밖이다(실험 PC 필요). 여기서는 fake 모드까지 검증한다.

---

## 2. 배경 — 왜 raw 레지스터인가

두 코드가 같은 벤더 패키지를 쓰지만 **깊이가 다르다.**

```
                    evb_full.py                    cloudchaser (현재)
                    -----------                    ------------------
칩 객체             Stampede(chip_id=0)     <같음>  Stampede(chip_id=0)
고수준 API          (안 씀)                         chip.init()
                                                    chip.path.enable()
                                                    chip.fields.wr(...)
                                                    chip.commit()
                                                    chip.beam_table.commit_table()
SPI 전송            chip.spi.wr(0, addr, val)      (드라이버 내부에서 호출)
```

`evb_full.py`는 MATLAB `firehawk.m`의 레지스터 시퀀스를 직접 계산해 `chip.spi.wr(chip_id, addr, value)`로 기입한다. cloudchaser는 벤더 드라이버에 맡긴다. 그래서 최종 레지스터 값이 **벤더 드라이버 내부 동작에 좌우된다.**

### 결정 근거

1. **벤더 API 신뢰성** (사용자 판단, 2026-08-20). `sivers_unified_api` 0.1.0은 오래된 버전이고 오류 여지가 있다. 레지스터를 직접 쓰는 편이 예측 가능하다.

2. **`chip.init()`이 레지스터를 건드린다.** `sivers_api/BFIC.py`의 `init()`은
   `spi.reset()` → `read_full_addres_range()` → `_set_reset()` → **`load_efuse()`** 순서로 동작한다.
   `load_efuse()`는 단순 읽기가 아니라 레지스터 맵 xlsx의 `EFUSE_INSTRUCTIONS` 시트에 적힌
   스크립트(R / W / RCLR / CLR / FIXED)를 실행해 **레지스터를 읽고·지우고·쓴다.**
   `evb_full.py`는 `chip.init()`을 한 번도 호출하지 않으므로, 이 단계를 그대로 두면 레지스터 결과가 처음부터 갈라진다.
   (`Stampede()` 생성자는 `init()`을 부르지 않는다 — `Regs.__init__`의 `self.init()`은 필드 컨테이너 생성일 뿐이다.)

3. **shadow 캐시 위험.** `sivers_api/regs.py`의 `fields.wr(name, val)`은 로컬 shadow(`self._regs`)에서
   read-modify-write 한 뒤 그 워드만 commit한다. **HW를 다시 읽지 않는다.**
   raw로 쓴 워드를 이후 `fields.wr()`가 낡은 shadow 값으로 되돌릴 수 있다 — 조용히 틀리는 종류의 버그다.
   쓰기 경로에서 `fields`를 제거하면 이 위험 자체가 사라진다.

### 읽기는 남긴다

`fields.rd(name)`은 **HW를 먼저 읽고** 리턴한다(`regs.py`의 `Fields.rd` → `regs.rd`). shadow를 신뢰하지 않으므로 안전하다.
따라서 진단 도구(`driver_reg_diff.py`, `manual.py`의 읽기 헬퍼)는 그대로 둔다. **쓰기만 걷어낸다.**

---

## 3. 아키텍처

| 파일 | 상태 | 역할 |
|---|---|---|
| `src/cloudchaser/board/firehawk.py` | 신규 | FH 레지스터 엔진. 주소 상수 + 비트팩 메서드 + `wr`/`rd`/`wr_verify` |
| `src/cloudchaser/board/bias_v4.py` | 신규 | v4 시트 `Casper`(TX)/`NF_OPTIM`(RX) 코드 테이블 |
| `src/cloudchaser/board/gain_map.py` | 신규 | 게인/위상 타깃 → (주소, 비트) 매핑. 테스트 항목이 사용 |
| `src/cloudchaser/board/bringup.py` | 내부 교체 | `bring_up_tx`/`bring_up_rx` — **시그니처·반환 dict 유지** |
| `src/cloudchaser/regdump.py` | 신규 | 실칩 덤프 + Sivers 덤프(xlsx/csv) diff CLI |

`bring_up_tx(chip, cfg, *, require_version=True, log=print) -> dict` 시그니처를 유지하므로
호출부 6곳(`runner.py` · `session.py` · `manual.py` · `setup_tx.py` · `biasscan_compare.py` · `driver_reg_diff.py`)은 수정하지 않는다.

### 레지스터 주소 (firehawk.m Constant)

| 상수 | 주소 | 워드 수 | 내용 |
|---|---|---|---|
| `COMMON_GAIN` | `0x1005` | 3 | B0/B1/B2 공통 게인(감쇠 코드, 0=최대 게인) |
| `BEAM_ENABLES_ADDR` | `0x1008` | 1+3 | center@0x1008, beam_enables@0x1009~ |
| `QUAD_ENABLES_ADDR` | `0x100C` | 4 | quad_H_en / quad_V_en / pulse_en |
| `QUAD_PWRDN_ADDR` | `0x1010` | 4 | pwrdn / override / bias_en / pulse / efuse_dis |
| `FE_GAIN_ADDR` | `0x1018` | 4 | Gain_H / Gain_V / pulse_en |
| `ADC_SET_ADDR` | `0x1020` | 2 | ADC clk / enable+rst |
| `TEMP_CAL_ADDR` | `0x1022` | 1 | temp offset/slope + core/bandgap en |
| `BEAM_BIAS_ADDR` | `0x1038` | 20 | FE bias (인터리브) |
| `DIST_BIAS_ADDR` | `0x104C` | 7 | DIST bias 3빔 + CTAT |
| `EXTRA_ADDR` | `0x1058` | 3 | extra bias code B0/B1/B2 + misc |
| `BEAM_CAL_ADDR` | `0x105C` | 12 | 채널×편파×빔 cal 감쇠 |
| `CAPTUNE_ADDR` | `0x1068` | 4 | FE captune CH0..3 |
| `PHASE_CAL_ADDR` | `0x106C` | 280 | phase-cal RAM (4×70) |
| `SHORT_ID_ADDR` | `0x1000` | 1 | short_id + version_id (TX 0xDC / RX 0xD4) |

### 비트팩 규칙 (evb_full.py `FH` 이식)

```
quad_pwrdn (0x1010+i)   = pwrdn | override<<6 | bias_en<<7 | pulse<<8 | efuse_dis<<9
  pwrdn 6-bit MSB-first  = [comb_V drv_V PA_V comb_H drv_H PA_H]
  ★ TX(Stampede)는 H/V 비트 위치가 RX와 반대: TX h=[5:3]/v=[2:0], RX h=[2:0]/v=[5:3]
     (출장 중 발견·수정한 버그. RX 규칙을 TX에 쓰면 편파가 뒤집힌다.)

beam_enables (0x1009+i) = beam_enables | bias_en<<8 | beam_pwrdn<<9 | match<<14
quad_enables (0x100C+i) = quad_H_en | quad_V_en<<8 | pulse_en<<11
fe_gain      (0x1018+i) = Gain_H | Gain_V<<8 | pulse_en<<12
center       (0x1008)   = sum(e[k] * w[k]),  w = [1 2 4 8 16 32 128 256 1024 4096]
temp         (0x1022)   = offset | slope<<4 | core_en<<8 | bandgap_en<<9

fe_bias   base 0x1038, 채널 i (0..3), 행 H=2i / V=2i+1, 열 [PTAT1 PTAT2 PTAT3 CTAT CBIAS]
  +i    = H.PTAT1 | H.PTAT2<<8
  +4+i  = H.PTAT3 | H.CTAT<<8
  +8+i  = V.PTAT1 | V.PTAT2<<8
  +12+i = V.PTAT3 | V.CTAT<<8
  +16+i = H.CBIAS | V.CBIAS<<8

dist_bias base 0x104C, 빔 b (0..2), 열 [PTAT1 PTAT2_0 PTAT2_1 cbias1 cbias2_0 cbias2_1]
  +2b   = PTAT1 | PTAT2_0<<8
  +2b+1 = PTAT2_1 | cbias1<<6 | cbias2_0<<9 | cbias2_1<<12
  +6    = DIST CTAT

beam table 워드 (addr = ch)   = atten(7bit) | phase_coarse<<7      (phase_coarse = ph//4)
phase-cal fine (0x106C 기준)  = 0x2000 | (ph % 4)
   base = 0x106C + (beam + hv*3)*12 + ch,  오프셋 +0 / +4 / +8
```

---

## 4. bring-up 시퀀스

### TX (Stampede) — `bring_up_tx`

`evb_full.py`의 `bring_up_tx` 순서를 그대로 따른다. 채널·빔·게인·감쇠는 `BoardConfig`(= `bench.toml [board]`)에서 가져온다.

| # | 동작 | 레지스터 | 비고 |
|---|---|---|---|
| 1 | `chip.spi.reset()` | — | **`chip.init()` 호출 안 함** (§2 결정근거 2) |
| 2 | `version_id` 확인 | `0x1000` | TX=0xDC. `require_version=True`면 불일치 시 예외 |
| 3 | `zero_phase_cal()` | `0x106C`~ 280워드 = 0 | ★ RTPS fine-phase 전제. cloudchaser가 놓쳤던 단계 |
| 4 | `set_center_enables([1,1,0,...])` | `0x1008` = 3 | bandgap + mirror |
| 5 | `set_common_gains([g,g,g])` | `0x1005`~ | `cfg.common_gain` |
| 6 | `set_cal(...)` | `0x105C`~ | 전 원소 0이 기본. `cfg.ch_atten`에 값이 있으면 해당 채널·편파의 전 빔 원소에 기입 (evb_full `CAL_ATTEN=None` → 0 과 동일) |
| 7 | `load_beam_table(0, [[0]*8])` + `beam_up()` | beam table | RTPS atten/phase 0 |
| 8 | `set_captune([0,0,0,0])` | `0x1068`~ | evb_full `FE_CAPTUNE=0x0000`과 동일. split_mode면 19번에서 0x8888로 덮인다 |
| 9 | `set_fe_bias(...)` | `0x1038`~ | **활성 채널만 기입.** optimized_bias면 Casper, 아니면 eFuse 리드백 |
| 10 | `set_dist_bias(..., ctat)` | `0x104C`~ | 활성 빔 행만. TX는 B2 PTAT=[6,6,6] 하드코딩 |
| 11 | `set_extra(...)` | `0x1058`~ | 활성 빔=8, 비활성=1, B2=14 |
| 12 | `set_temp_sensor([8,8],[1,1])` | `0x1022` | |
| 13 | daisy / ADC | `0x1004`=0x000F, `0x1020`=0x0021, `0x1021`=0x4100 | MATLAB Func 추가분 |
| 14 | `set_quad_enables(...)` | `0x100C`~ | 활성 채널 quad에 `1<<beam` |
| 15 | **staged power-up** (3회 기입) | `0x1010`~ | bias only → +PA/DRV(`0b011<<base`) → +combiner(`0b111<<base`), `base = 0 if pol=='v' else 3` |
| 16 | `set_beam_enables` ① splitter bias only | `0x1009`~ | `[0, 1, 0, 0]` |
| 17 | `set_beam_enables` ② +amp | `0x1009`~ | `[chan_mask, 1, 1, 0]` |
| 18 | DIRECT_REGS_TX | `0x104C`=3378, `0x104D`, `0x1050`=1542, `0x1051`=6, `0x1052`=8, `0x1058`=8, `0x1059`=11 | `0x104D`는 §5 참조 |
| 19 | (split_mode) SPLIT_REGS_TX | `0x1009`=783, `0x1068`=0x8888 | DIST 스플리터 split 모드 |
| 20 | readback 요약 반환 | — | 기존 dict 키 유지 |

### RX (Blueway) — `bring_up_rx`

| # | 동작 | 레지스터 | 비고 |
|---|---|---|---|
| 1 | `chip.spi.reset()` | — | |
| 2 | `version_id` 확인 | `0x1000` | RX=0xD4 |
| 3 | `set_fe_bias` / `set_dist_bias` | `0x1038`~ / `0x104C`~ | **enable 전에** 기입. optimized_bias면 NF_OPTIM |
| 4 | daisy | `0x1004` = 31 | |
| 5 | `set_center_enables([1,1,1,0,...])` | `0x1008` = 7 | |
| 6 | `set_beam_enables` | `0x1009` | `[1<<ci, 1, 4, 0]` → CH0/B0에서 2305 |
| 7 | `set_quad_enables` | `0x100C` | `[1<<beam, 1<<beam, 0]` → 257 |
| 8 | `set_quad_pwrdn` | `0x1010`~ | H=`0b000111`(199) / V=`0b111000`(248). 그 외 quad는 override만(64) |
| 9 | `set_captune` | `0x1068` | 기본 0x8888 |
| 10 | DIRECT_REGS_RX | `0x1004`=31, `0x1058`=0x8888, `0x1068`=0x8888, `0x1059`=4 | |

RX는 단일 채널 기준이다(`cfg.active_channels[0]`). MATLAB `Meas_260724_BLWY01`의 H0B0 시퀀스를 일반화한 것이다.

---

## 5. v4 optimized bias

출처: `C:\claude_code\Sivers_EVB\register_maps\Cloudchaser_ES1_BiasMapping_Tuning_Bits_v4.xlsx`
(보관: `C:\claude_code\_reference\01_Cloudchaser_BFIC\01_datasheet\`)

### TX — `Stampede TX Digital Settings` 시트, `H0-B0 (Casper)` 열

| 필드 | 레지스터 | 기본(H0-B0) | **Casper** | 기능 |
|---|---|---|---|---|
| `PTAT_St1` | `0x1038[5:0]` | 32 | **15** | PA |
| `PTAT_St2` | `0x1038[13:8]` | 26 | **45** | PA driver |
| `PTAT_St3` | `0x103C[5:0]` | 40 | **55** | combiner |
| `DIST_B0_St1_PTAT` | `0x104C[5:0]` | 40 | **50** | DIST St1 |
| `DIST_B0_St2_0_PTAT` | `0x104C[13:8]` | 13 | 13 | DIST St2 (**CH0-1용**) |
| `DIST_B0_St2_1_PTAT` | `0x104D[5:0]` | 0 | **13** | DIST St2 (**CH2-3용**) |
| `DIST_CTAT` | `0x1052[5:0]` | 8 | 8 | |
| `DIST_B0_St2_0_cbias` | `0x104D[11:9]` | 6 | 6 | |
| ptat_slope 1/2/3 | `0x1050[5:0]` / `0x1050[13:8]` / `0x1051[5:0]` | 6 / 6 / 6 | 동일 | |

방향: PA St1을 내리고(32→15) 구동단·합성단에 전류를 몰아준다(26→45, 40→55).

### RX — `Blueway RX Digital Settings` 시트, `NF_OPTIM` 열

| 필드 | 레지스터 | 기본(H0-B0) | **NF_OPTIM** | 기능 |
|---|---|---|---|---|
| `PTAT_St1` | `0x1038[5:0]` | 34 | 34 | St1 LNA |
| `PTAT_St2` | `0x1038[13:8]` | 30 | **24** | St2 LNA |
| `PTAT_St3` | `0x103C[5:0]` | 40 | **48** | St3 splitter |
| `DIST_B0_St1_PTAT` | `0x104C[5:0]` | 24 | **44** | DIST St1 combiner |
| `captune` | `0x1068[7:0]` | 119 | **136** | 0x77 → 0x88 |
| `extra_bits_B0` | `0x1058[7:0]` | 119 | **136** | |

### 적용 규칙

- **활성 채널/편파 원소에만 기입**한다. 비활성 행은 0.
  (MATLAB·Sivers 덤프와 동일한 규칙 — 출장 때 전 채널에 기입해서 diff가 어긋났던 항목이다.)
- CTAT/CBIAS는 시트에 최적화값이 없으므로 **die eFuse 리드백 값을 유지**한다.
- `optimized_bias = false`면 이 절의 필드를 eFuse 리드백 값으로 둔다.
  단 **TX 의 DIST 는 예외다** — step 18 의 `DIRECT_REGS_TX` 가 `0x104C`/`0x104D`/`0x1052` 를
  무조건 덮으므로 이 스위치와 무관하게 늘 MATLAB(=Casper) 값이다. §8.4 정정 참고.

### 열린 항목 — `0x104D[5:0]`

MATLAB 하드코딩은 `0x104D = 3100` → `[5:0] = 28`, 시트 v4 Casper는 **13**이다.
**시트 v4(13)를 기본값**으로 하되 `bench.toml`의 `dist_st2_1_ptat`으로 바꿀 수 있게 한다(실측 A/B 비교용).
`[11:9] = 6`(cbias)은 양쪽 일치하므로 고정한다.

---

## 6. 파라미터 계약 재설계

### 문제

현재는 사용자가 **레지스터 필드 이름 문자열**을 넘긴다: `gain_field="b0_common_gain"`, `channel_field="gain_control_h1"`.
이는 `chip.fields.wr(name, code)` 호출을 전제한 설계라 raw 기입과 맞지 않는다.

### 신규 계약

게인 조작 대상을 **타깃(target)** 으로 표현한다.

| `*_target` 값 | 대상 레지스터 | 코드 의미 |
|---|---|---|
| `common` | `0x1005 + beam_idx` | 빔 공통 감쇠 6-bit. 0 = 최대 게인 |
| `fe` | `0x1018 + ch_idx` (H=`[7:0]`, V=`[15:8]`) | 채널 FE 게인 4-bit |
| `beamtable` | beam table 워드 `addr = quad`, `[6:0]` | RTPS 감쇠 7-bit. 0 = 최대 게인 |

빔·채널은 기본적으로 `bench.board`(= `bench.toml [board]`)에서 가져온다. 필요할 때만 덮는다 —
`beam`(예: `"b1"`)과 `channel`(예: `"h1"`) 파라미터를 **모든 게인 조작 테스트 항목에 공통으로 추가**한다.
빈 문자열이 기본이고, 빈 값이면 `bench.board`를 따른다.

### 테스트 항목별 변경

| 테스트 | 기존 파라미터 | 신규 파라미터 |
|---|---|---|
| `op1db` | `gain_field="b0_common_gain"` | `gain_target="common"` |
| `ip1db` | `gain_field=""` | `gain_target="common"` |
| `gain_index_accuracy` | `common_field=""`, `channel_kind="beamtable"/"field"`, `channel_field="gain_control_h1"` | `common_target="common"`, `channel_target="beamtable"/"fe"` |
| `channel_gain_alignment` | `common_field=""` | `common_target="common"` |

`gain_code` · `common_codes` · `channel_codes` · `channel_quad` 는 그대로 둔다.

### 호환 shim

구 파라미터가 들어오면 **경고 로그 후 신규로 자동 매핑**한다. 기존 workbook 스크립트와 저장된 측정 CSV의 재현성을 지키기 위함이다.

```
gain_field="b0_common_gain"      -> gain_target="common", beam="b0"
gain_field="b1_common_gain"      -> gain_target="common", beam="b1"
gain_field="gain_control_h1"     -> gain_target="fe",     channel="h1"
channel_kind="field"             -> channel_target="fe"
channel_kind="beamtable"         -> channel_target="beamtable"
```

로그 문구: `[deprecated] gain_field is deprecated; use gain_target. Mapped to gain_target=common, beam=b0`

### 설계 근거 — `gain_control_*`는 이 칩에서 동작하지 않는다

`scripts/cloudchaser_workbook_ko.py:484`에 이미 기록돼 있다:

> 채널 손잡이: `channel_kind="beamtable"`(RTPS, 동작함) 유지. `"gain_control"`은 이 칩에서 DEAD.

따라서 `channel_target`의 **기본값은 `beamtable`** 로 두고 `fe`는 옵션으로 남긴다.

---

## 7. 설정 (`config/bench.toml` `[board]`)

기존 키(`chip_id` · `beam` · `active_channels` · `cal_freq_code` · `common_gain` · `ch_gain` · `ch_atten` · `ch_fe_attn`)는 그대로 유지한다. 아래 4개를 추가한다.

```toml
[board]
# ... 기존 키 ...

# DIST 스플리터 split 모드 (TX 전용).
#   true  = 0x1009=783, 0x1068=0x8888 추가 기입 (다채널 결합. Doosan 260729 설정)
#   false = thru (단일채널)
split_mode = true

# v4 시트의 최적화 bias 적용 여부. TX 에서는 FE bias 만 바뀐다(§8.4 정정 참고).
#   true  = TX Casper / RX NF_OPTIM 값을 활성 채널에 명시 기입
#   false = evb_full 베이스라인 (TX: FE 만 eFuse 로, DIST 는 DIRECT_REGS 고정 / RX: 둘 다 eFuse)
# 적용 전/후 gain·Pdc 델타를 비교하려면 이 값만 바꿔 두 번 측정한다.
optimized_bias = true

# 0x104D[5:0] = DIST_B0_St2_1_PTAT (CH2-3용). RX 에서는 무시된다.
#   13 = 시트 v4 Casper (기본)   /   28 = 기존 MATLAB 하드코딩
# 두 값 중 어느 쪽이 맞는지 실측 확인이 필요한 열린 항목이다.
dist_st2_1_ptat = 13

# 벤더 드라이버의 load_efuse() 실행 여부.
#   false = evb_full.py 와 동일 (spi.reset() 만). 기본값.
#   true  = chip.init() 호출 -> 레지스터 맵의 EFUSE_INSTRUCTIONS 스크립트 실행.
#           bring-up 이 그 8단계가 만지는 주소를 전부 덮으므로, 최종 레지스터에
#           남는 차이는 0x1055(daisy_chain3_bias)가 지워지는 것뿐이다(§12 참고).
run_efuse_init = false
```

---

## 8. 사용법

### 8.1 준비 (실험 PC)

```powershell
cd C:\claude_code\cloudchaser
git pull
.\.venv\Scripts\Activate.ps1
python -c "import sivers_api; print('sivers_api OK')"
```

FTDI 동글(C232HM MPSSE 케이블)이 USB에 연결돼 있어야 한다. 보드 전원은 세션의 전원 시퀀스가 인가한다(레일·순서는 `bench.toml`).

### 8.2 하드웨어 없이 먼저 확인 (fake dry-run)

레지스터 시퀀스만 눈으로 확인한다. 실험 PC가 아니어도 된다.

```powershell
python -m cloudchaser.runner run op1db --fake
python -m cloudchaser.regdump --fake --save out\fake_regs.csv
```

`out\fake_regs.csv`가 `addr,value` 형식으로 떨어진다. 골든 픽스처와 비교하려면
**명시적 `--range`** 가 필요하다(CLI 기본 `--range` 는 `0x1000 0x1204` 516워드인데
골든은 `0x1000`-`0x106F` 112워드만 덮는다) 그리고 `bench.toml [board]` 를 골든 설정
(`active_channels=["v1"]`, `beam="b0"`, `split_mode=true`, `common_gain=0x00`)에
맞춰야 한다(기본값은 `["h0"]`/`0x20`):

```powershell
python -m cloudchaser.regdump --fake --range 0x1000 0x1070 --diff tests\data\golden_regs_tx_v1_split.csv
#  -> "2 differing / 112 compared" 이면 정상 (0x1045/0x1049 잔차, 아래 참고)
```

**`0 differing` 이 아니라 `2 differing`이 정상이다.** `Sivers_EVB/evb_full.py` 의
`MockSPI` 와 `sivers_api.Fake_SPI` 의 eFuse 시드가 다르기 때문에(둘 다 fake 라 각자
다른 값을 심는다) `0x1045`/`0x1049` 두 레지스터가 항상 남는다 -- §8.5 가 "허용 가능한
잔차"로 분류한 것과 같은 종류(다이별 eFuse bias)이지 SW 버그가 아니다.

### 8.3 실칩 bring-up + 측정

```powershell
python -m cloudchaser.session        # 대화형 세션 진입 (전원 인가 + bring-up)
```

세션 안에서:

```python
op1db(freq_hz=28e9, gain_target="common", gain_code=0x20)
gain_index_accuracy(sg_level_dbm=0, channel_target="beamtable", channel_quad=1)
channel_gain_alignment(freq_hz=28e9, common_target="common")
ip1db(freq_hz=19.5e9, gain_target="common", gain_code=0)      # RX
```

`gain_target` / `channel_target` 을 생략하면 각각 `common` / `beamtable` 이 기본이다.
빔·채널은 `bench.toml [board]`의 `beam` · `active_channels`를 따른다.

> 구 파라미터(`gain_field=` 등)를 써도 동작하지만 `[deprecated]` 경고가 찍힌다. 새 이름으로 바꾸는 것을 권장한다.

### 8.4 optimize bias 적용 전/후 비교 (이번 작업의 핵심 사용 시나리오)

출장 결론이 "gain 미달 원인 = IC die 편차"였으므로,
**명시적 bias write가 die 편차를 얼마나 흡수하는지**가 실질 관전 포인트다. 같은 코드로 두 번 측정한다.

**① 적용 후 (기본)**

```powershell
# bench.toml:  optimized_bias = true
python -m cloudchaser.runner run op1db --out out\op1db_casper.csv
python -m cloudchaser.regdump --save out\regs_casper.csv
```

**② 적용 전 (eFuse 기본값)**

```powershell
# bench.toml:  optimized_bias = false  로 수정
python -m cloudchaser.runner run op1db --out out\op1db_efuse.csv
python -m cloudchaser.regdump --save out\regs_efuse.csv
```

**③ 비교**

```powershell
python -m cloudchaser.regdump --diff out\regs_efuse.csv --ours out\regs_casper.csv
```

차이가 **`0x1038`/`0x103C`(FE PTAT)에만** 나와야 한다. 그 외 레지스터가 뜨면 설정이 섞인 것이다.

> **정정 (최종 리뷰, Ruling 37).** 이 절은 원래 `0x104C`(DIST St1)도 갈린다고 적었지만
> 실측상 **DIST bias 는 `optimized_bias` 로 안 바뀐다.** step 10 의 `set_dist_bias()`
> 결과를 step 18 의 `DIRECT_REGS_TX`(`0x104C`=3378, `0x104D`, `0x1052`=8)가 무조건
> 덮어쓰기 때문이다. 즉 TX 에서 `optimized_bias=false` 는 "최적화 전부 해제"가 아니라
> **evb_full 베이스라인**이다 — FE 는 eFuse 리드백, DIST 는 MATLAB 이 늘 쓰던 값 고정.
> 이건 버그가 아니라 의도다: `DIRECT_REGS_TX` 값은 `evb_full.py` 의 MATLAB 하드코딩에서
> 왔고, v4 시트 분석에 따르면 그 DIST 값들이 곧 Casper 값이다(MATLAB 은 처음부터
> 최적화된 DIST 를 썼다). `DIRECT_REGS_TX` 를 조건부로 만들면 `evb_full` 과 갈라져
> 이 브랜치의 1번 목표(레지스터 동일성)가 깨진다.
> **DIST 를 정말 A/B 하려면 `board/bringup.py` 의 `DIRECT_REGS_TX` 를 직접 편집해야 한다.**
> RX 는 다르다 — `DIRECT_REGS_RX` 에 `0x104C~` 가 없어서 `optimized_bias` 가 FE·DIST 를
> 둘 다 되돌린다.

OP1dB / Pdc 델타는 두 CSV를 비교한다. `0x104D`(13 vs 28) 확인도 같은 방식으로 한다
(이건 `DIRECT_REGS` 경로라 `optimized_bias` 와 무관하게 항상 적용된다):

```powershell
# bench.toml:  dist_st2_1_ptat = 28  로 바꾸고 재측정
```

### 8.5 Sivers 덤프와 대조 (실칩 검증)

출장 때 Sivers 코드로 bring-up해 뜬 레퍼런스 덤프가 `reference/Data_260729_DoosanSTMP_RegDump.xlsx`에 있다.

```powershell
python -m cloudchaser.regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx
```

**판정 기준** (출장 때 확립한 것):

| 결과 | 해석 |
|---|---|
| 잔차가 **다이별 eFuse bias에만** 남음 (`0x1041`/`0x1045`/`0x1049` fe_bias, `0x1055` daisy) | 정상. SW 포팅 맞음, 남은 차이는 die 개체차 |
| 그 외 config 레지스터(routing/enable/pwrdn/DIRECT/extra/captune/ADC/temp)에도 잔차 | SW 문제. §8.6 체크리스트 |

단, Sivers 덤프는 `CHANNELS=["v1"]` + `SPLIT_MODE=true` 설정에서 뜬 것이다. 대조하려면 `bench.toml`을 맞춰야 한다:

```toml
[board]
active_channels = ["v1"]
beam = "b0"
split_mode = true
```

**xlsx 손상 행 주의**: 레퍼런스 파일의 `0x10E0`-`0x10E9` 10개 행은 Excel 이 지수표기로
자동변환해 원본 주소를 복구할 수 없다(regdump.py 의 xlsx 로더 조사, Task 11/12). `regdump`
는 로드 시점에 이걸 알린다:

```
note: 10 row(s) at 0x10E0-0x10E9 could not be parsed and were not compared
```

이 10개 레지스터는 diff 대상(`M compared`)에서 제외되므로, 그 구간은 이 대조로
검증되지 않는다.

### 8.6 문제 발생 시 체크리스트

| 증상 | 확인 |
|---|---|
| `version_id = 0x0` | 보드 전원 미인가. `bench.toml` 레일 순서 확인 |
| `version_id` 가 0xDC/0xD4 아님 | FTDI USB 연결 / D2XX 드라이버 |
| config 레지스터에 잔차 | `run_efuse_init` 이 `true`로 켜져 있지 않은지 확인 (켜면 evb_full과 달라짐) |
| TX에서 의도한 편파가 안 켜짐 | `0x1010+ch` 의 pwrdn 비트순서. **TX는 h=[5:3]/v=[2:0]로 RX와 반대** |
| RTPS 위상이 안 먹음 | `zero_phase_cal()` 이 bring-up에 있는지 (`0x106C`~ 280워드가 0인지 덤프로 확인) |
| 게인을 바꿨는데 출력이 그대로 | `gain_target="fe"` 를 쓰고 있지 않은지. `gain_control_*` 는 이 칩에서 DEAD — `beamtable` 을 쓸 것 |
| 측정 중 설정이 되돌아감 | 벤더 `fields.wr()` 잔존 여부. 쓰기 경로에 `chip.fields.wr` 가 남아 있으면 안 된다 |

### 8.7 레지스터를 직접 만질 때

`session.py`의 네임스페이스에 bring-up 때 만든 FH 엔진을 **`fh`** 라는 이름으로 노출한다
(기존 `C`(chip 객체)·`B`(bench)와 같은 방식).

```python
# 세션 안에서
fh.rd(0x104C)                    # 읽기
fh.wr_verify(0x104C, 3378)       # 쓰기 + readback 검증
fh.get_fe_bias()                 # die eFuse FE bias 8x5
fh.get_dist_bias()               # DIST bias 3x6 + CTAT
```

### 8.8 `regdump` CLI 레퍼런스

```
python -m cloudchaser.regdump [옵션]

  --fake              하드웨어 없이 실행(fake SPI). bring-up 후 덤프.
  --no-power          전원 인가 생략(이미 켜져 있을 때).
  --save PATH         덤프를 addr,value CSV로 저장.
  --diff PATH         기준 덤프와 비교(theirs). .csv / .xlsx 모두 지원.
  --ours PATH         비교 대상(ours)을 파일에서 읽는다. 생략하면 실칩을 라이브로 읽는다.
  --range A B         덤프 주소 범위(기본 0x1000 0x1204).

예)
  python -m cloudchaser.regdump --save out\regs.csv
  python -m cloudchaser.regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx
  python -m cloudchaser.regdump --diff out\regs_efuse.csv --ours out\regs_casper.csv
```

출력은 다른 레지스터만 한 줄씩 찍고 마지막에 `N differing / M compared` 로 끝난다
(`evb_full.py`의 `regdiff()`와 동일한 형식).

---

## 9. 검증 계획

| # | 항목 | 방법 | 하드웨어 |
|---|---|---|---|
| 1 | 레지스터 동일성 | `tests/test_bringup_golden.py` — fake bring-up 덤프 vs 골든 픽스처 정확 일치 | 불필요 |
| 2 | 골든 픽스처 생성 | `Sivers_EVB/evb_full.py`를 fake로 돌려 `dump()` → `tests/data/golden_regs_*.csv` 로 고정 | 불필요 |
| 3 | 기존 테스트 회귀 | `python -m pytest` 전량 통과 | 불필요 |
| 4 | 파라미터 shim | 구 이름 → 신규 매핑 단위 테스트 | 불필요 |
| 5 | 실칩 대조 | `regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx` | **필요** |
| 6 | bias 전/후 델타 | §8.4 절차 | **필요** |

### 골든 픽스처 주의

두 fake의 eFuse 시드가 다르다 — `evb_full.MockSPI`는 `_seed_efuse()`로 가짜 eFuse를 심고,
`sivers_api.Fake_SPI`는 전 레지스터 0에서 시작한다. 따라서:

- `optimized_bias = true`: bias를 명시 기입하므로 결정적 → **전 구간 비교**
- `optimized_bias = false`: FE bias가 eFuse 유래 → **eFuse 유래 레지스터 제외 후 비교**
  (TX 의 DIST 는 `DIRECT_REGS_TX` 고정이라 여전히 결정적이다 — §8.4 정정)

이 "결정적 → 전 구간 비교"는 `tests/test_bringup_golden.py` 처럼 **테스트가 직접
`seed_efuse()`로 두 fake 의 eFuse 를 동일하게 맞춘 경우**에 성립한다(CTAT/CBIAS 는
`optimized_bias=true` 여도 v4 시트에 값이 없어 eFuse 리드백을 그대로 쓰므로, 시드가
같아야 이 필드까지 일치한다). `python -m cloudchaser.regdump --fake --diff ...` 처럼
그런 수동 시딩 없이 CLI 로 즉석 비교하면 `sivers_api.Fake_SPI` 의 미시딩 eFuse(전부 0)가
그대로 남아 CTAT/CBIAS 필드(`0x1045`/`0x1049` 등)에 잔차가 생긴다 — §8.2 참고.

### 갱신이 필요한 기존 테스트

- `tests/test_session_ux.py:366` — `"param.gain_field: b1_common_gain"` 문자열 assert
- `tests/test_test_items_fake.py:165,179` — `test_gain_common_field_follows_beam`, `test_ip1db_gain_field_follows_beam`

---

## 10. 영향 파일

**신규**

`board/firehawk.py` · `board/bias_v4.py` · `board/gain_map.py` · `regdump.py` ·
`tests/test_bringup_golden.py` · `tests/data/golden_regs_*.csv`

**수정**

`board/bringup.py` · `board/__init__.py` · `bench.py`(BoardConfig 4필드) · `config/bench.toml` ·
`test_items/{op1db,ip1db,gain_index_accuracy,channel_gain_alignment,evm,phase_index_accuracy}.py` ·
`session.py`(파라미터 화이트리스트 51-69, tx_suite 유도 585-588) · `manual.py`(쓰기 헬퍼) ·
`scripts/cloudchaser_workbook.py` · `scripts/cloudchaser_workbook_ko.py` ·
`docs/SESSION.md` · `README.md` · `tests/test_session_ux.py` · `tests/test_test_items_fake.py`

**건드리지 않음**

`instruments/` · `loss.py` · `runner.py`(CSV 저장) · `docs/sivers_unified_api_v0.1.0/` · `docs/Cloudchaser_drv-v1.0.0/`

---

## 11. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| **실칩 미검증** | fake에서 맞아도 실칩에서 다를 수 있다 | 출장 때와 동일한 한계. §8.5 대조를 실험 PC에서 반드시 수행 |
| `load_efuse()` 생략이 실칩에서 문제 | bias 트림이 레지스터에 안 올라올 수 있다 | 출장 때 evb_full이 이것 없이 Sivers 덤프와 일치한 것이 반대 증거. **주의: `run_efuse_init` A/B 로는 이걸 확인할 수 없다** — 확인 방법은 아래 §12 참고 |
| 쓰기 경로에 `fields.wr` 잔존 | 측정 중 설정이 조용히 되돌아감 | grep 기반 회귀 테스트로 고정 |
| `0x104D` 13 vs 28 미확정 | DIST St2 CH2-3 bias가 틀릴 수 있다 | config 노출. 단일 채널(v1) 측정에서는 CH2-3 경로가 꺼져 있어 영향 없음 |
| 파라미터 변경으로 기존 스크립트 파손 | workbook·저장된 측정 재현 불가 | deprecation shim + 문서 갱신 |

---

## 12. 열린 항목

1. `0x104D[5:0]` = 13(시트 v4) vs 28(MATLAB) — 실칩 A/B 필요
2. `load_efuse()` 실칩 필요 여부 — **`run_efuse_init` A/B 로는 답이 안 나온다(최종 리뷰 확인).**
   Stampede rev_1 의 `EFUSE_INSTRUCTIONS` 는 8단계뿐이고 `0x1055` / `0x1058` / `0x1059` /
   `0x1068`-`0x106B` 만 만지는데, bring-up 이 그 **전부**를 뒤에서 덮는다(step 8 captune,
   step 11 extra, step 18 DIRECT_REGS, step 19 split). 그래서 `run_efuse_init=true` 로
   켜도 최종 레지스터에 남는 차이는 `0x1055` 의 `daisy_chain3_bias` 가 (RCLR 로) **지워진다**는
   것 하나뿐이다 — "bias 트림이 안 올라왔나"를 이 스위치로 A/B 하면 아무 신호도 못 얻는다.
   진짜 확인 방법: **bring-up 전에** `0x1055`/`0x1058`/`0x1059` 와
   `get_fe_bias()`/`get_dist_bias()` 를 읽어 남긴다(`docs/SESSION.md` §8 참고).
3. Casper/NF_OPTIM 적용 전후 gain·NF·Pdc 델타 — 측정 후 `_vault`의 EVB 측정 델타 문서에 반영
