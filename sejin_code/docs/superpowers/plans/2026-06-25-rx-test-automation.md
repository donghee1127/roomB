# RX Test Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RX(Blueway) 4-test 측정을 기존 엔진 재사용으로 자동화한다 — 채널 1개를 인자로 받아 Linearity / Gain Accuracy(2축) / EVM 을 순차 실행하고 채널별 CSV 를 남긴다.

**Architecture:** 측정 코드는 기존 `ip1db` / `gain_index_accuracy` / `evm` 를 100% 재사용한다. 신규/변경 코드는 (1) `chan()` 이 `bench.board.active_channels`/`beam` 을 갱신, (2) `gain_index_accuracy` 가 sweep 축을 `meta["axis"]` 로 노출, (3) `_save_csv` 가 그 축을 파일명에 태깅, (4) `rx_suite()` 얇은 오케스트레이터 뿐이다. 출력은 raw CSV 만(`out/`).

**Tech Stack:** Python 3.13, pytest, socket SCPI(계측기), sivers_api(vendor, fake 가능).

## Global Constraints

- Python 3.13. 테스트는 프로젝트 venv: `.venv/Scripts/python.exe -m pytest`.
- **사용자에게 보이는 모든 텍스트(print/log/raise/`_ns` 노출 docstring)는 영어로 작성**(콘솔 cp949 한글 깨짐 방지). 코드 주석·모듈 docstring 은 한국어 OK.
- **커밋 전 pytest 통과 확인.** 설정값은 코드가 아니라 `config/*.toml` 에서 바꾼다.
- `--fake` 모드로 하드웨어 없이 동작해야 한다(계측기·SPI 만 가짜).
- 측정 단위는 채널 1개, 주파수 기본 19.5 GHz(파라미터로 변경 가능). 출력은 raw CSV 만.
- Git 흐름(CLAUDE.md): 작업 브랜치 생성 → 태스크별 커밋 → 전체 통과 후 main 머지 → push → 작업 브랜치 삭제. 파괴적 작업만 확인. 커밋 메시지 비ASCII(em-dash 등) 피함.
- spec: `docs/superpowers/specs/2026-06-25-rx-test-automation-design.md`.

먼저 작업 브랜치를 만든다: `git checkout -b feat/rx-test-automation`

---

### Task 1: `chan()` 이 active_channels/beam 갱신

**Files:**
- Modify: `src/cloudchaser/manual.py` (chan, 약 163-186행)
- Test: `tests/test_session_ux.py` (신규 테스트 함수 추가)

**Interfaces:**
- Consumes: `build_namespace(bench, chip, beam)` 가 만드는 `chan(ch, b=None)` 클로저(이미 `bench`/`chip`/`beam` 접근 가능).
- Produces: `chan(ch, b=None)` 호출 후 `bench.board.active_channels == [ch]`, `bench.board.beam == (b or 기존 beam)`. 측정 아이템(ip1db/gain/evm)이 채널 meta·loss 계산에 이 값을 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_session_ux.py` 끝에 추가)

```python
def test_chan_updates_active_channel():
    """chan() must update bench.board.active_channels/beam so test items
    pick up the right channel for CSV meta and path-loss."""
    from cloudchaser import session
    sess = _start_fake_rx()
    sess["chan"]("h0")
    assert session.B.board.active_channels == ["h0"]
    sess["chan"]("v3", "b1")
    assert session.B.board.active_channels == ["v3"]
    assert session.B.board.beam == "b1"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_ux.py::test_chan_updates_active_channel -v`
Expected: FAIL — `assert ['h1'] == ['h0']` (chan 이 active_channels 를 안 바꿈).

- [ ] **Step 3: 최소 구현** — `manual.py` 의 `chan()` 에서 `bm = b or beam` 다음 줄에 추가

기존:
```python
        bm = b or beam
        chip.path.disable_all()
