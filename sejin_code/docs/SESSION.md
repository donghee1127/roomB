# CloudChaser 측정 매뉴얼 (Stampede TX / Blueway RX)

실제로 보드를 켜고 **측정하는 방법**을 담은 문서다. 두 가지 방법이 있다:

| 방법 | 용도 | 진입점 |
|------|------|--------|
| **IPython 세션** (주력) | 대화형으로 bring-up·디버깅·측정 | `cc.bat` → `start()` |
| **runner CLI** | 비대화 배치 실행(자동화) | `python -m cloudchaser.runner run ...` |

> 설정값(계측기 IP, 레일 전압/전류, 채널/게인, SG/SA)은 코드가 아니라
> **`config/bench.toml`** 에서 바꾼다. 경로 손실은 `Loss_data/` VNA CSV 파일에서 자동 로드된다.
>
> 명령어를 **복붙용 사전**으로 빠르게 찾으려면 [COMMANDS.md](COMMANDS.md) — 카테고리별 명령 +
> 전체 레지스터/필드 표. 이 문서는 측정 **절차/이유**, COMMANDS.md 는 **명령 목록** 담당.

---

## 1. 최초 1회 준비 (실험 PC)

```cmd
:: 가상환경 활성화 (본인 .sivers 경로)
C:\Users\Dosan\.sivers\Scripts\activate.bat
pip install ipython          :: 한 번만
```

`cc.bat` 의 `VENV`/`REPO` 경로를 본인 환경에 맞게 한 번 수정해 두면, 이후엔
**`cc.bat` 더블클릭**(또는 cmd 에서 `cc`)으로 세션이 열린다.

---

## 2. 세션 시작

`cc.bat` 으로 열거나, 수동으로 `activate → cd <repo> → ipython` 후:

```python
from cloudchaser.session import start

# 자동 감지 (기본) — TX/RX 어느 보드를 꽂아도 알아서 인식
start(channels=['h1'])                    # SPI 레일만 먼저 켜고 version_id 읽어 TX/RX 판별 -> 확인 후 진행

# 종류를 명시 (검증 모드) — 실제 칩과 다르면 경고+일시정지
start(channels=['h1'], chip='tx')         # TX 강제(검증). RX 보드면 경고
start(channels=['h1'], chip='rx')         # RX 강제(검증). bench_rx.toml 사용
```

- `start()` 가 끝나면 `chan`, `rf`, `peak`, `op1db`/`ip1db` 등 **모든 명령이 그대로 사용 가능**
  하다(IPython 네임스페이스에 자동 주입 — import 불필요).
- **전원 인가 순서는 `chip` 인자에 따라 두 갈래다.**

  **`chip='tx'` / `chip='rx'` (보드 명시) — Sivers 확정 타이밍 다이어그램 그대로:**

  ```
  ① CORE_1V0 1.0V                                    (VDD_DIG)
  ── 500 ms ──
  ② DIST_1V8 / IO_ANA_1V8 / FE2_1V8 / FE3_1V8 1.8V   (함께 lockstep, 여기서 SPI active)
     -> spi.reset() + version_id 확인                 (다이어그램의 'SPI active' 지점)
  ── 500 ms ──
  ③ FE1_4V0 4.0V                                     (PA -- 칩 확인 후에만 인가)
  ```

  `version_id` 가 안 맞으면 **PA(4V)를 안 켜고 중단**한다. 1.8V 군은 이미 인가된 상태이므로,
  벤치에 실제로 그 보드가 꽂혀 있는지 확인하고 쓸 것(시작 시 경고가 출력된다).
  이 경로는 `bench.toml` 에 `power_up_stages` 가 선언된 config(TX)에서만 쓰인다.

  **`chip='auto'` (기본값) — 감지 우선, 시퀀스는 한 번 끊긴다:**
  FE 레일 전압이 TX(1.8/1.8/4.0)와 RX(1.0/1.5/1.0)에서 다르므로 보드 확정 전에 올릴 수 없다.
  그래서 스테이지 ②를 둘로 쪼갠다 — TX/RX 공통 레일(+ `IO_ANA_1V8` 는 `detect_v`=1.3V)만 먼저
  올려 `version_id`(TX=0xDC / RX=0xD4)를 읽고, 확인받은 뒤 나머지 ②와 ③을 인가한다.
  다이어그램은 단계 사이 **최소** 500 ms 만 규정하므로 규격 위반은 아니지만, SPI 감지 시간만큼
  ②가 벌어진다. **깔끔한 시퀀스를 원하면 `chip='tx'` 를 명시할 것.**
- `version_id` 가 0xDC/0xD4 둘 다 아니면(SPI 미동작 등) → PA 안 켜고 중단.
- 전원 없이 설정만: `start(channels=['h1'], power=False)` (감지 생략, 외부 전원 가정)
- 하드웨어 없이 점검: `start(chip='tx', fake=True, power=False)` (fake 는 감지 생략, chip 지정값 사용)

---

## 3. 명령어 찾기

```python
help()                       # 카테고리별 전체 명령
help('rf')                   # 특정 명령 시그니처 + 상세
params('op1db')              # 한 테스트의 파라미터/기본값
tests()                      # 사용 가능한 측정 항목 목록
status()                     # 지금 채널/게인/SG 상태
```

---

## 4. 수동 신호 확인 (측정 전 점검)

### TX (Stampede)
```python
start(channels=['h1'])                   # H1 로 bring-up (TX 기본)
rf(True, freq=28e9, level=-10)           # SG 28GHz, -10dBm, RF ON
saconf(center=28e9, ref=20); peak()      # SA 보고 피크[dBm] 읽기
vi()                                    # 전원 V/I (PA 전류가 올라오나?)
chan('h3')                              # 다른 채널로 전환
biasscan('h3')                          # 단별 bias 반응(불량 단 탐지)
phase('h3', 0x40); rtps()               # 채널별 RTPS 위상(7-bit raw 코드) 쓰기/조회
```

> **phase() 주의**: 코드→도(°) 변환식 미검증(문서 부재), quad 단위(h/v 같은 숫자 채널이
> 워드 공유), `chan()` 이 beam table 을 클리어하므로 채널 전환 시 위상 0 리셋. 상세는
> COMMANDS.md §3.

### DIST 스플리터 모드 전환 — `split()` (TX 전용)

`split_mode` 는 `bench.toml` 의 시작 기본값이고, 세션 중에는 `split()` 로 바꾼다.

```python
split()             # 현재 모드 조회 (칩·설정 안 건드림)
split(False)        # thru  — 활성 채널 분기만
split(True)         # split — beam0 분배망 CH0..CH3 전부 (다채널 결합)
```

| 모드 | `0x1009` (`center_dist_b0`) | `0x1068` (`ch0_captune`) |
|---|---|---|
| split | `783` = `0x30F` → `dist_b0_st1_en=0xF` (CH0~CH3 전부) | `0x8888` |
| thru | 활성 채널 비트만 (예: h1 → `770`=`0x302`, `dist_b0_st1_en=0x2`) | `0x0000` |

- **모드를 바꾸면 bring-up 이 다시 돈다.** `0x1009=783` 이 앞서 쓴 `beam_enables` 를
  덮어써서 그 워드만 되돌릴 안전한 방법이 없기 때문이다. 따라서 `start()` 이후 손으로
  준 값(`gain()`/`chgain()`/`atten()`/`phase()`)은 `bench.toml` 값으로 리셋된다 —
  **토글 후 다시 적용할 것.** 같은 모드로 다시 부르면 bring-up 을 돌리지 않는다.
- **`0x1009` 는 b0 전용 주소다**(`center_dist_b{n}` = `0x1009+n`). beam 이 b1/b2 여도
  b0 워드를 쓰므로, 실칩 확인 전까지 split 은 b0 에서만 쓴다.
- **채널 라우팅 후에도 유지된다.** `route_channels()`(= `chan()`/`enable()`/`disable()`,
  그리고 `tx_suite()` 가 시작할 때 부르는 `chan()`)은 `0x1009` 를 '그 채널 분기만' 으로
  다시 쓴다. 그래서 라우팅 직후 `apply_split_mode()` 로 split 을 되살린다. 이걸 안 하면
  `bench.toml` 이 `split_mode = true` 인데도 `chan()` 한 번에 조용히 thru 로 떨어졌다 —
  **실측에서 게인이 8 dB 차이났다**(1:4 분배 = 10·log10(4) + 분배망 손실).
  `chan()` 안내 줄 끝에 현재 모드(`DIST split` / `DIST thru`)가 찍힌다.
