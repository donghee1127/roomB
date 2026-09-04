# COMMANDS — 커맨드 보관소 (복붙용 명령 레퍼런스)

CloudChaser **Stampede2731 (TX) EVB** 를 `cc.bat` 인터랙티브 세션에서 **수동으로** 제어할 때
그대로 복사-붙여넣기 할 수 있는 명령 모음이다. 카테고리별로 정리돼 있고, 맨 뒤에 **전체 레지스터/
필드 표**(부록 A·B)가 붙어 있어 `rd()/wr()` 에 넣을 필드 이름을 바로 찾을 수 있다.

- 이 문서 = **명령 사전**(무엇을 친다). 측정 **절차/이유**(왜·언제)는 [SESSION.md](SESSION.md).
- 명령 시그니처의 원본은 `src/cloudchaser/session.py`(세션·측정) 와 `src/cloudchaser/manual.py`
  (보드/계측기 헬퍼). 레지스터/필드는 `docs/register_maps/Cloudchaser_Stampede_register_map.xlsx`.
- 부록 A·B 표는 `scripts/dump_register_map.py` 로 재생성한다(맵 xlsx 가 바뀌면 다시 실행).

## 0. 사용법 — 한 줄 흐름

```text
cc.bat 더블클릭(또는 cmd 에서 cc)  →  IPython 진입
```
```python
start(channels=['h1'])          # 연결 + 전원 램프업 + bring-up + 명령어 주입
help()                          # 쓸 수 있는 명령 한눈에
# ... 아래 블록들을 복붙해서 측정 ...
shutdown()                      # 끝나면 전원 0V (exit() 해도 자동 실행됨)
```

세션에 자동 주입되는 **객체**(import 불필요):

| 객체 | 정체 | 쓰임 |
|---|---|---|
| `B` | `Bench` | 계측기/보드 핸들: `B.psu1` `B.psu2` `B.sg` `B.sa` `B.board` |
| `C` | sivers_api `Stampede` | 칩: `C.fields` `C.regs` `C.path` `C.beam_table` `C.spi` |
| `bench`,`psu1`,`psu2`,`sg`,`sa`,`chip` | 위와 동일 객체의 별칭 | manual 콘솔과 이름 공유 |

> ★ 구(舊) TX EVB 는 H0·V0·H2 driver단 RF 경로 HW 불량이 있었다(B0·B1 양쪽 동일, 레지스터
> 덤프로 확정). **새 TX EVB 로 교체됨 — 전 채널 사용 가능(재검증 진행 중).**

---

## 1. 세션 시작·종료

```python
start(channels=['h1'])                 # 표준: 자동 감지(TX/RX)+전원+bring-up. 감지 후 확인받음
start(channels=['h1'], chip='tx')      # TX 강제(검증). 실제 칩과 다르면 경고+일시정지
start(channels=['h1'], chip='rx')      # RX 강제(검증)
start(channels=['h1','h3','v1'])       # 여러 채널 동시 ON
start(channels=['h1'], chip='tx', fake=True)  # 하드웨어 없이 점검(fake 는 감지 생략)
start(channels=['h1'], power=False)    # 전원 램프업 생략(감지도 생략, 연결+bring-up 만)
start(channels=['h1'], beam='b1')      # 빔 포트 b1 사용(기본 b0)
restart(channels=['h1'])               # 닫고 같은 식으로 다시 start
status()                               # 현재 채널/공통게인/SG 상태
help()           ;  help('rf')         # 전체 명령 / 특정 명령 상세
shutdown()                             # RF off + 전 레일 0V(데이터시트 6.3 계단식). exit() 시 자동 실행
```

---

## 2. 채널 bring-up · 라우팅

```python
chan('h1')                  # 채널 1개를 '측정 가능 상태'로: 전체 OFF -> center bias ON
                            #   -> 해당 채널만 빔 라우팅 -> RTPS(beam table) 0 -> 공통게인 최대
chan('v1', 'b1')            # 빔 b1 으로 v1 준비
enable('h1')                # 채널 ON(현재 빔으로 라우팅)
enable('h1','h3','v1')      # 여러 채널 한 번에 ON
disable('h1')               # 채널 1개 OFF
disable()                   # 전체 OFF
paths()                     # 현재 활성 beam->채널 라우팅 출력
```

`chan()` 이 측정 직전 상태(center bias+RTPS0+max gain)까지 한 번에 만들어 주므로, 단일 채널
신호 확인은 보통 `chan()` 하나로 충분하다. 직접 단계별로 하려면 §4 수동 bring-up 참고.

---

## 3. 게인 · 감쇠 · 위상

게인 코드는 **감쇠 코드**다: `0` = 최대 게인, `0x3f` = 최대 감쇠.

```python
gain(0)                     # 빔 공통 게인 = 최대 (b{n}_common_gain 에 씀)
gain(0x20)                  # 공통 게인 중간값
chgain('h1', 0x8)           # 채널별 게인(gain_control_h1, 4-bit)
atten('h1', 0x0)            # 채널-빔 디지털 감쇠(ch1_h_b0_attn_cal)
phase('h1', 0x40)           # 채널별 RTPS 위상(beam table phase_shifter_setting, 7-bit)
rtps()                      # beam 0 의 quad 별 atten/phase 코드 출력(read=True: 디바이스 재독)
```

`phase()` 주의사항:
- 7-bit raw 코드(0~127)만 받는다. 코드→도(°) 변환식은 벤더 문서에 없어 **미검증**
  (360/128=2.8125°/step 은 추정일 뿐).
- beam table 은 quad 단위라 같은 숫자의 h/v 채널(h1/v1)이 같은 워드를 공유한다 —
  단일 채널만 활성인 상태에서 쓰는 것을 권장.