```
변경:
```python
        bm = b or beam
        # 측정 대상 채널/빔을 bench 부기에 반영 -> 측정 아이템이 채널 meta(파일명)
        # 와 경로 손실 계산에 active_channels[0]/beam 을 그대로 쓴다.
        bench.board.active_channels = [ch]
        bench.board.beam = bm
        chip.path.disable_all()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_ux.py::test_chan_updates_active_channel -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인 + 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_ux.py tests/test_workbook_smoke.py -q`
Expected: 전부 PASS

```bash
git add src/cloudchaser/manual.py tests/test_session_ux.py
git commit -m "feat(chan): update bench.board.active_channels/beam on channel switch"
```

---

### Task 2: `gain_index_accuracy` 가 sweep 축을 `meta["axis"]` 로 노출

**Files:**
- Modify: `src/cloudchaser/test_items/gain_index_accuracy.py` (TestResult meta, 약 230-237행)
- Test: `tests/test_test_items_fake.py` (신규 테스트 함수 추가)

**Interfaces:**
- Consumes: `gain_index_accuracy.run()` 내부의 `ccodes`(common_codes), `chcodes`(channel_codes).
- Produces: `result.meta["axis"]` ∈ {`"common"`, `"chan"`, `"2d"`, `None`}. common 만 다수면 `"common"`, channel 만 다수면 `"chan"`, 둘 다 다수면 `"2d"`, 둘 다 단일이면 `None`. Task 3(`_save_csv`)가 이 값을 파일명 태그로 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_test_items_fake.py` 에 추가)

```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_gain_index_accuracy_axis_meta():
    """meta['axis'] reflects which gain axis was swept (for CSV filename tag)."""
    from cloudchaser.test_items import get_test
    test = get_test("gain_index_accuracy")

    def run(common, channel):
        ctx = _make_ctx()
        p = test().resolve({"common_codes": common, "channel_codes": channel,
                            "settle_s": 0.0})
        r = test().run(ctx, p, log=lambda *a, **k: None)
        ctx.bench.close_all()
        return r.meta.get("axis")

    assert run([0, 1, 2], [0]) == "common"
    assert run([0], [0, 1, 2]) == "chan"
    assert run([0, 1], [0, 1]) == "2d"
    assert run([0], [0]) is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_test_items_fake.py::test_gain_index_accuracy_axis_meta -v`
Expected: FAIL — `meta.get("axis")` 가 None (키 없음) 이라 첫 assert 에서 실패.

- [ ] **Step 3: 최소 구현** — `gain_index_accuracy.py` 의 `return TestResult(...)` 직전에 axis 계산 추가하고 meta 에 넣는다.

기존 (약 229-237행):
```python
        log(f"[gain-sw] {summary}")
        return TestResult(self.id, self.title, passed, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "channel_quad": chquad,
```
변경:
```python
        # sweep 한 축 식별(파일명 태그용). 한 축만 다수면 그 축, 둘 다면 2d, 둘 다 단일이면 None.
        n_c, n_ch = len(ccodes), len(chcodes)
        axis = ("common" if n_c > 1 and n_ch == 1 else
                "chan" if n_ch > 1 and n_c == 1 else
                "2d" if n_c > 1 and n_ch > 1 else None)
        log(f"[gain-sw] {summary}")
        return TestResult(self.id, self.title, passed, summary, columns, rows,
                          meta={"beam": beam, "channel": channel,
                                "axis": axis,
                                "channel_quad": chquad,
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_test_items_fake.py::test_gain_index_accuracy_axis_meta -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인 + 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests/test_test_items_fake.py -q`
Expected: 전부 PASS (기존 `test_gain_index_accuracy_run` 포함)

```bash
git add src/cloudchaser/test_items/gain_index_accuracy.py tests/test_test_items_fake.py
git commit -m "feat(gain): expose swept axis as meta['axis'] for CSV tagging"
```

---

### Task 3: `_save_csv` 가 `meta["axis"]` 를 파일명에 태깅

**Files:**
- Modify: `src/cloudchaser/runner.py` (`_save_csv`, 약 102-105행)
- Test: `tests/test_measurement_logging.py` (신규 테스트 함수 추가)