- RX(Blueway) bring-up 은 `split_mode` 를 읽지 않는다 — `split()` 은 그렇다고 알리고 끝난다.

필드 해석 근거는 벤더 레지스터 맵(`docs/sivers_unified_api_v0.1.0/register_maps/`)이고,
비트별 설명은 `src/cloudchaser/board/bringup.py` 의 `SPLIT_REGS_TX` 주석에 있다.

### Sivers 레퍼런스 전류 매칭 — `bias_match` (TX)

Sivers 는 bias 코드가 IC 마다 다르고 **전류 소비 매트릭스가 공통**이라고 했다
(2026-08-25 메일). 그래서 게인/EVM 을 비교하기 전에 6개 bias 코드
(FE `ptat_st1/2/3` + DIST `st1/st2_0/st2_1`)를 그들의 레퍼런스 전류에 맞춘다.
타깃은 `config/bench.toml` 의 `[bias_match]` 에 있다.

#### 실측 절차 (순서대로)

**0. 준비** — 하드웨어 불필요, 5분

```powershell
git pull
pip install -e .                                  # -m 실행이 안 되면 이것부터
python -m cloudchaser.bias_match jacobian --fake  # 설치 확인
```

`--fake` 는 전류가 안 움직여서 **전 knob 이 NO RESPONSE 로 나오는 게 정상**이다.
`--ambient-c 25` 는 선택 — 붙이면 CSV 에 온도만 기록된다.

**1. `jacobian`** — 19점, RF/SG/SA 불필요, 약 10분

```powershell
python -m cloudchaser.bias_match jacobian
```

| 확인 | 기대 | 아니면 |
|---|---|---|
| 첫 줄 `splitter mode:` | **split** | thru 면 `bench.toml` 이 바뀐 것 -- 중단 |
| 6x6 표가 블록대각인가 | 각 knob 이 자기 레일에서 최대 반응 | 커플링이 크면 solve 의 전제가 깨짐 |
| `** NO RESPONSE **` | 6개 다 반응 | `dist_st2_1` 이 죽었으면 13 vs 28 논쟁의 답 |
| baseline vs 레퍼런스 reset 행 | CORE 3.2 / DIG 0.9 / Dist 0.0 / FE1 4.34 / FE2 0.07 / FE3 0.07 | 크게 다르면 레일 배선·전압부터 |
| PTAT 가 DIST_1V8 을 움직이나 | 조금 움직임 | Sivers 답변용 근거 데이터 |

**2. `solve`** — 약 15분

```powershell
python -m cloudchaser.bias_match solve
```

FE1 27.8 / FE2 18.35 / FE3 10.37 / Dist 64.4 mA 를 +-0.5 mA 로 맞춘다. 끝에 붙여넣을
TOML 스니펫이 찍히지만 **3단계를 보고 반영을 판단한다.** 수렴 실패해도 예외 없이
잔차를 보고하므로 결과는 나온다.

**3. `verify`** — 56점(VDD 7 x 주파수 8), 약 30~40분. **여기가 성공 판정이다.**

```powershell
python -m cloudchaser.bias_match verify --serial <DUT S/N>
```

같은 split 모드에서 27.5 GHz / VDD 4V 게인을 비교한다:

| | 게인 |
|---|---|
| Sivers 레퍼런스 | **23.1 dB** |
| 우리 (기존 bias) | 약 16 dB |
| 우리 (전류 매칭 후) | 이 값이 23 쪽으로 움직였는가 |

움직였으면 "전류를 맞추면 게인도 따라온다" = Sivers 주장 검증. **안 움직여도 결과다** --
전류가 같은데 게인이 다르면 원인이 bias 가 아닌 다른 곳(다이 편차·경로손실·측정 셋업)을
가리키므로, 그대로 되물을 근거가 된다.

> FE1(PA 드레인)을 4.0 -> 2.2 V 까지 내렸다 원복한다. 레일 변경 때마다 RF 를 끄고
> 예외가 나도 `finally` 에서 원복하지만, 끝나고 **PSU 화면에서 FE1 이 4.0 V 인지
> 눈으로 확인한다.** `Loss_data/` 의 VNA CSV 3종이 최신인지도 확인 -- 경로손실이
> 틀리면 게인이 통째로 어긋나 위 판정이 무의미해진다.

**4. `dist-gain`** (선택) — solve 의 비율 고정 해가 최적인지 교차검증

```powershell
python -m cloudchaser.bias_match dist-gain
```

#### 중단해야 할 신호

| 메시지 | 뜻 | 할 일 |
|---|---|---|
| `RESTORE FAILED` | 레일/코드 원복 실패 | 즉시 중단, PSU 상태 직접 확인 |
| `within 5% of its ... mA limit` | PSU 가 CC 로 떨어짐 | 즉시 중단, 이후 측정값 전부 무의미 |
| `trip polling off by config` | `bench.toml` 의 `trip_poll = false` | 정상. 이 E36313A 는 `STAT:QUES:COND?` 에 응답하지 않아 미리 꺼둔 것 -- 전류제한(CC)·OVP 는 그대로 동작한다 |
| `trip polling disabled` | 램프 중 조회 무응답으로 런타임에 꺼짐 | `trip_poll` 을 true 로 둔 장비에서만 나온다. 진행은 되나 전류제한만 남음 |
| `rail read timed out -- retry` | PSU MEAS 간헐 무응답 | 자동 재시도됨. 반복되면 `scripts/psu_probe.py` |

- 레일 대응 (2026-09-03 재배선으로 Sivers 컬럼과 **1:1** 이 됐다):

  | Sivers | 우리 레일 | 칩 핀 |
  |---|---|---|
  | `IDC_1p0` | `CORE_1V0` | `VDD_DIG` 6핀 |
  | `IDC_1p8` | `IO_ANA_1V8` | `VDD_1p8V_IO_SOUTH` + `IO_NORTH` + `VDD_1p8V_ANA` 5핀 |
  | `IDC_Dist` | `DIST_1V8` | `VDD_1p8V_DIST` 2핀 (BGA K9, K27) |
  | `IDC_FE1/2/3` | `FE1_4V0`/`FE2_1V8`/`FE3_1V8` | `VDD_FE1/2/3_CH0~3` |

  재배선 전에는 `IO` 채널이 IO 2핀만, `DIST` 채널이 ANA+DIST 를 함께 물고 있었다.
  ANA 를 IO 채널로 옮겨 저쪽 묶음과 맞췄다.

- **DIST bias 전류는 `DIST_1V8` 로 흐른다.** DIST 코드가 그 레일을 0.26~0.41 mA/code 로
  움직이는 반면 IO 쪽은 0.002 = 노이즈였다(09-02 자코비안). 그래서 `DIST_RAIL = "DIST_1V8"`.
- **`IO_ANA_1V8` 에는 bias 손잡이가 없다** -- bandgap/LDO/ADC/temp sensor/power detector
  (ANA) + SPI I/O 버퍼라 `report_only` 다. 재배선 전 ANA 몫은 DIST 채널에서 DIST 코드와
  무관한 약 13.2 mA 바닥으로 관측됐고, 저쪽 `IDC_1p8` 13.9 와 거의 같다.
- **`VDD_1p8V_IO` 는 1.8V 다.** 예전 1.3V 는 데이터시트 동작 최소 1.7V 미달이었다.
  1.8V 에서 칩이 오동작했던 원인은 GlobalFoundries 이슈가 아니라 EVB 의 CHIP ID 핀
  풀다운(10k) 문제이고, CID 를 GND 로 직결하는 보드 리워크로 해결된다(CHIP-ID = 0).
  1.3V 미만으로는 내리지 말 것 -- SPI 리드백이 1비트 밀린다
  (vault `wiki/errors/VDD_IO-강하-SPI-리드백-1비트-슬립`).
- **DIST 전류가 레퍼런스의 40% 다.** 재배선 전 실측(4V, 27.5 GHz, 코드 63/16/6):
  `IO` 0.6 + `DIST 채널` 38.6(= ANA 13.2 + DIST 25.4). 저쪽은 13.9 + 64.4.
  DIST 코드를 게인 기준으로 골랐기 때문인데(그때는 전류 타깃이 없었다), 이제
  `bench.toml [bias_match] targets_ma` 에 `DIST_1V8 = 64.4` 가 있으므로
  `solve` 가 이 값을 쫓는다. 64.4 를 내려면 DIST 코드가 최대 근처까지 올라갈 수
  있고 그때 게인이 어떻게 되는지는 **미확인**이다.
  ⚠️ 예전에 이 문서와 `bench.toml` 에 있던 "`DIG_1V8` 실측 77.6" 은 실측이 아니라
  pytest 합성 픽스처 값(13.2+64.4)이었다 -- 그건 실측이 아니라 **타깃**이다.