- `chan()` 은 beam table 을 0 으로 클리어하므로 채널 재선택 시 위상도 0 으로 리셋된다.

---

## 4. 레지스터 직접 제어

필드 이름 ↔ 주소/비트는 **부록 B**. 모르는 필드는 거기서 찾는다. **이름은 소문자**다 —
레지스터 맵 표기(`d2a_DIST_B0_St1_PTAT`) 그대로 넣으면 `KeyError` 가 난다.

### 필드 단위 (이름으로)

```python
rd('d2a_dist_b0_st1_ptat')          # 필드 읽기 (값 출력 + 반환)
rd('b0_common_gain')
wrf('d2a_dist_b0_st1_ptat', 50)     # 필드 쓰기 -- 나머지 비트는 그대로 둔다
wrf('centerbias_en', 1)
wrf('b0_common_gain', 0, verify=False)   # 리드백 검증 생략
```

`wrf` 출력 예 — 어느 워드가 어떻게 바뀌었는지 그대로 보여준다:

```
  0x104C: 0x0D32 -> 0x0D28  [5:0] = 40
  d2a_dist_b0_st1_ptat = 0x28 (40)
```

주소/비트 위치는 벤더 필드 표에서 가져오지만, **쓰기는 fh 를 통한 raw
read-modify-write** 다 — 벤더 `fields.wr()`/`commit()` 의 shadow-cache 경로는 쓰지
않는다(Ruling 28). 값이 필드 폭을 넘으면 `ValueError` 로 막는다.

### raw 워드 단위 (주소로)

```python
fh.rd(0x104C)                       # 16-bit 워드 읽기 -> 3378 (0x0D32)
fh.wr_verify(0x104C, 0x0D28)        # 쓰기 + 리드백 대조(3회 재시도, 불일치 시 [warn])
fh.wr(0x104C, 0x0D28)               # 검증 없는 생 write
```

> ⚠️ **한 워드에 필드가 여러 개 있다.** 예를 들어 `0x104C` 는
> `d2a_dist_b0_st1_ptat`[5:0] 과 `d2a_dist_b0_st2_0_ptat`[13:8] 을 같이 담는다.
> `fh.wr_verify(0x104C, 50)` 처럼 통째로 쓰면 이웃 필드가 0 으로 날아간다.
> 마스크를 직접 짜기 싫으면 `wrf()` 를 쓴다.

### 상태 확인 / 대조

```python
dump()                              # 0x1000~0x1203 현재 상태 {addr: value} (bring-up 재실행 안 함)
dump(b=0x1070)                      # config 영역만 (112개, 빠름)
dump('out/regs.csv')                # CSV 로도 저장
regdiff('reference/Data_260729_DoosanSTMP_RegDump.xlsx')   # 레퍼런스 대비 차이만 출력
load_golden()                       # 정상 레지스터 스냅샷 전체 주입(docs/golden_h0b0_25g.json)
```

묶음 setter/getter 는 `fh` 에 있다(`fh.get_dist_bias()`, `fh.set_dist_bias(bias, ctat)`,
`fh.get_fe_bias()`, `fh.set_captune()`, `fh.set_beam_enables()` ...). 전체 목록은
`src/cloudchaser/board/firehawk.py`.

> **손으로 쓴 값은 bring-up 이 다시 돌면 날아간다.** `restart()` 는 물론 `split()` 도
> bring-up 을 재실행한다. 특히 `0x104C`/`0x104D` 같은 DIST bias 워드는 `optimized_bias`
> 설정과 무관하게 매 bring-up 마다 `DIRECT_REGS_TX` 값으로 덮인다
> (`0x104C = 3378` -> `d2a_dist_b0_st1_ptat = 50`). 값을 고정하려면
> `src/cloudchaser/board/bringup.py` 의 `DIRECT_REGS_TX` 를 고친다.

> **없어진 명령**: 예전 문서의 `wr('field', v)` / `commit()` / `latch()` 와
> `C.regs.wr()` / `C.fields.set_many()` 는 더 이상 쓰지 않는다. raw-register 이관 때
> 제거된 벤더 shadow-cache write 경로이고, 세션 네임스페이스에도 없다.
> 읽기(`C.regs.rd`, `C.fields.rd`)는 HW 를 직접 읽으므로 그대로 써도 된다.

### 수동 bring-up 시퀀스 (start() 가 자동으로 하는 것을 직접)

`path.enable()` 은 center 마스터 바이어스를 **안 켜므로** `centerbias_en`/`centermirror_en` 을
수동 ON 해야 RF 가 분배망/RTPS 를 통과한다. (채널 h1, 빔 b0 예시)

```python
disable()                            # 전체 OFF 에서 시작
wrf('centerbias_en', 1)              # ★ center 바이어스 ON (필수)
wrf('centermirror_en', 1)            # ★ center 미러 ON (필수)
enable('h1')                         # 채널 h1 -> 빔 b0 라우팅
wrf('ch1_cal_freq_sel_beam0', 0)     # 보정 대역 선택
wrf('b0_common_gain', 0)             # 빔 공통 게인(0=최대)
wrf('gain_control_h1', 0x8)          # 채널 게인 (TX. 이 칩에서 DEAD 라 반응 없음)
wrf('ch1_h_b0_attn_cal', 0x0)        # 채널-빔 감쇠
fh.zero_phase_cal(); fh.beam_up()    # RTPS=0(최소감쇠/위상0) + 적용
```

> 빔은 `b0`/`b1` 두 포트뿐. 채널 인덱스 i 와 편파 p(h/v)에 대해 필드 이름은
> `gain_control_{p}{i}`, `ch{i}_{p}_b{n}_attn_cal`, `ch{i}_cal_freq_sel_beam{n}`, `ch{i}_{p}_enables`.