**Interfaces:**
- Consumes: `result.meta.get("axis")` (Task 2 가 설정).
- Produces: 파일명 패턴 `{test_id}_{ymd}_{beam}_{channel}_{freq}{gtag}{atag}_{hms}.csv`, 여기서 `atag = f"_{axis}"` (axis 가 truthy 일 때) / `""` (None·없음). axis 없는 테스트는 파일명 불변(하위호환).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_measurement_logging.py` 에 추가)

```python
def test_save_csv_axis_tag(tmp_path):
    """_save_csv inserts meta['axis'] into the filename; absent axis = unchanged."""
    from cloudchaser import runner
    from cloudchaser.test_items.base import TestResult

    def save(meta):
        r = TestResult("gain_index_accuracy", "Gain Index Accuracy", None,
                       "ok", ["a"], [[1]], meta=meta)
        return runner._save_csv(r, {}, tmp_path, log=lambda *a, **k: None).name

    base = {"beam": "b0", "channel": "h0", "freq_hz": 19.5e9}
    assert "_common_" in save({**base, "axis": "common"})
    assert "_chan_" in save({**base, "axis": "chan"})
    name_none = save({**base, "axis": None})
    assert "_None_" not in name_none and "_common_" not in name_none
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_measurement_logging.py::test_save_csv_axis_tag -v`
Expected: FAIL — 파일명에 `_common_` 가 없음.

- [ ] **Step 3: 최소 구현** — `runner.py` `_save_csv` 의 `gtag` 다음에 `atag` 추가 후 path 에 삽입.

기존 (약 103-105행):
```python
        gain = meta.get("gain_code")
        gtag = f"_G{int(gain):02X}" if gain is not None else ""
        path = out_dir / f"{result.test_id}_{ymd}_{beam}_{channel}_{freq}{gtag}_{hms}.csv"
```
변경:
```python
        gain = meta.get("gain_code")
        gtag = f"_G{int(gain):02X}" if gain is not None else ""
        # gain_index_accuracy 의 common/chan sweep 을 구분하는 축 태그(없으면 무영향).
        axis = meta.get("axis")
        atag = f"_{axis}" if axis else ""
        path = out_dir / f"{result.test_id}_{ymd}_{beam}_{channel}_{freq}{gtag}{atag}_{hms}.csv"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_measurement_logging.py::test_save_csv_axis_tag -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인 + 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests/test_measurement_logging.py -q`
Expected: 전부 PASS

```bash
git add src/cloudchaser/runner.py tests/test_measurement_logging.py
git commit -m "feat(csv): append sweep-axis tag to gain-accuracy filenames"
```

---

### Task 4: `rx_suite()` 오케스트레이터

**Files:**
- Modify: `src/cloudchaser/session.py` (신규 `rx_suite` 함수 + `_finalize` 의 `_ns.update` 등록)
- Test: `tests/test_session_ux.py` (신규 테스트 함수 추가)

**Interfaces:**
- Consumes: 전역 `B`/`C`/`_ns`(start() 후 설정), `_ns["chan"]`(Task 1), `_run_test(test_id, kw)`.
- Produces: `rx_suite(channel="h0", freq_hz=19.5e9, beam=None, waveform_path="", **overrides)` — 채널 세팅 후 4스텝(label: `linearity`/`gain_common`/`gain_chan`/`evm`) 순차 실행, 각 스텝이 자체 CSV 저장, `TestResult|None` 리스트(길이 4) 반환. `overrides[label]` (dict) 로 스텝 파라미터 덮어쓰기.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_session_ux.py` 에 추가)

```python
def test_rx_suite_runs_four_steps(tmp_path, monkeypatch):
    """rx_suite runs 4 steps for one channel, each saving its own CSV with
    the right axis tags, and sets the active channel."""
    from cloudchaser import session, runner
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path)
    _start_fake_rx()
    tiny = dict(settle_s=0.0)
    results = session.rx_suite(
        "h0", freq_hz=19.5e9,
        linearity={"pin_start_dbm": -40, "pin_stop_dbm": -38, **tiny},
        gain_common={"common_codes": [0, 1], **tiny},
        gain_chan={"channel_codes": [0, 1], **tiny},
        evm={"pin_start_dbm": -40, "pin_stop_dbm": -38, "pin_step_db": 2,
             "modulation": "manual", **tiny},
    )
    assert len(results) == 4
    assert session.B.board.active_channels == ["h0"]
    names = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert len(names) == 4
    assert any("ip1db" in n for n in names)
    assert any("gain_index_accuracy" in n and "_common_" in n for n in names)
    assert any("gain_index_accuracy" in n and "_chan_" in n for n in names)
    assert any("evm" in n for n in names)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_ux.py::test_rx_suite_runs_four_steps -v`