- `CORE_1V0` 는 reset 전류 = 동작 전류라 조절 손잡이가 없다 -- health check 전용.
- `--ambient-c` 는 선택이다. Sivers 가 요구한 적 없고 레퍼런스 CSV 에도 온도 컬럼이
  없다. 다만 PTAT 는 이름대로 절대온도에 비례하므로, 나중에 편차 원인을 따질 때
  쓰려고 기록만 남긴다. 온도계가 없으면 그냥 빼고 돌려도 된다.
- **스플리터 모드는 split 이 기본**이다(`bench.toml:split_mode`). Sivers 가 공유한
  결과는 전부 split 이라 그게 비교 기준이다. `--no-split` 은 일부러 thru 로 잴 때만
  쓴다 -- 두 모드는 게인이 약 8 dB 다르므로(1:4 분배, `d7b76c5`) 모드가 어긋나면
  저쪽 파일과의 비교 자체가 무의미해진다. 실제 적용된 모드는 CSV 메타에 남는다.
- 열린 항목(2026-09-03 갱신): 저쪽 Dist 레일은 **1.8V** 로 확정됐다(타이밍 다이어그램
  `VDD_1p8V_DIST`). **우리 1.8V 도메인 전류가 레퍼런스의 절반이다** -- 09-02 최종 코드
  실측(4V, 27.5 GHz)에서 `IO_ANA_1V8` 0.6 + `DIST_1V8` 38.6 = **39.2 mA** 인데 저쪽은
  `IDC_1p8` 13.9 + `IDC_Dist` 64.4 = **78.3 mA**. `CORE_1V0`/`FE1`/`FE2`/`FE3` 는 맞는다.
  ⚠️ 예전에 이 문서와 `bench.toml` 에 있던 "`DIST_1V8` 실측 77.6" 은 **실측이 아니라
  pytest 합성 픽스처 값**(13.2+64.4)이었다. 인용하지 말 것.
  `sivers_report` 의 `IDC_Dist -> IO_ANA_1V8` 매핑도 재검토 대상 -- 리워크 후 재측정하면서
  같이 확정할 것.

#### 경로 손실 파일이 바뀌었을 때

`Loss_data/` 는 **종류별로 날짜가 가장 최신인 파일이 자동 선택**된다(`loss.latest_files`).
셋업이 바뀌어 손실이 달라지면 **기존 파일을 수정하지 말고 새 날짜 파일을 넣는다** —
그래야 "언제부터 이 손실이었나"가 파일 목록만으로 남는다.

케이블을 다시 재지 못해 기존 실측에서 파생한 파일이라면, 헤더에 그 사실을 남긴다:

```
MS4644B
!==== DERIVED FILE -- NOT A VNA MEASUREMENT ====
!Source sweep : SA_Cable_Loss_260821.csv (measured 2026-08-20, ...)
!Change       : S12 and S21 magnitudes shifted by -1.0 dB across the whole band
!Reason       : a connector on the EVB -> SA path was swapped on 2026-09-02 ...
!TODO         : replace this with a real VNA sweep of the current cable, then delete it.
```

`PNT,...` 헤더 앞줄은 전부 파서가 건너뛰므로 주석은 얼마든지 넣어도 된다.
S-파라미터는 음수 dB라 **손실을 1 dB 늘리려면 S12/S21 에서 1 을 뺀다.** S11/S22 는 건드리지 않는다.

**현재 적용 중**: `SA_Cable_Loss_260902.csv` = `260821` 전 구간 +1 dB
(2026-09-02 출력 경로 커넥터 교체). 28 GHz 기준 `out_loss` 6.32 -> 7.32 dB.
그 결과 **Pout·게인·OP1dB·Psat 이 전부 1 dB 올라가고 IP1dB 는 불변**이다
(입력 경로가 안 변해 압축이 시작되는 Pin 이 그대로다).
⚠️ 케이블을 실제로 다시 재면 이 파생 파일은 **지울 것**.

#### 한 채널을 한 번에 끝내기 — `find_bias()` (TX)

위 4단계를 세션 안에서 한 번에 도는 함수다. **전원 사이클도 bring-up 도 하지
않는다** — 채널을 바꾸려면 케이블을 손으로 옮겨야 하므로, 케이블을 옮기고
채널을 라우팅한 다음 부르면 된다.

```python
start(channels=['h1'])
find_bias('h1')                  # 25~35분. 끝나면 bench.toml 에 기입된다
find_bias('h1', write=False)     # 보고만 하고 bench.toml 은 안 건드림
find_bias('h1', grid_step=8)     # DIST 그리드를 촘촘히 (느려진다)
```

| 단계 | 하는 일 | 판정 |
|---|---|---|
| A | PTAT 3열을 레퍼런스 전류로 (27.5 GHz, Pin −28 dBm) | `[bias_match] targets_ma` |
| B/C | DIST 그리드 한 번 순회 (조합마다 레일 1회 + 게인 1점) | `DIST_1V8` 전류 창 → 19..25 dB (데이터시트 split 행) |
| D | 남은 후보 파워 스윕 | OP1dB 최대 |
| A′ | 확정 DIST 위에서 PTAT 재매칭 + 확인 측정 | `targets_ma` (다시) |

- D 의 선택 규칙은 **OP1dB 최대**, 단 `op1db_tol_db`(기본 0.3 dB) 안에서 동률이면
  **DIST 전류가 큰 쪽**을 고른다. h0 에서 `dist_st2_1 = 63` 을 고른 근거와 같다 —
  성능은 그대로 두고 레퍼런스 `IDC_Dist` 에 더 붙는 축이기 때문이다.
- B 의 전류 창은 **선택 장치가 아니라 폭주 방지 장치**다. 레퍼런스 64.4 mA 는 게인
  max 25 dB 를 깨지 않고는 도달할 수 없음이 h0 에서 확인됐다(스펙 인 상한 48.7 mA).
- 그리드는 끝점 63 을 **항상 포함**한다. `range(0,64,16)` 은 48 에서 끝나 h0 의
  정답 `[63, 16, 63]` 을 후보에서 빠뜨린다.
- A′ 가 필요한 이유: **FE1 은 자기 PTAT 뿐 아니라 DIST 코드에도 끌려간다**(h0 실측
  27.1~30.3 mA). A 에서 맞춘 전류가 D 이후엔 어긋나 있다. 재매칭이 성능을 0.5 dB 넘게
  흔들면 경고가 나온다 — DIST 순위가 달라질 수 있다는 뜻이라 사람이 판단할 자리다.
  `rematch_ptat=False` 로 끄면 2~3분을 아낀다.
- **OP1dB 스펙 최소(19.5 dBm)는 강제하지 않는다.** 최대값을 고를 뿐이라 전 후보가
  미달이면 미달인 값이 기입된다 — 의도한 동작이고, 스펙 판정은 결과/CSV 를 보고
  사람이 한다.
- 끝나면 칩은 확정 코드 상태로 남으므로 바로 `op1db()` 등으로 넘어가면 된다.
  중간에 실패하면 실행 전 코드로 되돌린다.
- 후보 표는 `out/bias_find_<ch>_*.csv` 로 남는다.

옵션 전체는 `help('find_bias')` 또는 `cloudchaser/bias_find.py` 의 `FindBiasOpts`.
**왜 이 4단계인지, 각 판정 기준이 어디서 나왔는지**는 [BIAS_SEARCH.md](BIAS_SEARCH.md) 에 정리돼 있다.

#### 확정된 bias 코드는 bring-up 이 자동으로 싣는다

`bias_match` 로 찾은 채널별 코드는 `config/bench.toml` 의 `[board.bias.<ch>]` 에 적어두면
`start()` / `setup_tx` / `tx_suite()` 가 자동으로 적용한다. 따로 인자를 줄 필요가 없다.

```toml
[board.bias.h0]
ptat = [17, 55, 61]   # ptat_st1(PA), ptat_st2(DRV), ptat_st3(Comb)
dist = [63, 16, 63]   # dist_st1, dist_st2_0, dist_st2_1
```