---

## 5. 진단

```python
chan('h1'); biasscan('h1')          # 각 증폭단(PA/Driver/Comb) 바이어스 0->63 흔들며 레일 전류 변화
                                    #   변화 없으면 그 단이 죽은 것. (해당 채널만 켠 뒤 호출)
vi()                                # 전 레일 V/I 출력(증폭기 전류 상승 = 동작 확인)
```

정상/불량 채널 일괄 비교(세션 없이, RF 불필요 — DC 정지전류만):

```powershell
python -m cloudchaser.biasscan_compare --good h1 --bad h0,v0,h2   # 단별 delta 나란히 + verdict
python -m cloudchaser.biasscan_compare --no-power --csv out/biasscan.csv
```
- good 채널은 응답(delta>2mA)하는데 bad 채널이 flat 인 단을 `DEAD` 로 표시.
- 구 EVB 의 H0/V0/H2 driver(FE2_1V8) 단 결함 검증에 사용했던 절차 — 새 EVB 재검증에도 그대로 사용.

driver 단이 죽은 게 '설정/efuse 차이'인지 '실리콘/HW 결함'인지 가르기(레지스터 diff):

```powershell
python -m cloudchaser.driver_reg_diff --good h1,v1 --bad h0,v0,h2   # 같은 편파 정상 채널 기준 per-channel 레지스터 1:1 비교
python -m cloudchaser.driver_reg_diff --no-power --csv out/regdiff.csv
```
- 전 필드 동일 → 설정은 같은데 동작만 죽음 → 실리콘/HW 결함 확정.
- driver 바이어스(ptat_st2/ctat/enables/pwrdn/bias_en/efuse) 가 다르면 → 설정/efuse 문제 의심.

Sivers 전달용 결함 리포트(위 두 진단을 합쳐 영어 리포트 + 파일 저장):

```powershell
python -m cloudchaser.sivers_report                 # 전 채널 테스트, out/sivers_driver_report_<ts>.txt 저장
python -m cloudchaser.sivers_report --no-power --out report.txt
```
- TEST1: 전 채널 St2(driver) 바이어스 0->63 응답 PASS/FAIL + St1/St3 대조.
- TEST2: FAIL 채널 vs 같은 편파 정상 채널 레지스터 diff(게이팅 동일 / 트림만 차이).
- CONCLUSION: 게이팅 동일 + 바이어스 무반응 → HW 결함 단정 문구까지 자동 생성.

---

## 6. 신호발생기 SG (R&S SMW200A)

```python
rf(True, freq=28e9, level=-10)      # 주파수/레벨 설정 후 RF ON
rf(False)        ;  rfoff()         # RF OFF
level(-5)                           # 출력 레벨[dBm]만 변경(주파수/RF상태 유지)
```

하위(직접 제어가 필요할 때):

```python
B.sg.set_frequency(28e9)            # CW 주파수[Hz]
B.sg.set_level(-10)                 # 출력 레벨[dBm]
B.sg.rf_output(True)                # RF on/off
B.sg.configure(freq_hz=28e9, level_dbm=-10, rf_output=False)
B.sg.setup_nr5g(bw_mhz=100, link="DOWN", scs_khz=120)   # 5G NR baseband(K144)
B.sg.load_waveform(path)            # ARB 파형 로드
B.sg.modulation_off()               # 변조 끄고 CW 로
```

---

## 7. 스펙트럼분석기 SA (R&S FSVA3030)

```python
saconf(center=28e9, span=100e6, ref=20)   # SA 설정(center 기본=현재 SG 주파수). 측정 전 1회
peak()                                    # 단일 sweep, 마커 피크[dBm] (raw)
peakc(28)                                 # 손실보정 IC 출력 = raw + out_loss(28GHz)
```

하위(EVM / ACP / NR 전력 직접):

```python
B.sa.configure(center_hz=28e9, span_hz=100e6, rbw_hz=1e6, ref_level_dbm=20)
B.sa.measure_peak_dbm()                   # 단일 sweep + 피크
B.sa.setup_nr5g_analyzer(center_hz=28e9, bw_mhz=100)   # NR 분석 셋업(K144)
B.sa.read_evm_db()  ;  B.sa.read_nr_power_dbm()
B.sa.setup_acp(center_hz=28e9, chan_bw_hz=99e6, spacing_hz=100e6, n_adj=1)
B.sa.read_channel_power_dbm()  ;  B.sa.read_acp_dbc()   # 채널전력 / (하측,상측) dBc
```

---

## 8. 전원 PSU (Keysight E36313A ×2)

```python
vi()                                # 전 레일 V/I (가장 자주 씀)
shutdown()                          # RF off + 데이터시트 6.3 계단식 강하로 전 레일 0V
```

레일 이름: PSU1 = `FE1_4V0` `CORE_1V0` `IO_ANA_1V8` / PSU2 = `DIST_1V8` `FE2_1V8` `FE3_1V8`.

> `shutdown()`/`power_down()` 은 계단식 강하를 따른다(bench.toml `power_down_stages`).
> TX: 4V->1.8V->1V->0V, RX: 1.8V->1.5V->1V->0V. 각 plateau 에서 그보다 높은 레일을 함께 내리고
> 디지털 레일(VDD_DIG)은 마지막에 0V 로 내린다. plateau 사이에는 `stage_delay_s`(TX 0.5s)만큼 쉰다.
>
> 파워업도 같은 다이어그램의 스테이지를 따른다(bench.toml `power_up_stages`):
> TX ① CORE_1V0(1.0V) → ② DIG/IO/FE2/FE3(1.8V, 여기서 SPI active) → ③ FE1(4V).

하위(레일 개별 제어 — **주의**):