Expected: FAIL — `AttributeError: module 'cloudchaser.session' has no attribute 'rx_suite'`.

- [ ] **Step 3: 최소 구현 (3a)** — `session.py` 의 `ip1db()` 함수(약 421행) 다음에 `rx_suite` 추가

```python
def rx_suite(channel="h0", freq_hz=19.5e9, beam=None, waveform_path="", **overrides):
    """Run the RX measurement suite for ONE channel and save a CSV per step.

    Steps (each saves its own CSV; a failing step is skipped, others continue):
      1. linearity    = ip1db   (max gain CW Pin sweep; also covers Total PDC)
      2. gain_common  = gain_index_accuracy (sweep common, channel held at max gain)
      3. gain_chan    = gain_index_accuracy (sweep channel RTPS, common at max gain)
      4. evm          = evm     (load waveform, EVM vs input power)
    Total PDC is derived later from the linearity CSV. Override a step's params
    with overrides[label], e.g. rx_suite('h0', linearity={'pin_stop_dbm': -8}).
    """
    if C is None:
        print("not started. call start(channels=['h0'], chip='rx') first.")
        return None
    chan_fn = _ns.get("chan")
    if chan_fn is None:
        print("rx_suite: 'chan' not available in session namespace.")
        return None
    chan_fn(channel, beam)
    steps = [
        ("linearity", "ip1db",
         {"freq_hz": freq_hz, "gain_code": 0, "pin_start_dbm": -54.0,
          "pin_stop_dbm": -11.0, "pin_step_db": 1.0}),
        ("gain_common", "gain_index_accuracy",
         {"freq_hz": freq_hz, "common_codes": list(range(64)),
          "channel_codes": [0], "log_psu": False}),
        ("gain_chan", "gain_index_accuracy",
         {"freq_hz": freq_hz, "common_codes": [0],
          "channel_codes": list(range(64)), "channel_kind": "beamtable",
          "log_psu": False}),
        ("evm", "evm",
         {"freq_hz": freq_hz, "modulation": "load", "waveform_path": waveform_path}),
    ]
    results = []
    for label, test_id, kw in steps:
        ov = overrides.get(label)
        if isinstance(ov, dict):
            kw.update(ov)
        print(f"--- rx_suite step: {label} ({test_id}) ---")
        try:
            results.append(_run_test(test_id, kw))
        except Exception as e:  # noqa: BLE001
            print(f"[rx_suite] step '{label}' failed: {e} -- continuing")
            results.append(None)
    ok = sum(1 for r in results if r is not None)
    print(f"=== rx_suite({channel}) done: {ok}/{len(steps)} steps OK ===")
    return results
```

- [ ] **Step 4: 최소 구현 (3b)** — `_finalize` 의 `_ns.update({...})` 에 `rx_suite` 등록

기존 (약 295행):
```python
        "ip1db": ip1db,
        "params": params, "tests": tests,
```
변경:
```python
        "ip1db": ip1db, "rx_suite": rx_suite,
        "params": params, "tests": tests,
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session_ux.py::test_rx_suite_runs_four_steps -v`
Expected: PASS

- [ ] **Step 6: 회귀 확인 + 커밋**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

```bash
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "feat(session): add rx_suite one-channel RX measurement orchestrator"
```

---

### Task 5: 문서 동기화 (SESSION.md / workbook / README)

**Files:**
- Modify: `docs/SESSION.md` (§6 측정 항목에 RX suite 절 추가)
- Modify: `scripts/cloudchaser_workbook.py` (RX 측정 STEP 참고 블록/주석 추가)
- Modify: `README.md` (테스트 목록에 rx_suite 언급)

**Interfaces:**
- Consumes: Task 1-4 의 최종 동작(`chan` 채널 전환, `rx_suite` 시그니처, CSV 축 태그).
- Produces: 문서만. 코드 동작 변경 없음.

- [ ] **Step 1: SESSION.md 에 RX suite 절 추가** — §6.6(ip1db) 다음에 추가