bring-up 로그에 이렇게 찍히면 적용된 것:

```
[bias   ] measured ptat for h0: [17, 55, 61]
[bias   ] measured dist for h0: [63, 16, 63]
```

- 기입 시점은 **DIRECT_REGS / split 다음**이다. step 18 의 `DIRECT_REGS_TX` 가
  `0x104C` 에 v4 Casper DIST(50/13)를 하드코딩으로 넣기 때문에, 그보다 먼저 쓰면
  지워진다. 그 하드코딩은 evb_full 레지스터 동일성 근거라 건드리지 않는다.
- 여기 없는 채널은 v4 Casper 값이 그대로 남는다.
- **DIST 는 빔당 1행이라 채널마다 다른 값을 동시에 못 가진다.** 여러 채널이 `dist` 를
  정의하면 bring-up 은 첫 활성 채널 것을 쓰고 나머지를 로그로 알린다. `chan()` 이
  채널 전환 시 그 채널의 코드로 다시 기입한다(split 을 다시 적용하는 것과 같은 이유).

#### `bias_test()` 와 `bias_match` 중 뭘 쓰나

bias 를 흔드는 도구가 둘인데 **목적이 다르다.**

| | `bias_test()` | `bias_match` |
|---|---|---|
| 목적 | 이 다이에서 **게인 최대점** 찾기 | Sivers 레퍼런스와 **전류 맞추기** |
| 손잡이 | FE PTAT 3개 (PA/DRV/Comb) | FE 3개 + DIST 3개 = 6개 |
| 판정 기준 | SA 피크 게인 | 6개 레일 전류 (mA) |
| 방식 | 2단 격자 스윕 (~470점) | 자코비안 + 레일별 1D 이진탐색 |
| 진입점 | 세션 `_ns` (`start()` 후 바로) | CLI (`python -m`) |
| 언제 | "우리 보드에서 제일 좋은 값" | "저쪽과 같은 조건인지" |

`find_bias()` 는 셋째 도구가 아니라 **`bias_match` 의 절차를 세션에서 한 번에 도는
포장**이다. 전류 매칭(A)과 성능 판정(C/D)을 한 호출에 묶고 결과를 `bench.toml` 까지
적는다 — 채널 하나를 확정할 때는 이걸 쓰고, 중간 과정을 직접 보고 싶을 때만 CLI 를
단계별로 쓴다.

Sivers 와 데이터를 주고받을 때는 `bias_match`, 우리 보드 성능만 뽑을 때는
`bias_test()`. 전자로 전류를 맞춘 뒤 후자로 게인을 더 짜낼 수 있는지 보는 순서가
자연스럽다. 배경은 vault `wiki/dev-tasks/PTAT-bias-최적조합-탐색` 참조.

### RX (Blueway)
```python
start(channels=['h1'], chip='rx')        # RX bring-up
rf(True, freq=19.5e9, level=-30)         # SG Ka-band, 낮은 레벨 시작 (RX 민감)
saconf(center=19.5e9, ref=0); peak()     # SA 빔 포트에서 피크 읽기
vi()                                    # 전원 V/I 확인
```

> **RX 배선**: SG → 채널 포트(안테나 입력), SA → 빔 포트(B0/B1 출력). TX 와 반대.  
> **주파수**: Blueway 대역 17.7–21.2 GHz (Ka-band Satcom).

---

## 5. 경로 손실 보정 (케이블 + board trace)

측정 전력은 IC 기준으로 보상해야 한다:

- `Pin (IC 입력)  = SG레벨   - in_loss`
- `Pout(IC 출력) = SA측정값 + out_loss`

손실 모델은 **`Loss_data/` 디렉토리의 VNA CSV 3종**에서 읽는다:

| CSV 종류 | 내용 |
|----------|------|
| `SG_Cable_YYYYMMDD.csv` | SG → EVB 케이블 손실 |
| `SA_Cable_YYYYMMDD.csv` | EVB → SA 케이블 손실 |
| `Board_Trace_YYYYMMDD.csv` | EVB board trace 손실 |

- 주파수 범위·간격은 **측정마다 다르다**(260626=16–32 GHz/50 MHz, 260820=27–32 GHz/100 MHz). 각 종류별로 **날짜가 가장 최신인 파일**을 자동 선택한다.
- 측정 주파수가 선택된 표의 범위를 벗어나면 끝점으로 clamp 되고 **경고가 출력된다**. 예: 27–32 GHz 케이블 표만 있는 상태에서 RX 를 19.5 GHz 로 재면 27 GHz 값이 쓰이므로, 그 대역을 재려면 해당 범위를 덮는 CSV 가 필요하다.
- 각 포인트 손실: `loss = max(|S12|, |S21|)` (보수적, 방향 비대칭 포함).
- `in_loss = sg_cable + trace/2`, `out_loss = sa_cable + trace/2` (TX/RX · 빔/채널 구분 없음).
- 표에 없는 주파수는 **선형 보간**, 범위 밖 주파수는 **끝점으로 clamp**.

```python
loss()              # 현재 loss 테이블 보기 (선택된 CSV + 대표 주파수별 in/out)
loss(28)            # 28 GHz 손실 조회 (GHz 단위)
peakc(28)           # 손실 보상된 IC 출력 (SA 오프셋 적용 후 피크)
```

- 손실은 **SG/SA 오프셋으로 계측기에 자동 적용**된다: SG level offset = −(in_loss)
  (SG 가 출력을 in_loss 만큼 부스트 → 칩이 명령값을 실제로 받음), SA ref level
  offset = +out_loss (SA 읽기 = 칩 출력). 따라서 SG/Pin = 칩 입력, SA/Pout = 칩
  출력이 바로 나온다(per-point 보정 계산 없음).

**수동 override (간이 측정 시):**
```python
set_loss(3.0, 4.5)  # in_loss=3.0dB, out_loss=4.5dB 고정 (CSV 무시)
set_loss()          # override 해제 → CSV 자동 모드로 복귀
```

> `Loss_data/*.csv` 는 `.gitignore` 의 `!Loss_data/*.csv` 로 **추적됩니다**. VNA 측정 후 해당 디렉토리에
> 파일을 넣으면 다음 세션부터 자동 반영됩니다(재시작 불필요).

---

## 6. 측정 항목 (Test Items)

각 측정은 세션 함수 한 번으로 실행되고 결과가 **`out/<test_id>_<timestamp>.csv`**
(메타 주석 + 데이터 표)로 저장된다. 경로 손실은 자동 적용된다.

### 6-1. `op1db` — 출력 1-dB 압축점
고정 게인에서 CW 입력 전력을 sweep 하며 게인이 1dB 꺾이는 출력 전력(OP1dB)을 찾는다.

```python
op1db(freq_hz=28e9, gain_code=0)          # gain_code 0 = 최대 게인(common)
op1db(freq_hz=28e9, pin_stop_dbm=18)      # 압축점이 안 잡히면 SG sweep 끝을 키운다
op1db(log_idd=True)                       # 매 포인트 합산 전류(Idd_mA)도 기록
```
결과: OP1dB[dBm], 소신호 게인, (압축점 Pin/SG). `params('op1db')` 로 전체 파라미터.

### 6-2. `gain_index_accuracy` — 게인 인덱스 정확도
SG 고정, 공통(common) × per-path(RTPS) 게인 인덱스를 2D sweep 해 인덱스별 게인을 본다.

```python
gain_index_accuracy(sg_level_dbm=0)                    # 기본: common × beamtable
gain_index_accuracy(channel_codes=[0])                 # common 만 1D sweep
gain_index_accuracy(channel_target='beamtable', channel_quad=1)  # RTPS atten(h1=quad1)
```
게인 조작은 필드 이름이 아니라 **타깃(target)** 으로 지정한다(`gain_target`/
`common_target`/`channel_target`, 값은 `""`(블랭크=기본)/`common`/`fe`/`beamtable`).
빔·채널은 기본적으로 `bench.toml [board]`(`beam`/`active_channels`)를 따르고,
필요할 때만 `beam=`/`channel=` 로 덮어쓴다.

| target | 대상 레지스터 | 코드 의미 | 상태 |
|---|---|---|---|
| `common` | `0x1005 + beam index` | 빔 공통 감쇠 6-bit. 0=최대 게인 | 실동작(기본) |
| `beamtable` | beam table 워드(quad 단위) | RTPS 감쇠 7-bit. 0=최대 게인 | 실동작(per-path 기본) |
| `fe` | `0x1018 + channel index` | 채널 FE 게인 4-bit | **DEAD**(이 칩에서 무반응, 구 `gain_control_*`) |