```python
B.psu1.read_vi()                    # PSU1 레일만 V/I
B.psu1.ramp_rail('CORE_1V0', step_v=0.2, settle_s=0.1)      # 안전 램프업(단계적)
B.psu1.ramp_rail_down('CORE_1V0')                           # 안전 램프다운
B.psu1.tripped()                    # OVP/OCP 트립 여부
B.psu1.output(False, channels=[1,2,3])
```

> ★ `B.psu1.set_voltage(ch, v)` 는 램프 없이 즉시 인가 — 위험. 정상 사용은 `ramp_rail`.

---

## 9. 경로 손실 보정

손실은 `Loss_data/` 의 VNA CSV(SG_Cable / SA_Cable / Board_Trace)에서 주파수별로 자동 로드된다.

```python
loss()                              # 전체 손실 테이블 출력
loss(28)                            # 28GHz 의 in_loss / out_loss
peakc(28)                           # 손실보정 IC 출력 = SA raw + out_loss
```

---

## 10. 측정 항목 (복붙 한 줄 + 상세 링크)

자동 측정 함수. 경로 손실은 Loss_data CSV 에서 주파수에 맞춰 자동 적용되고, 결과는 `out/` 에 CSV
저장된다. 파라미터/절차 상세는 [SESSION.md §6](SESSION.md) 참고.

```python
op1db(freq_hz=28e9, gain_code=0)                     # OP1dB 압축점.        상세: SESSION.md §6-1
gain_index_accuracy(sg_level_dbm=0)                  # 게인 인덱스 정확도.  상세: SESSION.md §6-2
channel_gain_alignment(channel_mode='all')           # 채널 게인 정렬(대화). 상세: SESSION.md §6-3
channel_gain_alignment(channels_script='h1,h3,v1')   #   비대화(자동) 측정
evm(freq_hz=28e9, modulation='setup')                # EVM(5G NR).          상세: SESSION.md §6-4
acp(freq_hz=28e9)                                    # ACP(인접채널전력비). 상세: SESSION.md §6-5
params('op1db')                                      # 그 테스트의 파라미터/기본값
tests()                                              # 사용 가능한 테스트 목록
```

손실은 **SG/SA 오프셋으로 자동 적용**된다(SG=−in_loss, SA=+out_loss). VNA CSV 를 `Loss_data/` 에 넣으면 즉시 반영(`set_loss(in,out)` 로 수동 override, `set_loss()` 로 해제).

---

## 11. 전형적 흐름 예시 (복붙 블록)

**단일 채널 신호 확인**
```python
start(channels=['h1'])
chan('h1')                          # 측정 준비(center bias+RTPS0+max gain)
rf(True, freq=28e9, level=-10)
saconf(center=28e9, ref=20)
peak()                              # 노이즈 플로어 위 실제 톤이 보이나?
vi()                                # FE 전류가 올랐나?(증폭기 동작)
shutdown()
```

**멀티 채널 레벨 스윕**
```python
start(channels=['h1','h3','v1'])
gain(0)                             # 최대 게인
rf(True, freq=28e9, level=-20)
saconf(center=28e9, ref=20)
for lv in [-20, -15, -10]:
    level(lv); print(lv, peak())
shutdown()
```

**OP1dB 측정**
```python
start(channels=['h1'])
op1db(freq_hz=28e9, gain_code=0, pin_start_dbm=-20, pin_stop_dbm=5)
shutdown()                          # CSV 는 out/ 에 저장됨
```

---

## 부록 A — 전체 레지스터 (이름 / hex / dec)

97개. `scripts/dump_register_map.py` 출력(맵 xlsx 기준).