```markdown
### 6-7. `rx_suite` — RX 채널 1개 측정 묶음 (Linearity + Gain Accuracy + EVM)

RX(Blueway) 한 채널에 대해 측정을 순서대로 돌리고 채널별 CSV 를 남긴다.
채널을 바꾸려면 SG 케이블을 해당 포트로 옮기고 channel 인자만 바꾼다.

```python
start(channels=['h0'], chip='rx')                 # RX 세션
rx_suite('h0', freq_hz=19.5e9, waveform_path='...')   # 한 채널 전체

# 수동(스텝별) — 자유도가 필요하면 개별 실행:
chan('h0')                                        # 채널/빔 세팅(active_channels 갱신)
ip1db(freq_hz=19.5e9, gain_code=0, pin_start_dbm=-54, pin_stop_dbm=-11)  # Linearity(+PDC)
gain_index_accuracy(freq_hz=19.5e9, common_codes=list(range(64)),
                    channel_codes=[0], log_psu=False)        # Gain Accuracy (common 축)
gain_index_accuracy(freq_hz=19.5e9, common_codes=[0],
                    channel_codes=list(range(64)),
                    channel_kind='beamtable', log_psu=False)  # Gain Accuracy (channel 축)
evm(freq_hz=19.5e9, modulation='load', waveform_path='...')   # EVM
```

- 스텝: linearity(`ip1db`) → gain_common → gain_chan → evm. 각자 CSV 저장.
- Total PDC 는 Linearity CSV 의 레일 V/I 에서 후처리로 추출(별도 측정 없음).
- Gain Accuracy 의 두 sweep 은 파일명 축 태그(`_common_`/`_chan_`)로 구분된다.
- 스텝 파라미터는 `rx_suite('h0', linearity={'pin_stop_dbm': -8})` 처럼 덮어쓴다.
```

- [ ] **Step 2: workbook 에 RX 측정 참고 추가** — `scripts/cloudchaser_workbook.py` 의 측정 STEP 영역에 RX suite 주석 블록 추가(기존 STEP 스타일에 맞춰, 복붙용)

```python
# =============================================================================
# [STEP 6-RX] RX measurement suite (Blueway) -- one channel at a time
#   Move the SG cable to the channel's antenna port, set CHANNELS=["h0"],
#   then run. Each test saves its own CSV to out/.
# =============================================================================
# rx_suite("h0", freq_hz=19.5e9, waveform_path="")     # full suite for one channel
#
# # or run steps manually for control:
# chan("h0")                                           # set channel (updates active_channels)
# ip1db(freq_hz=19.5e9, gain_code=0, pin_start_dbm=-54, pin_stop_dbm=-11)   # Linearity (+PDC)
# gain_index_accuracy(freq_hz=19.5e9, common_codes=list(range(64)),
#                     channel_codes=[0], log_psu=False)            # Gain Accuracy (common)
# gain_index_accuracy(freq_hz=19.5e9, common_codes=[0],
#                     channel_codes=list(range(64)),
#                     channel_kind="beamtable", log_psu=False)     # Gain Accuracy (channel)
# evm(freq_hz=19.5e9, modulation="load", waveform_path="")         # EVM
```

- [ ] **Step 3: README 테스트 목록에 추가** — 측정 항목/테스트 목록 부분에 한 줄 추가

```markdown
- `rx_suite` — RX 채널 1개 측정 묶음(Linearity + Gain Accuracy 2축 + EVM, 채널별 CSV)
```

- [ ] **Step 4: workbook smoke 테스트로 문법 확인 + 전체 테스트**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workbook_smoke.py -q && .venv/Scripts/python.exe -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add docs/SESSION.md scripts/cloudchaser_workbook.py README.md
git commit -m "docs(rx): document rx_suite and manual RX step flow"
```

---

## 최종 통합 (모든 태스크 후)

- [ ] 전체 테스트: `.venv/Scripts/python.exe -m pytest -q` → 전부 PASS
- [ ] main 머지 + push:
```bash
git checkout main
git merge --no-ff feat/rx-test-automation -m "Merge feat/rx-test-automation"
git branch -d feat/rx-test-automation
git push origin main
```
- [ ] 실험 PC 수동 검증(코드 아님, 사용자): H0 에서 `rx_suite('h0')` 또는 개별 명령 실행 → CSV 가 reference 시트와 정합하는지 확인. EVM waveform 경로 확정.