- `common`: 0=최대 게인, 클수록 감쇠(16dB / 0.25dB step).
- per-path 는 **beam table attenuator(RTPS)** = `channel_target='beamtable'` 가 실동작
  (0=최대). `channel_target='fe'`(구 `gain_control_*`)는 이 칩에서 무반응(DEAD).
- beamtable 2D 는 매 포인트 SPI+beam_up 이라 느리다(4096점 ~15–20분 → step 키워 축소).
- 구 파라미터(`gain_field=`/`common_field=`/`channel_kind=`/`channel_field=`)도 여전히
  동작하지만 `[deprecated]` 경고 후 자동으로 신규 타깃에 매핑된다.

### 6-3. `channel_gain_alignment` — 채널 게인 정렬 (인터랙티브)
게인을 최대로 고정하고 **채널별 출력 전력**을 측정해 채널 간 편차(spread)를 본다.
SA 케이블을 채널 포트로 옮겨가며 한 채널씩 측정한다.

```python
channel_gain_alignment(channel_mode='all')      # 후보 채널 모두 ON, 케이블만 이동
channel_gain_alignment(channel_mode='single')   # 측정하는 채널만 ON(인접 간섭 배제)
```

**인터랙티브 진행:**
```
channel to measure (or 'n' to stop):  h0      ← 측정할 채널 입력
  move cable to H0 port, then 'y' to measure:  y   ← 케이블 옮긴 뒤 y
  H0: SA_raw=-10.00  out_loss=7.20  Pout=-2.80 dBm  Idd=300 mA
channel to measure (or 'n' to stop):  v3      ← 다음 채널
  ...
channel to measure (or 'n' to stop):  n       ← 종료 → CSV 저장
```

- `channel_mode='all'`: 시작 시 후보 채널(`channels`, 기본 H0–H3·V0–V3)을 모두 ON
  해두고 케이블만 옮긴다.
- `channel_mode='single'`: 채널을 입력하면 그 채널만 ON 하고 나머지는 OFF.
- 출력 손실(out_loss)은 **주파수별로** Loss_data CSV 에서 자동 계산된다(채널 구분 없음).
- **PSU 전 레일 V/I + 합산 전류(Idd_mA) + 총 소비전력(Pdc_mW)** 가 매 측정마다 CSV 에
  기록된다. `Pdc_mW = sum(레일별 V x I)` 로 코드가 계산해 **마지막 열**에 넣는다
  (콘솔 로그에는 안 나오고 CSV 전용). 엑셀에서 손으로 곱해 더하던 값이다.
- 비대화(자동/회귀): `channel_gain_alignment(channels_script='h0,h1,v0')` 로 입력
  프롬프트 없이 그 순서대로 측정.

결과: 채널 간 spread[dB] + 채널별 Pout. `params('channel_gain_alignment')` 참고.

### 6-4. `evm` — 변조 품질 (5G NR)
변조신호(기본 5G NR 100MHz)를 인가하고 SG 파워를 sweep 하며 EVM[dB]/출력을 측정.

```python
evm(freq_hz=28e9)                         # modulation='setup'(코드가 NR 설정)
evm(modulation='manual')                  # 계측기를 손으로 설정, 코드는 측정만
evm(modulation='load', waveform_path='...')   # SMW ARB 파형 로드
```

### 6-5. `acp` — 인접채널전력비 (5G NR)
변조신호로 SG 파워를 sweep 하며 채널전력과 ACP[dBc](스펙트럼 재성장)를 측정.

```python
acp(freq_hz=28e9)                         # modulation='setup'/'load'/'manual'
```

> ★ R&S 5G NR(K144)/ACP SCPI 는 펌웨어/옵션에 따라 다를 수 있다. 안 맞으면
> `modulation='manual'` 로 두고 계측기를 손으로 설정하거나, SMW/FSVA GUI 의
> SCPI Recorder 로 실제 시퀀스를 뽑아 드라이버를 교체한다.

---

### 6-6. `ip1db` — 입력 1-dB 압축점 **(RX / Blueway 전용)**

`start(chip='rx')` 후 사용. RX 신호 방향(SG → 채널 포트 → IC → 빔 포트 → SA)에서
CW 입력 전력을 sweep 해 이득이 1dB 꺾이는 입력 전력(IP1dB)을 찾는다.

```python
start(channels=['h1'], chip='rx')            # RX 세션 시작
ip1db(freq_hz=19.5e9, gain_code=0)           # gain_code 0 = 최대 게인
ip1db(freq_hz=19.5e9, pin_stop_dbm=-10)      # sweep 끝 레벨 올리기
ip1db(log_idd=True)                          # 매 포인트 합산 전류도 기록
```

결과: IP1dB[dBm](입력 기준), OP1dB[dBm](출력 기준), 소신호 게인. `params('ip1db')` 참고.
경로 손실은 Loss_data CSV 에서 자동 적용(TX/RX 구분 없음, `set_loss()` 로 수동 override 가능).

---

### 6-7. `rx_suite` — RX 채널 1개 측정 묶음 (Linearity + Gain Accuracy + EVM)

RX(Blueway) 한 채널에 대해 측정을 순서대로 돌리고 채널별 CSV 를 남긴다.
채널을 바꾸려면 SG 케이블을 해당 포트로 옮기고 channel 인자만 바꾼다.

```python
start(channels=['h0'], chip='rx')                       # RX 세션
rx_suite('h0', freq_hz=19.5e9, waveform_path='...')     # 한 채널 전체
rx_suite('v3', beam='b1')                               # B1 빔 측정(빔 지정). 생략 시 현재 빔 유지


# 수동(스텝별) — 자유도가 필요하면 개별 실행:
chan('h0')                                              # 채널/빔 세팅(active_channels 갱신)
ip1db(freq_hz=19.5e9)                                    # Linearity(+PDC); 기본 max gain, sweep -50..-20
gain_index_accuracy_common()                            # Gain Accuracy (common 축); RX 기본값
gain_index_accuracy_channel()                           # Gain Accuracy (channel/RTPS 축); RX 기본값
evm_rx()                                                # EVM bathtub; SMW에 이미 로드된 파형 사용(manual)
# evm_rx(waveform_path='/var/user/xxx.wv')              #   경로 주면 코드가 그 .wv를 SG에 로드(load)
```

- 스텝: linearity(`ip1db`) → gain_common → gain_chan → evm. 각자 CSV 저장.
- Total PDC 는 CSV 의 `Pdc_mW` 열에 이미 들어 있다(후처리 불필요).
- Gain Accuracy 두 sweep 은 파일명 축 태그(`_common_`/`_chan_`)로 구분된다.
- 스텝 파라미터는 `rx_suite('h0', linearity={'pin_stop_dbm': -8})` 처럼 덮어쓴다.
- **EVM**: `evm_rx()` 는 SG 에 ARB 파형을 로드하고 입력파워를 sweep 하며 EVM 을 잰다.
  FSVA NR 분석기는 **수동 설정**이 기본(`setup_sa=False`) — 측정 전 FSVA GUI 에서 NR 앱을
  파형에 맞게 세팅 + Auto EVM 해 둘 것. 코드 자동설정(DL)을 쓰려면 `setup_sa=True`.
  EVM 은 시작 시 **max gain**(common=0, RTPS=0)으로 고정해 측정하므로, rx_suite 에서
  직전 gain sweep 이 게인을 바꿔놔도 영향받지 않는다.
  SG baseband 도 양방향 자동: **CW 테스트(ip1db/gain/op1db)는 시작 시 baseband OFF**(CW
  보장), **EVM(manual)은 시작 시 선택된 ARB 파형 baseband ON**(파형 출력 보장). 따라서
  CW↔EVM 을 번갈아 돌려도 SG 변조 상태 때문에 틀어지지 않는다. 수동 토글은 `modoff()`
  (CW 로) / `modon()`(파형 ON).
  반대로 CW 테스트는 SA 를 spectrum(SAN) 모드로 두는데, EVM 은 시작 시 자동으로 NR 앱
  (`INST:SEL 'NR5G'`)으로 전환하므로(설정은 유지) SA 가 spectrum 모드여도 그대로 측정된다.

---

### 6-8. `tx_suite` — TX 측정 묶음 (항목·순서·주파수를 골라서)