| Register | Addr (hex) | Addr (dec) |
|---|---|---|
| `chip_info` | 0x1000 | 4096 |
| `unique_id_l` | 0x1001 | 4097 |
| `unique_id_h` | 0x1002 | 4098 |
| `status` | 0x1003 | 4099 |
| `output_daisy_amp_control` | 0x1004 | 4100 |
| `common_gain_b0` | 0x1005 | 4101 |
| `common_gain_b1` | 0x1006 | 4102 |
| `center_control` | 0x1008 | 4104 |
| `center_dist_b0` | 0x1009 | 4105 |
| `center_dist_b1` | 0x100A | 4106 |
| `temp_adc_dctest_pwrdn` | 0x100B | 4107 |
| `quad0_enables` | 0x100C | 4108 |
| `quad1_enables` | 0x100D | 4109 |
| `quad2_enables` | 0x100E | 4110 |
| `quad3_enables` | 0x100F | 4111 |
| `quad0_pwrdn` | 0x1010 | 4112 |
| `quad1_pwrdn` | 0x1011 | 4113 |
| `quad2_pwrdn` | 0x1012 | 4114 |
| `quad3_pwrdn` | 0x1013 | 4115 |
| `cal_freq_adj_ch0` | 0x1014 | 4116 |
| `cal_freq_adj_ch1` | 0x1015 | 4117 |
| `cal_freq_adj_ch2` | 0x1016 | 4118 |
| `cal_freq_adj_ch3` | 0x1017 | 4119 |
| `quad0_gain_ctrl` | 0x1018 | 4120 |
| `quad1_gain_ctrl` | 0x1019 | 4121 |
| `quad2_gain_ctrl` | 0x101A | 4122 |
| `quad3_gain_ctrl` | 0x101B | 4123 |
| `ch0_pd_dctest_ctrl` | 0x101C | 4124 |
| `ch1_pd_dctest_ctrl` | 0x101D | 4125 |
| `ch2_pd_dctest_ctrl` | 0x101E | 4126 |
| `ch3_pd_dctest_ctrl` | 0x101F | 4127 |
| `dctest_ctrl` | 0x1021 | 4129 |
| `temp_sense_ctrl` | 0x1022 | 4130 |
| `temp_adc_data` | 0x1023 | 4131 |
| `ch0_h_pd_data` | 0x1024 | 4132 |
| `ch0_v_pd_data` | 0x1025 | 4133 |
| `ch1_h_pd_data` | 0x1026 | 4134 |
| `ch1_v_pd_data` | 0x1027 | 4135 |
| `ch2_h_pd_data` | 0x1028 | 4136 |
| `ch2_v_pd_data` | 0x1029 | 4137 |
| `ch3_h_pd_data` | 0x102A | 4138 |
| `ch3_v_pd_data` | 0x102B | 4139 |
| `beam0_pd_data` | 0x102C | 4140 |
| `beam1_pd_data` | 0x102D | 4141 |
| `dctest_adc_data` | 0x1030 | 4144 |
| `dctest_adc_ctrl` | 0x1031 | 4145 |
| `beam_pd_ctrl` | 0x1032 | 4146 |
| `beam_pd_gc` | 0x1033 | 4147 |
| `ch0_pd_gc` | 0x1034 | 4148 |
| `ch1_pd_gc` | 0x1035 | 4149 |
| `ch2_pd_gc` | 0x1036 | 4150 |
| `ch3_pd_gc` | 0x1037 | 4151 |
| `bias_ctrl_0` | 0x1038 | 4152 |
| `bias_ctrl_1` | 0x1039 | 4153 |
| `bias_ctrl_2` | 0x103A | 4154 |
| `bias_ctrl_3` | 0x103B | 4155 |
| `bias_ctrl_4` | 0x103C | 4156 |
| `bias_ctrl_5` | 0x103D | 4157 |
| `bias_ctrl_6` | 0x103E | 4158 |
| `bias_ctrl_7` | 0x103F | 4159 |
| `bias_ctrl_8` | 0x1040 | 4160 |
| `bias_ctrl_9` | 0x1041 | 4161 |
| `bias_ctrl_10` | 0x1042 | 4162 |
| `bias_ctrl_11` | 0x1043 | 4163 |
| `bias_ctrl_12` | 0x1044 | 4164 |
| `bias_ctrl_13` | 0x1045 | 4165 |
| `bias_ctrl_14` | 0x1046 | 4166 |
| `bias_ctrl_15` | 0x1047 | 4167 |
| `ch0_comb_cbias` | 0x1048 | 4168 |
| `ch1_comb_cbias` | 0x1049 | 4169 |
| `ch2_comb_cbias` | 0x104A | 4170 |
| `ch3_comb_cbias` | 0x104B | 4171 |
| `bias_ctrl_20` | 0x104C | 4172 |
| `bias_ctrl_21` | 0x104D | 4173 |
| `bias_ctrl_22` | 0x104E | 4174 |
| `bias_ctrl_23` | 0x104F | 4175 |
| `bias_ctrl_26` | 0x1052 | 4178 |
| `bias_ctrl_28` | 0x1054 | 4180 |
| `bias_ctrl_29` | 0x1055 | 4181 |
| `bias_ctrl_32` | 0x1058 | 4184 |
| `bias_ctrl_33` | 0x1059 | 4185 |
| `ch0_h_attn_cal` | 0x105C | 4188 |
| `ch1_h_attn_cal` | 0x105D | 4189 |
| `ch2_h_attn_cal` | 0x105E | 4190 |
| `ch3_h_attn_cal` | 0x105F | 4191 |
| `ch0_v_attn_cal` | 0x1060 | 4192 |
| `ch1_v_attn_cal` | 0x1061 | 4193 |
| `ch2_v_attn_cal` | 0x1062 | 4194 |
| `ch3_v_attn_cal` | 0x1063 | 4195 |
| `ch0_v_b1_attn_cal` | 0x1064 | 4196 |
| `ch1_v_b1_attn_cal` | 0x1065 | 4197 |
| `ch2_v_b1_attn_cal` | 0x1066 | 4198 |
| `ch3_v_b1_attn_cal` | 0x1067 | 4199 |
| `ch0_captune` | 0x1068 | 4200 |
| `ch1_captune` | 0x1069 | 4201 |
| `ch2_captune` | 0x106A | 4202 |
| `ch3_captune` | 0x106B | 4203 |

---

## 부록 B — 전체 필드 (이름 / 주소 / 비트)

227개. `rd('field')` / `wrf('field', val)` 에 넣는 이름 사전. 비트는 `[msb:lsb]`,
멀티세그먼트 필드는 `주소[비트] + 주소[비트]` 로 표기.

