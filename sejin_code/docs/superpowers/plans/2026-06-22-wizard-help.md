# wizard() + enhanced help() + start() banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `wizard()` guided measurement function, expand `help()` to show purpose/key-params per test, and improve the `start()` completion banner so returning users immediately know what to do.

**Architecture:** All changes are confined to `src/cloudchaser/session.py`. Two module-level dicts (`_WIZARD_HIDDEN`, `_WIZARD_USES_LOSS`) capture wizard configuration. The `_HELP` dict "measure" section expands to 3-tuples. `wizard()` is a new module-level function wired into `_ns` by `start()`.

**Tech Stack:** Python 3.13, IPython namespace injection, `builtins.input()` for prompts, existing `Param`/`coerce`/`list_tests` from `test_items`.

## Global Constraints

- Python 3.13, venv at `.venv`
- User-visible output and exceptions in **English** (cp949 console; no Korean in print/raise)
- Code comments/docstrings may be Korean
- Run tests: `python -m pytest` from project root
- All tests must pass before commit
- No new dependencies; no changes outside `session.py` and the new test file

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/cloudchaser/session.py` | Modify | Add `_WIZARD_HIDDEN`, `_WIZARD_USES_LOSS`, `wizard()`; expand `_HELP`; update `help()` print loop + detail; fix `start()` banner; wire `wizard` into `_ns` |
| `tests/test_session_ux.py` | Create | Fake-mode tests for help() format, start() banner, wizard() flow |

---

## Task 1: Expand `_HELP["measure"]` and update `help()` output

### Files
- Modify: `src/cloudchaser/session.py`
- Test: `tests/test_session_ux.py`

### Interfaces
- Consumes: existing `_HELP` dict, existing `help()` function
- Produces: `_HELP["measure"]` items now support 3-tuple `(sig, desc, hint)` and special `"!warn"` sentinel; `help()` prints expanded format for measure section

- [ ] **Step 1: Create test file and write failing test for expanded help output**

Create `tests/test_session_ux.py`:

```python
"""Session UX 개선(wizard/help/banner) 오프라인 테스트.

sivers_api 가 없으면 전부 skip.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SIVERS_MISSING = importlib.util.find_spec("sivers_api") is None
CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def _start_fake():
    """fake 세션 시작 헬퍼. power=False 로 PSU 램프업 없이 연결+bring-up 만."""
    from cloudchaser import session
    session.start(channels=["h1"], fake=True, power=False, config=CONFIG)
    return session


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_help_measure_section_shows_purpose(capsys):
    """help() 의 measure 섹션이 목적(desc)과 힌트(hint) 두 줄을 출력해야 한다."""
    sess = _start_fake()
    sess.help()
    out = capsys.readouterr().out
    # 3-tuple 항목: sig 다음 줄에 desc 가 들여쓰기로 나와야 함
    assert "CW power sweep" in out          # op1db desc
    assert "gain_code(0=max)" in out        # op1db hint
    assert "H1 / H3 / V1" in out           # broken-channel warning


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_help_detail_shows_param_table(capsys):
    """help('op1db') 가 파라미터 표를 포함해야 한다."""
    sess = _start_fake()
    sess.help("op1db")
    out = capsys.readouterr().out
    assert "freq_hz" in out
    assert "gain_code" in out
    assert "pin_start_dbm" in out
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_session_ux.py::test_help_measure_section_shows_purpose tests/test_session_ux.py::test_help_detail_shows_param_table -v
```

Expected: FAIL — `"CW power sweep"` not found in output (current help() is single-line format).

- [ ] **Step 3: Expand `_HELP["measure"]` to 3-tuples and update `help()` print loop**

In `session.py`, replace the entire `_HELP` dict's `"measure"` section and update the `help()` print loop.

**Replace `_HELP["measure"]` (the existing list):**

```python
    "measure": [
        # ("!warn", message, "")  → printed as  !!  message
        ("!warn", "Healthy channels only: H1 / H3 / V1 / V2 / V3", ""),
        # 3-tuple: (signature, purpose, key-params hint)
        ("op1db(freq_hz=28e9, gain_code=0)",
         "CW power sweep -> output 1-dB compression point. CSV -> out/.",
         "Key: gain_code(0=max gain), pin_start/stop_dbm, log_idd  |  params('op1db')"),
        ("gain_index_accuracy(sg_level_dbm=0)",
         "Sweep common & per-path(RTPS) gain codes, record gain vs index.",
         "Key: channel_kind('beamtable'), channel_quad  |  params('gain_index_accuracy')"),
        ("channel_gain_alignment(channel_mode='all')",
         "Move SA cable per channel, record output level spread.",
         "channel_mode: 'all'(all ON, move cable) / 'single'(switch per ch)  |  params('channel_gain_alignment')"),
        ("evm(freq_hz=28e9)",
         "5G NR modulation quality (EVM[dB]) vs output power.",
         "Key: modulation(setup/load/manual), waveform_path  |  params('evm')"),
        ("acp(freq_hz=28e9)",
         "Adjacent channel power ratio[dBc] vs output power.",
         "Key: modulation  |  params('acp')"),
        ("params('op1db')", "show that test's parameters & defaults", ""),
        ("tests()", "list available tests", ""),
        ("wizard()", "guided step-by-step measurement  <-- start here", ""),
    ],
```

**Replace the `help()` function body's inner print loop** (the part inside `if topic is None:`):

```python
def help(topic=None):
    """명령어 도움말. help() = 전체 목록, help('rf') = 특정 명령 상세."""
    if topic is None:
        print("=== Cloudchaser session -- type help('name') for detail ===")
        for cat, items in _HELP.items():
            print(f"\n[{cat}]")
            for item in items:
                if item[0] == "!warn":
                    print(f"  !! {item[1]}")
                elif len(item) == 3:
                    sig, desc, hint = item
                    print(f"  {sig}")
                    print(f"    {desc}")
                    if hint:
                        print(f"    {hint}")
                else:
                    sig, desc = item
                    print(f"  {sig:52} {desc}")
        print("\n  objects: B (bench), C (chip).  quit IPython: exit()")
        return
    fn = _ns.get(topic)
    if callable(fn):
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = "(...)"
        doc = inspect.getdoc(fn) or "(no description)"
        print(f"{topic}{sig}\n\n{doc}")
        # 테스트 항목이면 파라미터 표도 출력
        try:
            from .test_items import REGISTRY
            if topic in REGISTRY:
                cls = REGISTRY[topic]
                if cls.params:
                    print("\nParameters:")
                    for p in cls.params:
                        unit_str = f" {p.unit}" if p.unit else ""
                        default_str = f"{p.default}{unit_str}"
                        print(f"  {p.name:<22} {p.type:<10} {default_str:<18} {p.help or p.label}")
        except Exception:
            pass
    else:
        names = ", ".join(k for k in _ns if not k.startswith("_") and callable(_ns.get(k)))
        print(f"'{topic}' is not a command. available:\n  {names}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_session_ux.py::test_help_measure_section_shows_purpose tests/test_session_ux.py::test_help_detail_shows_param_table -v
```

Expected: PASS both.

- [ ] **Step 5: Run full test suite**

```
python -m pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "feat: expand help() measure section to 3-tuple format with purpose and key-params"
```

---

## Task 2: Improve `start()` completion banner

### Files
- Modify: `src/cloudchaser/session.py`
- Test: `tests/test_session_ux.py` (add test)

### Interfaces
- Consumes: `start()` in session.py
- Produces: `start()` prints wizard/help/status hints + typical flows + broken HW warning

- [ ] **Step 1: Add failing test for start() banner**

Append to `tests/test_session_ux.py`:

```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_start_banner_shows_wizard_and_flows(capsys):
    """start() 완료 후 배너에 wizard(), help(), typical flows, 불량 채널 경고가 있어야 한다."""
    _start_fake()
    out = capsys.readouterr().out
    assert "wizard()" in out
    assert "help()" in out
    assert "Broken HW" in out or "Broken" in out
    assert "op1db" in out          # typical flow 예시
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_session_ux.py::test_start_banner_shows_wizard_and_flows -v
```

Expected: FAIL — current banner only prints `"type help() for commands."`, no `wizard()` mention.

- [ ] **Step 3: Replace the two banner print lines in `start()`**

Find this block near the end of `start()`:

```python
    print(f"[session] ready: channels={B.board.active_channels} beam={bm} "
          f"fake={fake} power={power}")
    print("type help() for commands.  (objects: B=bench, C=chip)")
```

Replace with:

```python
    print(f"[session] ready: channels={B.board.active_channels}  beam={bm}"
          f"  fake={fake}  power={power}")
    print()
    print("  wizard()   <- step-by-step guided measurement  (start here)")
    print("  help()     <- full command reference")
    print("  status()   <- current channel / gain / SG state")
    print()
    print("  Typical flows:")
    print("    Signal check : rf(True, freq=28e9, level=-10) -> peak()")
    print("    OP1dB        : op1db(freq_hz=28e9)")
    print("    Chan align   : channel_gain_alignment(channel_mode='all')")
    print()
    print("  !! Broken HW: H0 / V0 / H2  ->  use H1 / H3 / V1..V3")
```

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/test_session_ux.py::test_start_banner_shows_wizard_and_flows -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```
python -m pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "feat: improve start() banner with wizard hint, typical flows, broken-HW warning"
```

---

## Task 3: Add `wizard()` function, wire into `_ns` and `_HELP`

### Files
- Modify: `src/cloudchaser/session.py`
- Test: `tests/test_session_ux.py` (add test)

### Interfaces
- Consumes: `list_tests()`, `coerce()` from `test_items`; `_ns` (to call session functions at runtime); `_WIZARD_HIDDEN`, `_WIZARD_USES_LOSS` (new module-level dicts)
- Produces: `wizard()` — callable from IPython; added to `_ns` by `start()`; returns `TestResult | None`

- [ ] **Step 1: Add failing test for wizard()**

Append to `tests/test_session_ux.py`:

```python
@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_op1db_fake(monkeypatch):
    """wizard() で op1db を選んでデフォルトで実行 -> TestResult が返る."""
    from cloudchaser.test_items import TestResult
    sess = _start_fake()

    # Simulate user inputs:
    #   "1"  -> select op1db (first test)
    #   ""   -> freq_hz: keep default
    #   ""   -> gain_code: keep default
    #   ""   -> pin_start_dbm: keep default
    #   ""   -> pin_stop_dbm: keep default
    #   ""   -> log_idd: keep default
    #   "n"  -> no loss override
    #   "y"  -> confirm run
    responses = iter(["1", "", "", "", "", "", "n", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    result = sess.wizard()
    assert result is not None
    assert isinstance(result, TestResult)
    assert result.test_id == "op1db"


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_quit(monkeypatch):
    """wizard() に 'q' を入力すると None を返す."""
    sess = _start_fake()
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")
    result = sess.wizard()
    assert result is None


@pytest.mark.skipif(_SIVERS_MISSING, reason="sivers_api not installed")
def test_wizard_cancel_at_confirm(monkeypatch):
    """wizard() 최종 확인에서 'n' 입력 시 None 반환."""
    sess = _start_fake()
    responses = iter(["1", "", "", "", "", "", "n", "n"])  # last "n" = cancel run
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    result = sess.wizard()
    assert result is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_session_ux.py::test_wizard_op1db_fake tests/test_session_ux.py::test_wizard_quit tests/test_session_ux.py::test_wizard_cancel_at_confirm -v
```

Expected: FAIL — `AttributeError: module 'cloudchaser.session' has no attribute 'wizard'`.

- [ ] **Step 3: Add `_WIZARD_HIDDEN` and `_WIZARD_USES_LOSS` dicts to `session.py`**

Insert after the imports block (before `B = None` globals), right after `from .test_items import TestContext, get_test, list_tests`:

```python
# wizard: 프롬프트에서 숨길 파라미터(기본값으로 자동 사용)
_WIZARD_HIDDEN: dict[str, set] = {
    "op1db": {
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "sa_ref_level_dbm", "settle_s", "gain_field",
    },
    "gain_index_accuracy": {
        "common_field", "channel_field", "common_codes", "channel_codes",
        "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "channel_gain_alignment": {
        "max_gain_code", "beam", "common_field", "channels",
        "apply_loss", "in_loss_db", "out_loss_db",
        "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "evm": {
        "pin_step_db", "bw_mhz", "auto_evm_each", "settle_s",
    },
    "acp": {
        "pin_step_db", "bw_mhz", "chan_bw_hz", "spacing_hz", "n_adj", "settle_s",
    },
}

# _apply_loss 가 자동 적용되는 테스트(wizard 에서 손실 override 옵션 제공)
_WIZARD_USES_LOSS: frozenset = frozenset({"op1db", "gain_index_accuracy", "evm", "acp"})
```

- [ ] **Step 4: Add `wizard()` function to `session.py`**

Insert the full function just before the `_HELP` dict definition (after the `peakc` function):

```python
def wizard():
    """Step-by-step guided measurement.

    Prompts for test selection and key parameters, then calls the
    corresponding session function. Path loss is auto-applied from
    loss.toml (same as calling the function directly).
    Usage: call after start().
    """
    if C is None:
        print("Not started. Call start(channels=['h1']) first.")
        return None

    all_tests = list_tests()
    channels = getattr(B.board, "active_channels", []) if B else []
    beam = getattr(B.board, "beam", "b0") if B else "b0"

    print("=== Measurement Wizard ===")
    print(f"Active: channels={channels}  beam={beam}")
    print("!! Broken HW: H0 / V0 / H2 -- use H1 / H3 / V1 / V2 / V3")
    print()
    print("Select test:")
    for i, t in enumerate(all_tests, 1):
        desc = (t.description or t.title)[:65]
        print(f"  {i}. {t.id:<28} {desc}")
    print("  q. quit")
    print()

    raw = input("> ").strip().lower()
    if raw in ("q", "quit", ""):
        print("wizard: cancelled.")
        return None
    try:
        idx = int(raw) - 1
        if not (0 <= idx < len(all_tests)):
            print(f"wizard: invalid selection '{raw}'.")
            return None
    except ValueError:
        print(f"wizard: invalid selection '{raw}'.")
        return None

    test_cls = all_tests[idx]
    test_id = test_cls.id
    hidden = _WIZARD_HIDDEN.get(test_id, set())
    uses_loss = test_id in _WIZARD_USES_LOSS

    print(f"\n--- {test_id} parameters (Enter = keep default) ---")
    from .test_items.base import coerce as _coerce

    collected: dict = {}
    for p in test_cls.params:
        if p.name in hidden:
            continue
        if p.name in ("in_loss_db", "out_loss_db"):
            continue  # handled in loss override block below
        unit_str = f" {p.unit}" if p.unit else ""
        label_str = p.help or p.label
        prompt = f"  {p.name:<22} [{p.default}{unit_str}]  {label_str} : "
        raw_val = input(prompt).strip()
        if raw_val:
            try:
                collected[p.name] = _coerce(p, raw_val)
            except (ValueError, TypeError) as exc:
                print(f"    Bad value '{raw_val}': {exc}. Using default {p.default!r}.")

    # 손실 자동 적용 테스트: override 제공
    if uses_loss:
        print(f"\n  in_loss / out_loss: auto from loss.toml")
        override = input("  Override? enter 'in out' dB values, or n/Enter to skip: ").strip().lower()
        if override and override not in ("n", "no", ""):
            parts = override.replace(",", " ").split()
            if len(parts) == 2:
                try:
                    collected["in_loss_db"] = float(parts[0])
                    collected["out_loss_db"] = float(parts[1])
                    print(f"  -> in_loss={collected['in_loss_db']} "
                          f"out_loss={collected['out_loss_db']} dB (manual)")
                except ValueError:
                    print("  Could not parse. Using auto loss.")
            else:
                print("  Expected two values (e.g. '2.5 15.0'). Using auto loss.")

    # 실행 요약 + 확인
    key_items = [f"{k}={v}" for k, v in list(collected.items())[:4]
                 if k not in ("in_loss_db", "out_loss_db")]
    freq_hz = collected.get("freq_hz", test_cls.defaults().get("freq_hz"))
    freq_str = f"{freq_hz / 1e9:.3f} GHz" if freq_hz else ""

    print(f"\n=== Ready to run ===")
    print(f"  Test   : {test_cls.title}")
    if freq_str:
        print(f"  Freq   : {freq_str}")
    if key_items:
        print(f"  Params : {'  '.join(key_items)}")
    if uses_loss:
        if "in_loss_db" in collected:
            print(f"  Loss   : in={collected['in_loss_db']} "
                  f"out={collected['out_loss_db']} dB (manual)")
        else:
            print("  Loss   : auto (loss.toml)")
    print()

    confirm = input("Run now? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("wizard: cancelled.")
        return None

    fn = _ns.get(test_id)
    if fn is None:
        print(f"wizard: '{test_id}' not found in session namespace.")
        return None
    return fn(**collected)
```

- [ ] **Step 5: Wire `wizard` into `_ns` in `start()` and add to `_HELP["info"]`**

In `start()`, find the `_ns.update({...})` block and add `"wizard": wizard` to it:

```python
    _ns.update({
        "B": B, "C": C,
        "op1db": op1db, "gain_index_accuracy": gain_index_accuracy,
        "channel_gain_alignment": channel_gain_alignment,
        "evm": evm, "acp": acp,
        "params": params, "tests": tests,
        "loss": loss, "peakc": peakc,
        "status": status, "help": help, "start": start,
        "restart": restart, "shutdown": shutdown,
        "wizard": wizard,                          # <-- add this line
    })
```

In `_HELP["info"]`, add wizard entry:

```python
    "info": [
        ("status()", "current channel / gain / SG state"),
        ("help() / help('rf')", "this list / detail of one command"),
        ("wizard()", "guided step-by-step measurement"),   # <-- add
    ],
```

- [ ] **Step 6: Run wizard tests to confirm they pass**

```
python -m pytest tests/test_session_ux.py::test_wizard_op1db_fake tests/test_session_ux.py::test_wizard_quit tests/test_session_ux.py::test_wizard_cancel_at_confirm -v
```

Expected: all PASS.

- [ ] **Step 7: Run full test suite**

```
python -m pytest -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```
git add src/cloudchaser/session.py tests/test_session_ux.py
git commit -m "feat: add wizard() guided measurement + wire into session namespace"
```

---

## Post-Implementation: Push to remote and merge

- [ ] Push branch and merge to main per project workflow:

```
git push origin HEAD
git checkout main && git merge <branch> && git push origin main
```

---

## Self-Review

**Spec coverage check:**
- ✅ `wizard()` with step-by-step prompts → Task 3
- ✅ Parameter visibility (hidden vs shown) → `_WIZARD_HIDDEN` in Task 3 Step 3
- ✅ Loss auto-apply with override option → Task 3 Step 4 (loss override block)
- ✅ `channel_gain_alignment` special case (no loss prompt, interactive itself) → `_WIZARD_HIDDEN` hides its in/out_loss params; wizard just passes `channel_mode` and calls session fn
- ✅ Enhanced `help()` — 3-line per test → Task 1 Step 3
- ✅ `help('op1db')` shows param table → Task 1 Step 3 (help detail section)
- ✅ `start()` banner improvement → Task 2
- ✅ `wizard` wired into `_ns` → Task 3 Step 5
- ✅ Tests for all three features → Tasks 1/2/3

**Placeholder scan:** No TBD/TODO in task steps. All code is complete.

**Type consistency:**
- `wizard()` returns `TestResult | None` — `_run_test()` returns `TestResult`, consistent.
- `_WIZARD_HIDDEN` is `dict[str, set]`, accessed with `.get(test_id, set())` — consistent.
- `_ns.get(test_id)` returns the session function — same pattern used in `help(topic)`.
- `coerce` imported as `_coerce` inside `wizard()` — avoids shadowing, consistent with one-time use.