TX(Stampede) 한 채널에 대해 **고른 테스트 항목들을** 순서대로 돌리고 스텝마다 CSV 를
남긴다. 채널을 바꾸려면 SA 케이블을 해당 포트로 옮기고 channel 인자만 바꾼다.

진입은 세 가지다.

```python
tx_suite()                        # 대화형 빌더 — 항목/채널/주파수/파라미터를 물어본다
tx_suite('h1')                    # 예전 4단계 프리셋 그대로 (op1db + gain x2 + evm)
tx_suite('h1', steps='vdd_sensitivity,evm', freqs='28e9,29e9,30e9')   # 조합 실행
```

**대화형 빌더** (`tx_suite()` 무인자):

```
=== TX Suite Builder ===
Available tests:
  1. op1db                    ...
  ...
  7. vdd_sensitivity          ...
Select tests in run order (e.g. 7,4) : 7,4      <- 번호 또는 이름(vdd_sensitivity,evm)
Channel [h1] :
Beam [b0] :
Frequencies, comma-separated [2.8e+10] : 28e9,29e9,30e9

--- params 1/2: vdd_sensitivity (Enter = keep default) ---
  vdd_list_v  [4.0, 3.6, ... V] :
  gain_code   [32]              : 0
--- params 2/2: evm ... ---

=== Plan: 2 test(s) x 3 freq(s) ===
Run now? [Y/n]:
```

파라미터 프롬프트는 `wizard()` 와 **같은 코드**를 쓴다(숨김 목록도 동일). 차이는
`freq_hz` 하나 — 앞에서 목록으로 한 번 받고 항목별 프롬프트에서는 빼므로, 같은 주파수
집합이 전 항목에 적용된다. 항목마다 다른 주파수를 주려면 비대화형 호출을 나눠 쓴다.

**실행 순서** — 기본은 `order='freq'` (freq-major): 한 주파수에서 전 항목을 돌고 다음
주파수로 간다.

```
28 GHz: vdd_sensitivity -> evm    29 GHz: vdd_sensitivity -> evm    30 GHz: ...
```

`order='step'` 이면 반대로 항목 하나를 전 주파수에서 돌고 다음 항목으로 간다.
**freq-major 는 주파수마다 SA 앱(spectrum <-> NR5G)을 오간다** — 전환 자체는
`FSVA3030._switch_app` 이 확인·재시도로 방어하지만(§6-8 아래 참고), 벤치에서 계속
불안정하면 `order='step'` 으로 전환 횟수를 항목 수만큼으로 줄인다.

- 스텝별 CSV 는 파일명에 주파수가 들어가 서로 안 덮인다(`..._28000MHz_...csv`).
- 한 스텝이 실패해도 다음 스텝은 계속 돌고, 끝에 `스텝/주파수/OK·FAIL/요약` 표가 나온다.
- 파라미터 덮어쓰기는 **test id 키**로 준다: `tx_suite('h1', steps='evm', evm={'pin_stop_dbm': -5})`.
  (예전 프리셋 경로는 예전 라벨 키 `linearity`/`gain_common`/`gain_chan`/`evm` 를 그대로 쓴다.)
- `freq_hz` 파라미터가 없는 항목은 주파수 확장 없이 한 번만 돈다.

**SA 모드 전환** — spectrum(SAN) 과 NR5G 를 오갈 때 예전에는 전환 직후 `SYST:ERR?` 를
곧장 읽어 계측기가 바쁘면 측정이 통째로 죽고, 단발 `*OPC?` 가 타임아웃되면 늦게 온
응답이 다음 query 로 밀려 desync 가 났다. 지금은 `_switch_app` 이 (1) 에러 큐를 전환
완료 후에 읽고 (2) `wait_opc_poll` 로 폴링 대기하고 (3) `INST:SEL?` 로 실제 전환을
확인해 아니면 재시도한다. 확인 응답 문자열은 벤더 매뉴얼로 확정하지 못해 부분일치로
보고, 예상 밖이면 경고만 남기고 진행한다.

**EVM 주파수** — `setup_sa=False`(suite 기본) 경로는 SA 설정을 사용자 것 그대로 쓰되
**center 주파수만은 그 스텝 주파수로 맞춘다**(`sa_follow_center`, 기본 `True`).
안 그러면 주파수를 여러 개 도는 동안 29/30 GHz EVM 이 28 GHz 에 맞춰진 NR 앱에서
조용히 측정된다. 일부러 off-center 로 재려면 `evm={'sa_follow_center': False}`.

**예전 프리셋**(`steps` 생략 시) 은 그대로다: linearity(`op1db`, max gain 0x00,
SA ref 25 dBm) -> gain_common -> gain_chan -> evm.

```python
# 수동(스텝별) — 자유도가 필요하면 개별 실행:
chan('h0')                                              # 채널/빔 세팅(active_channels 갱신)
op1db(gain_code=0x00, sa_ref_level_dbm=25)              # Linearity(+PDC); max gain, sweep -22..10
gain_index_accuracy(channel_codes=[0], log_psu=False)   # Gain Accuracy (common 축)
gain_index_accuracy(common_codes=[0], log_psu=False)    # Gain Accuracy (channel/attenuator 축)
evm(modulation='manual', setup_sa=False)                # EVM bathtub; SMW에 이미 로드된 파형 사용
```

- 게인 기본값: gain_index_accuracy(gain_common/gain_chan) 를 제외한 나머지 스텝은 **max gain**
  (op1db 는 gain_code 0x00, EVM 은 시작 시 common=0 + beam table=0 으로 리셋).
- **ACP 는 프리셋에 없다** — 필요하면 `acp()` 를 별도 실행하거나 `steps` 에 넣는다.
- Gain Accuracy 두 sweep 은 파일명 축 태그(`_common_`/`_chan_`)로 구분. SG 레벨 기본 0 dBm —
  max gain 에서 압축이 보이면 `tx_suite('h1', gain_common={'sg_level_dbm': -10})` 처럼 낮춘다.
- `rx_suite` 는 아직 예전 구조다(RX 검증 때 같은 구조로 바꿀 예정).

### 6-9. `phase_index_accuracy` — RTPS 위상 인덱스 정확도 (VNA, TX/RX 공통)

채널의 RTPS phase index(beam-table `phase_shifter_setting`, 7-bit 0..127)를 sweep 하며
**Anritsu MS4644B VNA** 로 S21 gain/phase 를 읽어 코드별 실제 위상/게인 변화를 기록한다.
code→degree 변환식은 벤더 미문서 — 이 측정이 그 매핑을 실측하는 것이다(명목 LSB 360/128=2.8125°).

**사전 준비 (중요):**
1. 케이블링: VNA port1 → DUT 입력, DUT 출력 → VNA port2 (SG/SA 경로와 다름 — suite 에 없음).
2. **VNA 캘리브레이션을 수동으로 수행**(현재 케이블링 기준). 코드는 절대 preset(*RST) 하지 않고,
   기본(`configure_freq=False`)에서는 주파수 설정도 안 건드린다(계기의 cal 된 sweep 그대로 사용).
3. `config/bench.toml`(TX)/`bench_rx.toml`(RX)의 `[vna]` host/port 확인
   (Anritsu raw-socket SCPI 포트는 보통 **5001**, 계기 System→Remote Interface 에서 확인).
4. 경로 손실 보정은 적용하지 않는다(VNA user cal 이 케이블을 이미 de-embed).

```python
chan('h0')                                             # 채널 bring-up (실행 중 chan() 금지 — beam table 리셋됨)
phase_index_accuracy()                                 # 전체 128코드, marker(스윕 중앙 1포인트)
phase_index_accuracy(marker_freq_hz=28e9)              # 분석 주파수 지정
phase_index_accuracy(phase_codes=list(range(0,128,8))) # 빠른 확인(16코드)
phase_index_accuracy(read_mode='trace')                # 코드마다 전체 sweep 저장
phase_index_accuracy(read_mode='point', freq_start_hz=27.5e9, freq_stop_hz=28.5e9,
                     freq_step_hz=250e6)               # 주파수 그리드만 저장
```

- **read_mode**: `marker`=코드당 1행(분석 주파수 최근접 트레이스 포인트, 기본) /
  `point`=freq_start..stop 을 freq_step 간격으로 뽑은 그리드 행 / `trace`=전체 sweep 행.
  셋 다 같은 complex S-data 쿼리에서 뽑으므로 계기 화면 포맷을 바꾸지 않는다.