| Field | Addr (hex) | Bits |
|---|---|---|
| `chip_id` | 0x1000 | [7:0] |
| `version_id` | 0x1000 | [15:8] |
| `uid_low` | 0x1001 | [15:0] |
| `uid_high` | 0x1002 | [15:0] |
| `soft_reset` | 0x1003 | [0] |
| `beam_pd_supply_pwrdn_sw` | 0x1004 | [13:12] |
| `b0_common_gain` | 0x1005 | [5:0] |
| `pulse_en_1` | 0x1005 | [6] |
| `b1_common_gain` | 0x1006 | [5:0] |
| `center_efuse_pwrdn_dis` | 0x1008 | [12] |
| `center_pd_override` | 0x1008 | [2] |
| `centerbias_en` | 0x1008 | [0] |
| `centermirror_en` | 0x1008 | [1] |
| `d2a_center_bias_en` | 0x1008 | 0x1008[1:0] + 0x1009[8] + 0x100A[8] + 0x100B[8] |
| `ds_sel` | 0x1008 | [11:8] |
| `global_power_down` | 0x1008 | [4] |
| `pulse_en_2` | 0x1008 | [7] |
| `spi_daisy_chain_disable` | 0x1008 | [3] |
| `beam0_pwrdn` | 0x1009 | [13:9] |
| `center_bias_beam0_en` | 0x1009 | [8] |
| `dist_b0_st1_en` | 0x1009 | [3:0] |
| `beam1_pwrdn` | 0x100A | [13:9] |
| `center_bias_beam1_en` | 0x100A | [8] |
| `dist_b1_st1_en` | 0x100A | [3:0] |
| `temp_adc_dctest_pwrdn_ctl` | 0x100B | [8] |
| `ch0_h_enables` | 0x100C | [2:0] |
| `ch0_v_enables` | 0x100C | [10:8] |
| `ch1_h_enables` | 0x100D | [2:0] |
| `ch1_v_enables` | 0x100D | [10:8] |
| `ch2_h_enables` | 0x100E | [2:0] |
| `ch2_v_enables` | 0x100E | [10:8] |
| `ch3_h_enables` | 0x100F | [2:0] |
| `ch3_v_enables` | 0x100F | [10:8] |
| `ch0_bias_en` | 0x1010 | [7] |
| `ch0_efuse_pwrdn_dis` | 0x1010 | [9] |
| `ch0_h_pwrdn` | 0x1010 | [5:3] |
| `ch0_pwrdn_override` | 0x1010 | [6] |
| `ch0_v_pwrdn` | 0x1010 | [2:0] |
| `pulse_en_ch0_2` | 0x1010 | [8] |
| `ch1_bias_en` | 0x1011 | [7] |
| `ch1_efuse_pwrdn_dis` | 0x1011 | [9] |
| `ch1_h_pwrdn` | 0x1011 | [5:3] |
| `ch1_pwrdn_override` | 0x1011 | [6] |
| `ch1_v_pwrdn` | 0x1011 | [2:0] |
| `pulse_en_ch1_2` | 0x1011 | [8] |
| `ch2_bias_en` | 0x1012 | [7] |
| `ch2_efuse_pwrdn_dis` | 0x1012 | [9] |
| `ch2_h_pwrdn` | 0x1012 | [5:3] |
| `ch2_pwrdn_override` | 0x1012 | [6] |
| `ch2_v_pwrdn` | 0x1012 | [2:0] |
| `pulse_en_ch2_2` | 0x1012 | [8] |
| `ch3_bias_en` | 0x1013 | [7] |
| `ch3_efuse_pwrdn_dis` | 0x1013 | [9] |
| `ch3_h_pwrdn` | 0x1013 | [5:3] |
| `ch3_pwrdn_override` | 0x1013 | [6] |
| `ch3_v_pwrdn` | 0x1013 | [2:0] |
| `pulse_en_ch3_2` | 0x1013 | [8] |
| `ch0_cal_freq_sel_beam0` | 0x1014 | [2:0] |
| `ch0_cal_freq_sel_beam1` | 0x1014 | [5:3] |
| `pulse_en_ch0_3` | 0x1014 | [9] |
| `ch1_cal_freq_sel_beam0` | 0x1015 | [2:0] |
| `ch1_cal_freq_sel_beam1` | 0x1015 | [5:3] |
| `pulse_en_ch1_3` | 0x1015 | [9] |
| `ch2_cal_freq_sel_beam0` | 0x1016 | [2:0] |
| `ch2_cal_freq_sel_beam1` | 0x1016 | [5:3] |
| `pulse_en_ch2_3` | 0x1016 | [9] |
| `ch3_cal_freq_sel_beam0` | 0x1017 | [2:0] |
| `ch3_cal_freq_sel_beam1` | 0x1017 | [5:3] |
| `pulse_en_ch3_3` | 0x1017 | [9] |
| `gain_control_h0` | 0x1018 | [3:0] |
| `gain_control_v0` | 0x1018 | [11:8] |
| `pulse_en_ch0_4` | 0x1018 | [12] |
| `gain_control_h1` | 0x1019 | [3:0] |
| `gain_control_v1` | 0x1019 | [11:8] |
| `pulse_en_ch1_4` | 0x1019 | [12] |
| `gain_control_h2` | 0x101A | [3:0] |
| `gain_control_v2` | 0x101A | [11:8] |
| `pulse_en_ch2_4` | 0x101A | [12] |
| `gain_control_h3` | 0x101B | [3:0] |
| `gain_control_v3` | 0x101B | [11:8] |
| `pulse_en_ch3_4` | 0x101B | [12] |
| `ch0_dctest_en` | 0x101C | [7:4] |
| `ch0_h_pd_en` | 0x101C | [2] |
| `ch0_h_pd_enbgr` | 0x101C | [3] |
| `ch0_v_pd_en` | 0x101C | [0] |
| `ch0_v_pd_enbgr` | 0x101C | [1] |
| `ch1_dctest_en` | 0x101D | [7:4] |
| `ch1_h_pd_en` | 0x101D | [2] |
| `ch1_h_pd_enbgr` | 0x101D | [3] |
| `ch1_v_pd_en` | 0x101D | [0] |
| `ch1_v_pd_enbgr` | 0x101D | [1] |
| `ch2_dctest_en` | 0x101E | [7:4] |
| `ch2_h_pd_en` | 0x101E | [2] |
| `ch2_h_pd_enbgr` | 0x101E | [3] |
| `ch2_v_pd_en` | 0x101E | [0] |
| `ch2_v_pd_enbgr` | 0x101E | [1] |
| `ch3_dctest_en` | 0x101F | [7:4] |
| `ch3_h_pd_en` | 0x101F | [2] |
| `ch3_h_pd_enbgr` | 0x101F | [3] |
| `ch3_v_pd_en` | 0x101F | [0] |
| `ch3_v_pd_enbgr` | 0x101F | [1] |
| `dctest_reset` | 0x1021 | [14] |
| `tcoc` | 0x1022 | [3:0] |
| `tcsc` | 0x1022 | [7:4] |
| `temp_adc_enbgr` | 0x1022 | [9] |
| `thermo_core_en` | 0x1022 | [8] |
| `temp_adc_data` | 0x1023 | [7:0] |
| `ch0_h_pd_data` | 0x1024 | [7:0] |
| `ch0_v_pd_data` | 0x1025 | [7:0] |
| `ch1_h_pd_data` | 0x1026 | [7:0] |
| `ch1_v_pd_data` | 0x1027 | [7:0] |
| `ch2_h_pd_data` | 0x1028 | [7:0] |
| `ch2_v_pd_data` | 0x1029 | [7:0] |
| `ch3_h_pd_data` | 0x102A | [7:0] |
| `ch3_v_pd_data` | 0x102B | [7:0] |
| `beam0_pd_data` | 0x102C | [7:0] |
| `beam1_pd_data` | 0x102D | [7:0] |
| `dctest_adc_data` | 0x1030 | [7:0] |
| `dctest_enbgr` | 0x1031 | [10] |
| `dctest_gc` | 0x1031 | [12:11] |
| `dctest_mode` | 0x1031 | [15:13] |
| `beam0_pd_en` | 0x1032 | [0] |
| `beam0_pd_enbgr` | 0x1032 | [1] |
| `beam1_pd_en` | 0x1032 | [2] |
| `beam1_pd_enbgr` | 0x1032 | [3] |
| `beam0_pd_gc` | 0x1033 | [1:0] |
| `beam1_pd_gc` | 0x1033 | [3:2] |
| `ch0_h_pd_gc` | 0x1034 | [1:0] |
| `ch0_v_pd_gc` | 0x1034 | [3:2] |
| `ch1_h_pd_gc` | 0x1035 | [1:0] |
| `ch1_v_pd_gc` | 0x1035 | [3:2] |
| `ch2_h_pd_gc` | 0x1036 | [1:0] |
| `ch2_v_pd_gc` | 0x1036 | [3:2] |
| `ch3_h_pd_gc` | 0x1037 | [1:0] |
| `ch3_v_pd_gc` | 0x1037 | [3:2] |
| `d2a_ch0_h_ptat_st1` | 0x1038 | [5:0] |
| `d2a_ch0_h_ptat_st2` | 0x1038 | [13:8] |
| `d2a_ch1_h_ptat_st1` | 0x1039 | [5:0] |
| `d2a_ch1_h_ptat_st2` | 0x1039 | [13:8] |
| `d2a_ch2_h_ptat_st1` | 0x103A | [5:0] |
| `d2a_ch2_h_ptat_st2` | 0x103A | [13:8] |
| `d2a_ch3_h_ptat_st1` | 0x103B | [5:0] |
| `d2a_ch3_h_ptat_st2` | 0x103B | [13:8] |
| `d2a_ch0_h_ctat` | 0x103C | [13:8] |
| `d2a_ch0_h_ptat_st3` | 0x103C | [5:0] |
| `d2a_ch1_h_ctat` | 0x103D | [13:8] |
| `d2a_ch1_h_ptat_st3` | 0x103D | [5:0] |
| `d2a_ch2_h_ctat` | 0x103E | [13:8] |
| `d2a_ch2_h_ptat_st3` | 0x103E | [5:0] |
| `d2a_ch3_h_ctat` | 0x103F | [13:8] |
| `d2a_ch3_h_ptat_st3` | 0x103F | [5:0] |
| `d2a_ch0_v_ptat_st1` | 0x1040 | [5:0] |
| `d2a_ch0_v_ptat_st2` | 0x1040 | [13:8] |
| `d2a_ch1_v_ptat_st1` | 0x1041 | [5:0] |
| `d2a_ch1_v_ptat_st2` | 0x1041 | [13:8] |
| `d2a_ch2_v_ptat_st1` | 0x1042 | [5:0] |
| `d2a_ch2_v_ptat_st2` | 0x1042 | [13:8] |
| `d2a_ch3_v_ptat_st1` | 0x1043 | [5:0] |
| `d2a_ch3_v_ptat_st2` | 0x1043 | [13:8] |
| `d2a_ch0_v_ctat` | 0x1044 | [13:8] |
| `d2a_ch0_v_ptat_st3` | 0x1044 | [5:0] |
| `d2a_ch1_v_ctat` | 0x1045 | [13:8] |
| `d2a_ch1_v_ptat_st3` | 0x1045 | [5:0] |
| `d2a_ch2_v_ctat` | 0x1046 | [13:8] |
| `d2a_ch2_v_ptat_st3` | 0x1046 | [5:0] |
| `d2a_ch3_v_ctat` | 0x1047 | [13:8] |
| `d2a_ch3_v_ptat_st3` | 0x1047 | [5:0] |
| `ch0_h_comb_cbias` | 0x1048 | [2:0] |
| `ch0_v_comb_cbias` | 0x1048 | [10:8] |
| `ch1_h_comb_cbias` | 0x1049 | [2:0] |
| `ch1_v_comb_cbias` | 0x1049 | [10:8] |
| `ch2_h_comb_cbias` | 0x104A | [2:0] |
| `ch2_v_comb_cbias` | 0x104A | [10:8] |
| `ch3_h_comb_cbias` | 0x104B | [2:0] |
| `ch3_v_comb_cbias` | 0x104B | [10:8] |
| `d2a_dist_b0_st1_ptat` | 0x104C | [5:0] |
| `d2a_dist_b0_st2_0_ptat` | 0x104C | [13:8] |
| `d2a_dist_b0_st1_cbias` | 0x104D | [8:6] |
| `d2a_dist_b0_st2_0_cbias` | 0x104D | [11:9] |
| `d2a_dist_b0_st2_1_cbias` | 0x104D | [14:12] |
| `d2a_dist_b0_st2_1_ptat` | 0x104D | [5:0] |
| `d2a_dist_b1_st1_ptat` | 0x104E | [5:0] |
| `d2a_dist_b1_st2_0_ptat` | 0x104E | [13:8] |
| `d2a_dist_b1_st1_cbias` | 0x104F | [8:6] |
| `d2a_dist_b1_st2_0_cbias` | 0x104F | [11:9] |
| `d2a_dist_b1_st2_1_cbias` | 0x104F | [14:12] |
| `d2a_dist_b1_st2_1_ptat` | 0x104F | [5:0] |
| `d2a_dist_ctat` | 0x1052 | [5:0] |
| `d2a_daisy_chain0_bias` | 0x1054 | [5:0] |
| `d2a_daisy_chain1_bias` | 0x1054 | [13:8] |
| `d2a_daisy_chain2_bias` | 0x1055 | [5:0] |
| `d2a_daisy_chain3_bias` | 0x1055 | [13:8] |
| `d2a_extra_bits_0` | 0x1058 | [7:0] |
| `d2a_extra_bits_1` | 0x1058 | [15:8] |
| `d2a_extra_bits_2` | 0x1059 | [7:0] |
| `ch0_h_b0_attn_cal` | 0x105C | [3:0] |
| `ch0_h_b1_attn_cal` | 0x105C | [11:8] |
| `ch1_h_b0_attn_cal` | 0x105D | [3:0] |
| `ch1_h_b1_attn_cal` | 0x105D | [11:8] |
| `ch2_h_b0_attn_cal` | 0x105E | [3:0] |
| `ch2_h_b1_attn_cal` | 0x105E | [11:8] |
| `ch3_h_b0_attn_cal` | 0x105F | [3:0] |
| `ch3_h_b1_attn_cal` | 0x105F | [11:8] |
| `ch0_v_b0_attn_cal` | 0x1060 | [11:8] |
| `ch1_v_b0_attn_cal` | 0x1061 | [11:8] |
| `ch2_v_b0_attn_cal` | 0x1062 | [11:8] |
| `ch3_v_b0_attn_cal` | 0x1063 | [11:8] |
| `ch0_v_b1_attn_cal` | 0x1064 | [3:0] |
| `ch1_v_b1_attn_cal` | 0x1065 | [3:0] |
| `ch2_v_b1_attn_cal` | 0x1066 | [3:0] |
| `ch3_v_b1_attn_cal` | 0x1067 | [3:0] |
| `ch0_h_comb_in_captune` | 0x1068 | [2:0] |
| `ch0_h_comb_out_captune` | 0x1068 | [4:3] |
| `ch0_v_comb_in_captune` | 0x1068 | [10:8] |
| `ch0_v_comb_out_captune` | 0x1068 | [12:11] |
| `ch1_h_comb_in_captune` | 0x1069 | [2:0] |
| `ch1_h_comb_out_captune` | 0x1069 | [4:3] |
| `ch1_v_comb_in_captune` | 0x1069 | [10:8] |
| `ch1_v_comb_out_captune` | 0x1069 | [12:11] |
| `ch2_h_comb_in_captune` | 0x106A | [2:0] |
| `ch2_h_comb_out_captune` | 0x106A | [4:3] |
| `ch2_v_comb_in_captune` | 0x106A | [10:8] |
| `ch2_v_comb_out_captune` | 0x106A | [12:11] |
| `ch3_h_comb_in_captune` | 0x106B | [2:0] |
| `ch3_h_comb_out_captune` | 0x106B | [4:3] |
| `ch3_v_comb_in_captune` | 0x106B | [10:8] |
| `ch3_v_comb_out_captune` | 0x106B | [12:11] |