- CSV 컬럼: `phase_code, freq_Hz, gain_dB, phase_deg` (+`log_psu=True` 시 레일 V/I).
  파일명에 모드 태그(`_marker`/`_point`/`_trace`)가 붙는다.
- 요약(메타): 분석 주파수에서 인접 코드 간 phase step 의 mean/std, 전체 span, gain ripple.
  pass/fail 판정은 없다(raw 데이터가 산출물).
- 측정 후 phase 는 0(phase zero)으로 복원되고 VNA 는 연속 sweep 으로 되돌린다.
- RX(Blueway): 메커니즘 동일. 직접 호출은 rx_default 가 적용되지 않으므로 19.5 GHz 대역
  주파수(`marker_freq_hz` 또는 point 그리드)를 명시할 것.
- `configure_freq=True` 로 코드가 sweep(start/stop/points)을 설정하게 할 수 있으나,
  **사용자 cal 그리드와 다르면 cal 이 보간/무효될 수 있다** — 기본 False 권장.

---

### 6-10. `vdd_sensitivity` — 공급전압(FE1) 민감도

`op1db` 와 **완전히 같은 sweep/계산**을 FE1(PA 공급, 정격 4.0V) 전압을 낮춰가며
반복한다. DC-DC/배터리 전압이 흔들릴 때 OP1dB·소신호 게인·Idd 가 얼마나 나빠지는지
한 번에 본다.

```python
vdd_sensitivity(freq_hz=28e9)                       # 기본 4.0/3.6/3.3/3.0/2.7/2.4/2.2 V
vdd_sensitivity(vdd_list_v=[4.0, 3.0, 2.2])         # 전압 계단만 바꿔서 짧게
vdd_sensitivity(gain_code=0x00, pin_stop_dbm=18)    # max gain + sweep 끝 확장
```

- **칩을 다시 bring-up 하지 않는다** — 4.0V 에서 게인/bias 를 잡아둔 뒤 공급전압만
  내린다(FE1 은 PA 공급 레일이라 SPI/디지털 상태는 유지). "설정 그대로, 전압만 강하"가
  이 측정의 정의다.
- 레일은 `bench.set_rail_voltage()` 로 `[ramp].step_v` 간격 램프로만 움직이고,
  **`bench.toml` 의 `v_target`(4.0V) 위로는 절대 올라가지 않는다.** 측정이 끝나거나
  중간에 예외·Ctrl-C 가 나도 항상 정격 4.0V 로 복구한다(복구 실패 시 `[ERROR]` 출력).
- 결과는 **CSV 한 개**: 맨 앞에 `VDD_set_V` 컬럼이 붙고 7개 sweep 이 이어 붙는다.
  FE1 실측 V/I 는 기존 레일 컬럼(`FE1_4V0_V` / `FE1_4V0_mA`)에 그대로 들어간다.
- 콘솔에는 전압별 `OP1dB / 소신호게인 / Idd_max / 정격 대비 Δ` 요약표가 나온다.
- 저전압에서 압축점이 sweep 범위 안에 안 잡히면 그 전압만 `n/a` 로 남기고 계속 진행한다
  (`pin_stop_dbm` 을 키우면 잡힌다).

`params('vdd_sensitivity')` 로 전체 파라미터. 나머지 파라미터는 `op1db` 와 동일하다.

## 7. 비대화 실행 (runner CLI)

세션을 안 열고 한 번에 돌리는 배치 방법(자동화/CI):

```powershell
python -m cloudchaser.runner list                              # 항목 목록
python -m cloudchaser.runner info channel_gain_alignment       # 파라미터 보기
python -m cloudchaser.runner run op1db --param gain_code=0 --param pin_stop_dbm=18
python -m cloudchaser.runner run gain_index_accuracy --fake    # 하드웨어 없이 dry-run
```

> 손실은 세션이든 runner 든 측정 시 자동으로 SG/SA 오프셋에 적용된다(Loss_data CSV, TX/RX 동일).
> VNA CSV 파일을 `Loss_data/` 에 넣으면 다음 측정부터 즉시 반영된다.

---

## 8. 레지스터 덤프와 대조

`regdump` CLI 로 실칩(또는 fake) 레지스터를 덤프하고, Sivers 레퍼런스 덤프나 이전
측정과 비교한다(설계 스펙 8.5·8.8 절차).

```powershell
python -m cloudchaser.regdump --fake --save out\fake_regs.csv        # fake 덤프 저장
python -m cloudchaser.regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx  # 실칩만
```

옵션:

```
python -m cloudchaser.regdump [옵션]
  --config PATH       bench.toml 경로(기본 config/bench.toml). RX 보드는 bench_rx.toml.
  --fake              하드웨어 없이 실행(fake SPI). bring-up 후 덤프.
  --no-power          전원 인가 생략(이미 켜져 있을 때).
  --save PATH         덤프를 addr,value CSV로 저장.
  --diff PATH         기준 덤프와 비교(theirs). .csv / .xlsx 모두 지원.
  --ours PATH         비교 대상(ours)을 파일에서 읽는다. 생략하면 실칩을 라이브로 읽는다.
  --range A B         덤프 주소 범위(기본 0x1000 0x1204).
```

> `python -m cloudchaser.regdump` 를 pytest 밖(cmd/PowerShell)에서 직접 실행할 때
> `ModuleNotFoundError: No module named 'cloudchaser'` 가 나면 프로젝트를
> editable install 하지 않은 환경이다 — `pip install -e .` 하거나
> `$env:PYTHONPATH="src"` 를 세션에 한 번 설정한다.

### fake 스모크 확인 (실험 PC 아니어도 됨)

골든 픽스처(`tests/data/golden_regs_tx_v1_split.csv`)는 `active_channels=["v1"]`,
`beam="b0"`, `split_mode=true`, `common_gain=0x00` 설정에서 생성됐고 `0x1000`-`0x106F`
(112워드)만 덮는다. 현재 `config/bench.toml` 의 기본값(`["h0"]`, `common_gain=0x20`)과
다르고, CLI 기본 `--range` 는 `0x1000 0x1204`(516워드)라 범위도 안 맞는다. 그래서
**명시적으로 `--range` 를 좁혀야** 골든과 비교가 된다:

```powershell
python -m cloudchaser.regdump --fake --range 0x1000 0x1070 --diff tests\data\golden_regs_tx_v1_split.csv
```

(`--range A B` 는 `[A, B)` 반열림 구간이다 — 골든이 `0x1000`-`0x106F` 112워드를
덮으므로 `B` 는 `0x1070` 이어야 마지막 레지스터 `0x106F` 까지 포함된다. `0x106F` 를
주면 그 레지스터가 빠져 `3 differing` 으로 하나 더 나온다.)

`bench.toml [board]` 도 골든과 같은 `active_channels=["v1"]` / `common_gain=0x00`
으로 맞춘 상태에서 실행하면(기본 `["h0"]`/`0x20` 로는 훨씬 많은 차이가 난다):

```
  0x1045:  theirs=0x2037  ours=0x0037
  0x1049:  theirs=0x0500  ours=0x0000
  2 differing / 112 compared
```

**기대 결과는 `0 differing` 이 아니라 이 `2 differing / 112 compared` 다.** 남는 잔차
2개(`0x1045`/`0x1049`)는 `Sivers_EVB/evb_full.py` 의 `MockSPI` 와 cloudchaser 가 쓰는
`sivers_api.Fake_SPI` 의 eFuse 시드가 다르기 때문이다(둘 다 fake 라 진짜 칩 eFuse가
아니라 각자 다른 값을 심어 둔다). 이건 설계 스펙 8.5 절이 "허용 가능한 잔차"로 분류한
바로 그 종류(다이별 eFuse bias)이지 SW 버그가 아니다.

### 실칩 대조

출장 때 Sivers 코드로 bring-up해 뜬 레퍼런스 덤프가
`reference/Data_260729_DoosanSTMP_RegDump.xlsx` 에 있다(repo 에 커밋돼 있다 --
`reference/` 의 다른 Sivers 자료와 같은 취급이다. 예전 주석의 "git-ignored" 는 틀렸다).

```powershell
python -m cloudchaser.regdump --diff reference\Data_260729_DoosanSTMP_RegDump.xlsx
```

레퍼런스 덤프는 `active_channels=["v1"]` + `beam="b0"` + `split_mode=true` 설정에서
뜬 것이다. 대조하려면 `bench.toml` 을 맞춰야 한다:

```toml
[board]
active_channels = ["v1"]
beam = "b0"
split_mode = true
```

**이 xlsx 파일에는 손상된 행이 10개 있다.** Excel 이 `0x10E0`-`0x10E9` 주소 10칸을
지수표기 숫자(`1e10` 등)로 자동변환해 원본 주소를 복구할 수 없게 만들었다. `regdump`
는 로드 시점에 이걸 알려준다:

```
note: 10 row(s) at 0x10E0-0x10E9 could not be parsed and were not compared
```

이 10개 레지스터는 diff 대상에서 **아예 제외**된다 — `N differing / M compared` 의
`M` 에 포함되지 않으므로, 그 주소 구간은 이 대조로 검증되지 않는다는 뜻이다.

판정 기준(출장 때 확립):

| 결과 | 해석 |
|---|---|
| 잔차가 **다이별 eFuse bias에만** 남음 (`0x1041`/`0x1045`/`0x1049` fe_bias, `0x1055` daisy) | 정상. SW 포팅 맞음, 남은 차이는 die 개체차 |
| 그 외 config 레지스터(routing/enable/pwrdn/DIRECT/extra/captune/ADC/temp)에도 잔차 | SW 문제 — bring-up 시퀀스 확인 |

## 9. optimize bias 전/후 비교

출장 결론이 "gain 미달 원인 = IC die 편차"였으므로, **명시적 bias write(v4 시트
`Casper`/`NF_OPTIM`)가 die 편차를 얼마나 흡수하는지**가 실측 관전 포인트다.
`config/bench.toml [board] optimized_bias` 를 바꿔가며 같은 코드로 두 번 측정한다
(설계 스펙 8.4 절차).

**① 적용 후 (기본, `optimized_bias = true`)**

```powershell
python -m cloudchaser.runner run op1db --out out\op1db_casper.csv
python -m cloudchaser.regdump --save out\regs_casper.csv
```

**② 적용 전 (`optimized_bias = false` 로 bench.toml 수정 후)**

```powershell
python -m cloudchaser.runner run op1db --out out\op1db_efuse.csv
python -m cloudchaser.regdump --save out\regs_efuse.csv
```

**③ 비교**

```powershell
python -m cloudchaser.regdump --diff out\regs_efuse.csv --ours out\regs_casper.csv
```

차이가 **`0x1038`/`0x103C`(FE PTAT)에만** 나와야 한다. 그 외 레지스터가 뜨면 설정이
섞인 것이다. OP1dB / Pdc 델타는 두 CSV를 직접 비교한다.

> **TX 의 `optimized_bias=false` 는 "최적화 전부 해제"가 아니다.** DIST bias 는 이
> 스위치로 한 비트도 안 바뀐다 — step 10 의 `set_dist_bias()` 결과를 step 18 의
> `DIRECT_REGS_TX`(`0x104C`=3378, `0x104D`, `0x1052`=8)가 무조건 덮기 때문이다.
> 실제로 갈리는 건 FE PTAT 뿐이다. 즉 `false` 는 **evb_full 베이스라인**(FE 는 eFuse,
> DIST 는 MATLAB 이 늘 쓰던 Casper 값 고정)이라고 읽어야 한다. 이건 의도된 동작이다:
> `DIRECT_REGS_TX` 를 조건부로 만들면 `evb_full` 과 레지스터가 갈려서 이 마이그레이션의
> 1번 목표(레지스터 동일성)가 깨진다.
> **DIST bias 를 정말 A/B 하려면 `src/cloudchaser/board/bringup.py` 의 `DIRECT_REGS_TX`
> 를 직접 편집해야 한다.** (RX 는 `DIRECT_REGS_RX` 에 `0x104C~` 가 없어서
> `optimized_bias` 가 FE·DIST 를 둘 다 되돌린다.)

`0x104D[5:0]`(`dist_st2_1_ptat`, 13 vs 28) 도 같은 방식으로 A/B 확인한다. 이건
`DIRECT_REGS` 경로라 `optimized_bias` 와 무관하게 늘 적용된다:

```powershell
# bench.toml:  dist_st2_1_ptat = 28  로 바꾸고 재측정
```

## 9-1. eFuse 트림이 실제로 올라왔는지 확인하는 법

`run_efuse_init = true` 로 A/B 하는 것은 **이 질문의 답이 되지 않는다.** Stampede
rev_1 의 `EFUSE_INSTRUCTIONS` 는 8단계뿐이고 `0x1055` / `0x1058` / `0x1059` /
`0x1068`-`0x106B` 만 만지는데, bring-up 이 그 **전부**를 뒤에서 덮는다(step 8 captune,
step 11 extra, step 18 DIRECT_REGS, step 19 split). 그래서 `true` 로 켜도 최종
레지스터에 남는 차이는 `0x1055` 의 `daisy_chain3_bias` 가 (RCLR 로) **지워진다**는
것 하나뿐이다.

트림이 die 에서 올라왔는지 보려면 **bring-up 전에** 읽어서 남겨야 한다. IPython 에서:

```python
from cloudchaser.bench import Bench
from cloudchaser.board.bringup import make_chip
from cloudchaser.board.firehawk import FH
B = Bench.from_toml('config/bench.toml'); B.connect_all(); B.power_up()
C = make_chip(B.board, fake=False); fh = FH(C, B.board.chip_id)
fh.reset()                                   # SPI 엔진 리셋(칩 POR 아님)
for a in (0x1055, 0x1058, 0x1059):
    print(f'0x{a:04X} = 0x{fh.rd(a):04X}')   # eFuse 스크립트가 만지는 주소
print('fe  :', fh.get_fe_bias())             # 행별 [PTAT1 PTAT2 PTAT3 CTAT CBIAS]
print('dist:', fh.get_dist_bias())
```

전부 0 이면 트림이 안 올라온 것이고, CTAT/CBIAS 에 die 별 값이 보이면 올라온 것이다.
(그 뒤 `bring_up_tx(C, B.board)` 를 부르면 된다.)

## 9-2. 채널을 바꿔 bring-up 을 다시 돌릴 때

bring-up 은 **비활성 채널/빔의 bias 행을 0 으로 기입한다.** `fh.reset()` 은 SPI 엔진
리셋이지 칩 POR 이 아니라서, 그 0 은 다음 bring-up 까지 칩에 그대로 남는다.
같은 chip 객체로 다시 bring-up 하면 첫 리드백을 캐시해 뒀다가 재사용하므로
(`board/bringup.py` `_efuse_readback`) 트림이 복원되지만, **`session.restart()` 처럼
chip 객체를 새로 만드는 경로는 POR 을 내지 않으므로 복원되지 않는다.**

- 측정 중 채널만 바꾸고 싶으면 **`chan('h1')` 을 쓴다**(bias 를 다시 안 쓴다).
- 채널을 바꿔 bring-up 을 처음부터 다시 돌리려면 **전원 사이클**(`shutdown()` 후
  PSU 재인가)이 필요하다 — 그래야 die eFuse 가 다시 로드된다.

---

## 10. 끝낼 때

```python
rfoff()        # RF 끄기
shutdown()     # 전원 0V 로 안전 종료(데이터시트 6.3 계단식 강하: TX 4->1.8->1->0, RX 1.8->1.5->1->0)
exit()         # IPython 종료 (전원이 켜져 있으면 자동으로 안전 차단됨)
```

---

## 핵심 객체

`B` = bench(계측기), `C` = chip(보드), `fh` = raw 레지스터 엔진(bring-up 이 쓰는 것과 동일 객체).
헬퍼로 안 되는 건 이 셋을 직접 조작한다.

**쓰기는 `fh`만 쓴다** — 벤더 `C.fields.wr(...)` 는 shadow 캐시를 거치는 쓰기 경로라 더
이상 쓰지 않는다(근거: 설계 스펙 2장). `C.fields.rd(...)` 는 HW 를 직접 읽으므로 읽기는
계속 안전하게 쓸 수 있다.

```python
C.fields.rd('b0_common_gain')     # 레지스터 필드 읽기 (벤더 API, 읽기 전용이라 안전)
fh.rd(0x1005)                     # 레지스터 주소 읽기 (raw 엔진, 위와 같은 값)
fh.wr_verify(0x1005, 0x10)        # 레지스터 주소 쓰기 + readback 검증 (쓰기는 이 경로만)
B.psu1.set_voltage(1, 4.0)        # PSU 직접 제어
B.read_all_vi()                   # 전 레일 V/I dict
```