---

## 부록 C — 핵심 bring-up 필드 의미

| Field | 의미 / 쓰는 값 |
|---|---|
| `centerbias_en`, `centermirror_en` | center 마스터 바이어스(bandgap+mirror). **둘 다 1** 이어야 RF 가 분배망/RTPS 통과. `path.enable()` 이 안 켜므로 수동 ON 필수. |
| `b0_common_gain`, `b1_common_gain` | 빔 공통 게인(6-bit, **감쇠 코드**: 0=최대 게인, 0x3f=최대 감쇠). |
| `gain_control_h{i}`, `gain_control_v{i}` | 채널별 FE 게인(4-bit). i=0..3. |
| `ch{i}_h_enables`, `ch{i}_v_enables` | 채널→빔 라우팅 enable(빔0/1 비트). `enable()`/`path` 가 설정. |
| `ch{i}_{p}_b{n}_attn_cal` | 채널-빔 디지털 감쇠(진폭 테이퍼/보정). p=h/v, n=0/1. |
| `ch{i}_cal_freq_sel_beam{n}` | 보정 대역 선택(칩이 LO 를 만들지 않음 — 외부 SG 가 RF 인가). |
| `d2a_ch{i}_{p}_ptat_st{1,2,3}` | 채널 증폭단(PA/Driver/Comb) 바이어스. `biasscan()` 이 0→63 흔들어 죽은 단 검출. |
| `version_id` | 정상 칩이면 0xDC. SPI 링크 점검용. |

> 빔은 `b0`/`b1` 두 포트(고로 common gain 도 b0/b1 둘). 채널은 H0..H3 / V0..V3 (각 4개).
> RTPS(Reflective-Type Phase Shifter) = beam table(`C.beam_table.zero_table()` + `C.spi.beam_up()`).
