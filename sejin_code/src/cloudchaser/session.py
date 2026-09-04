"""IPython 인터랙티브 세션 — 모듈처럼 불러와 자유롭게 제어/측정/디버깅.

목적: cmd 에서 매번 길게 명령을 치는 대신, IPython 안에서 한 번 start() 하면
연결+전원+보드 bring-up 을 하고, 모든 명령어(chan/rf/peak/op1db 등)를 IPython
네임스페이스에 '자동 주입'한다. 그 뒤로는 그냥 함수처럼 부르면 된다.

전형적 흐름(IPython 안에서):
    from cloudchaser.session import start
    start(channels=['h1'])                 # 연결+전원+bring-up, 명령어 주입
    help()                                 # 쓸 수 있는 명령 한눈에
    rf(True, freq=28e9, level=-10)          # SG 설정+RF ON
    saconf(center=28e9, ref=20); peak()     # SA 보고 피크 측정
    vi()                                   # 전원 V/I
    op1db(gain_code=0)                      # OP1dB 측정(경로손실은 SG/SA 오프셋에 자동 적용)
    help('op1db')                          # 특정 명령 상세
    status()                               # 현재 상태(채널/게인/SG)
    shutdown()                             # 끝나면 전원 0V

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import atexit
import inspect
from pathlib import Path

from pathlib import Path

from .bench import Bench
from .board.bringup import (
    VERSION_ID_OK,
    VERSION_ID_OK_RX,
    bring_up_rx,
    bring_up_tx,
    make_chip,
    make_chip_rx,
)
from .board.firehawk import FH
from .board.gain_map import get_gain
from .loss import get_loss, loss_table
from .manual import build_namespace
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout
from .test_items import TestContext, get_test, list_tests

# bench_rx.toml 기본 경로: 이 파일 기준으로 repo 루트의 config/bench_rx.toml
DEFAULT_CONFIG_RX = Path(__file__).resolve().parents[2] / "config" / "bench_rx.toml"

# wizard: 프롬프트에서 숨길 파라미터(기본값으로 자동 사용)
_WIZARD_HIDDEN: dict[str, set] = {
    "op1db": {
        # sa_ref_level_dbm 은 일부러 숨기지 않는다 -- 압축점 측정에서 ref level 을
        # 잘못 잡으면 스윕 상단이 잘려 OP1dB 가 틀리는데, 그걸 조용히 기본값으로
        # 넘기면 벤치에서 매번 손으로 다시 잡게 된다.
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "settle_s", "gain_target", "beam", "channel",
        "pin_step_db",
    },
    "gain_index_accuracy": {
        "common_target", "channel_target", "channel", "common_codes",
        "channel_codes", "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "channel_gain_alignment": {
        "max_gain_code", "beam", "common_target", "channels",
        "sa_span_hz", "sa_ref_level_dbm", "settle_s",
    },
    "evm": {
        "pin_step_db", "bw_mhz", "auto_evm_each", "settle_s", "sa_follow_center",
    },
    "acp": {
        "pin_step_db", "bw_mhz", "chan_bw_hz", "spacing_hz", "n_adj", "settle_s",
    },
    "ip1db": {
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "sa_ref_level_dbm", "settle_s", "gain_target", "beam", "channel",
        "pin_step_db",
    },
    "vdd_sensitivity": {
        # op1db 와 같은 항목을 숨기되, sa_ref_level_dbm 과 vdd_list_v 는 반드시 묻는다
        # (ref level 을 잘못 잡으면 압축점이 틀리고, 전압 계단은 이 테스트의 본체다).
        "ref_skip_pts", "ref_avg_pts", "sa_span_hz",
        "settle_s", "gain_target", "beam", "channel",
        "pin_step_db", "vdd_rail", "vdd_settle_s",
    },
}

# 경로 손실이 자동 적용되는 테스트(wizard 가 'Loss: auto' 안내 표시)
_WIZARD_USES_LOSS: frozenset = frozenset(
    {"op1db", "gain_index_accuracy", "channel_gain_alignment", "evm", "acp", "ip1db",
     "vdd_sensitivity"})

# 세션 전역 상태 — start() 가 채운다.
B = None        # Bench (계측기)
C = None        # bring-up 된 chip
_ns: dict = {}  # 주입된 명령어 묶음
_fake = False
_chip_kind = "tx"            # 'tx' (Stampede) or 'rx' (Blueway)
_powered = False             # 전원이 인가됐는지(자동 차단 여부 판단)
_atexit_armed = False        # 종료 시 자동 차단을 한 번만 등록하기 위한 플래그


def _atexit_powerdown():
    """IPython/프로세스 종료 시, 전원이 켜져 있으면 역순으로 안전하게 내린다.

    사용자가 shutdown() 을 깜빡하고 exit() 해도 PSU 가 켜진 채 방치되지 않게 한다.
    (이미 shutdown() 으로 내렸으면 레일이 0V 라 추가 동작은 무해하게 끝난다.)
    """
    global _powered
    if B is None or not _powered or _fake:
        return
    try:
        print("\n[session] exit detected -> safe power-down (reverse sequence)...")
        try:
            B.sg.rf_output(False)
        except Exception:
            pass
        B.power_down()          # power_up_order 의 역순(FE1_4V0/PA 먼저)
        B.close_all()
        _powered = False
        print("[session] rails ramped to 0 V.")
    except Exception as e:
        print(f"[session] auto power-down failed: {e}")


# ----------------------------------------------------------------------
# 세션 시작/재시작/종료
# ----------------------------------------------------------------------
# auto 감지 시 1단계 연결/감지에 쓰는 기준(donor) config 종류.
# 감지 레일(detect=true)은 TX/RX 전압이 동일하므로 어느 쪽을 써도 안전하다.
# 현재 활성 작업이 RX 라 'rx' 로 두어, RX 보드일 때 bench/chip 재구성 없이 happy path 로 간다.
_DETECT_DONOR = "rx"


def _version_kind(ver: int) -> str | None:
    """version_id 값을 보드 종류로 매핑한다(인식 불가면 None)."""
    if ver == VERSION_ID_OK:
        return "tx"
    if ver == VERSION_ID_OK_RX:
        return "rx"
    return None


def _kind_label(kind: str) -> str:
    return "RX (Blueway)" if kind == "rx" else "TX (Stampede)"


def _confirm_detected(kind: str, ver: int) -> bool:
    """auto 모드: 감지 결과를 사용자에게 확인받는다(y 면 진행)."""
    print(f"[detect] version_id = {hex(ver)} -> board detected as {_kind_label(kind)}.")
    try:
        ans = input(f"        Proceed to power up as {_kind_label(kind)}? [y/N]: ")
    except EOFError:
        ans = ""
    return ans.strip().lower() in ("y", "yes")


def _confirm_mismatch(requested: str, detected: str, ver: int) -> bool:
    """명시(tx/rx) 모드인데 실제 칩이 다를 때: 경고 + 일시정지. y 면 강제 진행."""
    print("")
    print("  !! BOARD MISMATCH ------------------------------------------------")
    print(f"  !! Requested {_kind_label(requested)}, but version_id={hex(ver)} "
          f"-> {_kind_label(detected)}.")
    print("  !! FE rails are NOT powered yet. Forcing the requested profile onto")
    print("  !! the wrong board can DAMAGE it (e.g. 4.0V onto a 1.0V LNA rail).")
    print("  !! ----------------------------------------------------------------")
    try:
        ans = input(f"        Override and force {_kind_label(requested)} anyway? [y/N]: ")
    except EOFError:
        ans = ""
    return ans.strip().lower() in ("y", "yes")


def _apply_board_overrides(channels, beam) -> None:
    """channels/beam 사용자 지정값을 현재 B.board 에 반영한다."""
    if channels:
        B.board.active_channels = [c.strip().lower() for c in channels]
    if beam:
        B.board.beam = beam


def start(channels=None, *, chip="auto", power=True, fake=False,
          config=None, beam=None):
    """Connect instruments, auto-detect TX/RX, ramp power, bring up board, inject commands.

    channels : list of channels to enable (e.g. ['h1']). Defaults to bench.toml value.
    chip     : 'auto' (default) detects the board from version_id and asks you to
               confirm; 'tx'/'rx' force a profile but still VALIDATE against the chip
               and pause on mismatch. Wrong-board protection: only the SPI rails
               (same voltage on TX & RX) are powered before the chip is identified;
               FE rails are powered only after the board type is confirmed.
    power    : True = staged PSU ramp-up (real hardware). False = connect + bring-up
               only (no auto-detect; uses 'tx'/'rx' as given, 'auto' falls back to the
               donor profile).
    fake     : run without hardware (dry-run mode; no detection, uses chip or 'tx').
    config   : explicit path to a bench.toml (overrides auto-selection).
    """
    global B, C, _ns, _fake, _chip_kind, _powered, _atexit_armed
    _force_utf8_stdout()
    _fake = fake
    req = str(chip).lower()
    if req not in ("auto", "tx", "rx"):
        raise ValueError(f"chip must be 'auto', 'tx', or 'rx', got '{chip}'")

    # ---- fake 모드: 하드웨어 감지 불가 -> 요청값(auto 면 tx)으로 단상 진행 ----
    if fake:
        kind = "tx" if req in ("auto", "tx") else req
        cfg = config or (DEFAULT_CONFIG_RX if kind == "rx" else DEFAULT_CONFIG)
        B = Bench.from_toml(cfg, fake=True)
        B.connect_all()
        _apply_board_overrides(channels, beam)
        if power:
            B.power_up()
        C = (make_chip_rx if kind == "rx" else make_chip)(B.board, fake=True)
        (bring_up_rx if kind == "rx" else bring_up_tx)(C, B.board, require_version=False)
        return _finalize(kind, fake, power)

    # ---- power=False: 전원 시퀀스가 없으면 감지 단계도 없음(고급/외부전원 케이스) ----
    if not power:
        kind = req if req in ("tx", "rx") else _DETECT_DONOR
        cfg = config or (DEFAULT_CONFIG_RX if kind == "rx" else DEFAULT_CONFIG)
        B = Bench.from_toml(cfg, fake=False)
        B.connect_all()
        _apply_board_overrides(channels, beam)
        C = (make_chip_rx if kind == "rx" else make_chip)(B.board, fake=False)
        (bring_up_rx if kind == "rx" else bring_up_tx)(C, B.board, require_version=True)
        return _finalize(kind, fake, power)

    # ---- 실제 하드웨어 2단계: (1) 감지 레일만 전원 -> (2) version 확인 -> (3) 나머지 ----
    donor_kind = req if req in ("tx", "rx") else _DETECT_DONOR
    donor_cfg = config or (DEFAULT_CONFIG_RX if donor_kind == "rx" else DEFAULT_CONFIG)
    B = Bench.from_toml(donor_cfg, fake=False)
    B.connect_all()
    _apply_board_overrides(channels, beam)

    # 보드 종류를 사용자가 명시했고(chip='tx'/'rx') toml 에 벤더 스테이지가 선언돼
    # 있으면, 데이터시트 시퀀스를 그대로 따른다: 마지막 스테이지(PA)만 남기고 전부
    # 올린 뒤 SPI 로 칩을 확인하고 마지막에 PA 를 인가한다. 다이어그램이 'SPI active'
    # 로 표시한 바로 그 지점에서 확인하는 셈이다.
    # chip='auto' 이거나 스테이지가 없는 config 는 기존 2단계 감지 경로를 쓴다 --
    # FE 레일 전압이 TX/RX 에서 다르므로 보드가 확정되기 전엔 올릴 수 없다.
    strict = req in ("tx", "rx") and B.staged

    if strict:
        pre = [n for s in B.power_up_stages[:-1] for n in s]
        last_stage = list(B.power_up_stages[-1])
        print(f"[power ] strict sequence (chip='{req}' given): "
              f"{', '.join(pre)} -> SPI check -> {', '.join(last_stage)}")
        print(f"[warn  ] FE rails are energised at {req.upper()} voltages before the "
              f"SPI check -- make sure the board on the bench really is {req.upper()}")
        B.power_up(rails=pre)
    else:
        # 1단계: 감지 레일(detect=true)만 켠다. FE 레일은 아직 OFF.
        #   detect_stage=True 라 detect_v 가 있는 레일(TX VDD_IO)은 TX/RX 공용 안전
        #   전압(1.3V)까지만 올라간다 -- 보드 종류가 확정되기 전에는 어느 쪽 보드가
        #   붙어 있어도 과전압이 되지 않아야 한다. 확정 후 5단계에서 승압한다.
        B.power_up(rails=B.detect_rail_names, detect_stage=True)
    _powered = True
    if not _atexit_armed:
        atexit.register(_atexit_powerdown)
        _atexit_armed = True

    # 2단계: version_id 를 init()/eFuse 없이 라이브 읽기.
    #   단, SPI 엔진 리셋(spi.reset)은 먼저 해야 한다 — 이게 없으면 갓 켠 칩에서
    #   읽기가 0x0 으로 나온다(실측). spi.reset() 은 chip.init() 의 첫 단계와 동일한
    #   FTDI/SPI 엔진 리셋일 뿐, eFuse 적용도 칩 레지스터 쓰기도 아니라 안전하다.
    # TODO(RESET_N): 데이터시트 Stampede 6.3 은 HW RESET_N 핀을 '1.8V 레일 인가 후 ·
    #   FE1(4V) 인가 전'에 해제하도록 규정한다. 현재 코드엔 HW RESET_N 제어가 없고
    #   spi.reset()(SPI 엔진 리셋, detect 레일 후·FE 레일 전 위치라 시점은 부합) +
    #   bring-up 의 chip.init()(전 레일 인가 후) 로 대체한다. EVB 에서 RESET_N 을
    #   우리가 제어 가능한지(POR 자동인지) 미확인 — 확인되면 이 위치에 핀 제어 추가.
    C = (make_chip_rx if donor_kind == "rx" else make_chip)(B.board, fake=False)
    C.spi.reset()
    ver = int(C.fields.rd("version_id"))
    detected = _version_kind(ver)
    if detected is None:
        raise RuntimeError(
            f"version_id {hex(ver)} unrecognized (expected TX {hex(VERSION_ID_OK)} or "
            f"RX {hex(VERSION_ID_OK_RX)}). PA rail NOT powered. Check SPI link / board.")

    # 3단계: auto 면 확인받고, 명시면 검증 후 불일치 시 경고+일시정지.
    if req == "auto":
        if not _confirm_detected(detected, ver):
            raise RuntimeError("Aborted by user after auto-detect. FE rails NOT powered.")
        kind = detected
    elif detected != req:
        # strict 경로에서는 1.8V 군이 이미 인가된 상태라 'PA 만 아직'이라고 알린다.
        held = "PA rail NOT powered" if strict else "FE rails NOT powered"
        if not _confirm_mismatch(req, detected, ver):
            raise RuntimeError(
                f"Board mismatch (requested {req}, detected {detected}). "
                f"{held}. Aborted.")
        kind = req  # 사용자 강제 override
    else:
        kind = req

    # strict 경로: 스테이지가 하나 남았다 -> PA(FE1 4V) 인가하고 bring-up 으로.
    if strict:
        B.power_up(rails=last_stage)
        (bring_up_rx if kind == "rx" else bring_up_tx)(C, B.board, require_version=True)
        return _finalize(kind, fake, power)

    # 4단계: donor 와 종류가 다르면 올바른 config 로 bench/chip 재구성.
    #         close_all 은 소켓만 닫고 전원 출력은 유지하므로 감지 레일은 켜진 채 남는다.
    if kind != donor_kind:
        try:
            C.spi.close()
        except Exception:
            pass
        B.close_all()
        final_cfg = config or (DEFAULT_CONFIG_RX if kind == "rx" else DEFAULT_CONFIG)
        B = Bench.from_toml(final_cfg, fake=False)
        B.connect_all()
        _apply_board_overrides(channels, beam)
        C = (make_chip_rx if kind == "rx" else make_chip)(B.board, fake=False)

    # 5단계: 나머지(비-감지) 레일 + detect_v 로 낮게 걸어둔 감지 레일을 켠다
    #         -> FE 를 확정된 보드 전압으로 안전 인가하고, VDD_IO 를 1.3V -> 1.8V 로
    #         승압한다. 이미 목표 전압인 레일은 _ramp_stage_up 이 건너뛰므로 글리치가
    #         없다. 단 bench 를 재구성한 경우(kind != donor_kind)에는 PSU 의 전압
    #         추적값이 0 으로 초기화돼 승압이 0V 부터 다시 시작되므로 제외한다
    #         (재구성 = 다른 보드 = detect_v 승압 대상이 아님).
    detect_names = set(B.detect_rail_names)
    if kind == donor_kind:
        topup = {n for n in detect_names
                 if B.rail(n).detect_v is not None
                 and B.rail(n).detect_v < B.rail(n).v_target}
    else:
        topup = set()
    remaining = [n for n in B.power_up_order
                 if n not in detect_names or n in topup]
    B.power_up(rails=remaining)

    # 6단계: bring-up(여기서 init/eFuse + version 재확인까지 수행).
    (bring_up_rx if kind == "rx" else bring_up_tx)(C, B.board, require_version=True)
    return _finalize(kind, fake, power)


def _finalize(kind: str, fake: bool, power: bool):
    """네임스페이스 구성 + IPython 주입 + 안내 출력. start() 의 공통 마무리."""
    global _ns, _chip_kind
    _chip_kind = kind
    B.chip_kind = kind          # bring-up/chip 식별용 (loss 매핑엔 더 이상 안 쓰임)
    bm = B.board.beam

    # manual 의 헬퍼 묶음 + 세션 전용(측정/정보) 함수를 합쳐 네임스페이스 구성.
    _ns = build_namespace(B, C, bm)
    _ns.update({
        "B": B, "C": C,
        "op1db": op1db, "gain_index_accuracy": gain_index_accuracy,
        "gain_index_accuracy_common": gain_index_accuracy_common,
        "gain_index_accuracy_channel": gain_index_accuracy_channel,
        "evm_rx": evm_rx,
        "channel_gain_alignment": channel_gain_alignment,
        "evm": evm, "acp": acp,
        "ip1db": ip1db, "phase_index_accuracy": phase_index_accuracy,
        "rx_suite": rx_suite, "tx_suite": tx_suite,
        "vdd_sensitivity": vdd_sensitivity,
        "params": params, "tests": tests,
        "loss": loss, "set_loss": set_loss, "peakc": peakc,
        "find_bias": find_bias,
        "split": split,
        "status": status, "help": help, "start": start,
        "restart": restart, "shutdown": shutdown,
        "wizard": wizard,
    })
    _inject(_ns)
    print(f"[session] ready: chip={kind}  channels={B.board.active_channels}"
          f"  beam={bm}  fake={fake}  power={power}")
    print()
    print("  wizard()   <- step-by-step guided measurement  (start here)")
    print("  help()     <- full command reference")
    print("  status()   <- current channel / gain / SG state")
    print()
    if kind == "rx":
        print("  Typical flows (RX / Blueway):")
        print("    Signal check : rf(True, freq=19.5e9, level=-30) -> peak()")
        print("    IP1dB        : ip1db(freq_hz=19.5e9)")
        print()
        print("  NOTE: SG -> channel port (antenna input), SA -> beam port (output)")
    else:
        print("  Typical flows (TX / Stampede):")
        print("    Signal check : rf(True, freq=28e9, level=-10) -> peak()")
        print("    OP1dB        : op1db(freq_hz=28e9)")
        print("    Chan align   : channel_gain_alignment(channel_mode='all')")
    print()
    return _ns


def _inject(ns: dict) -> None:
    """명령어를 IPython 사용자 네임스페이스에 직접 주입한다.

    IPython 안이면 get_ipython().user_ns 에 넣어 바로 chan()/rf() 등을 쓸 수 있게
    한다. 일반 파이썬이면 이 모듈 전역에 넣는다(from session import * 로 접근).
    """
    try:
        ip = get_ipython()  # type: ignore[name-defined]  # IPython 이 주입하는 전역
        ip.user_ns.update(ns)
        print("[session] commands injected into IPython namespace.")
    except NameError:
        globals().update(ns)


def restart(**kw):
    """Close the current session and call start() again with the given arguments."""
    global B
    if B is not None:
        try:
            B.close_all()
        except Exception:
            pass
    return start(**kw)


def shutdown():
    """Ramp all rails to 0 V in reverse power-up order (RF off first).

    Reverses power_up_order, so the PA 4V rail ramps down first.
    Call at end of session. Also runs automatically on exit().
    """
    global _powered
    if B is None:
        print("not started.")
        return
    try:
        B.sg.rf_output(False)
    except Exception:
        pass
    B.power_down()
    _powered = False
    print("[session] power-down complete (rails ramped to 0 V, reverse sequence).")


# ----------------------------------------------------------------------
# 측정(현재 세션의 계측기/보드를 그대로 사용 — 재연결 안 함)
# ----------------------------------------------------------------------
def op1db(**kw):
    """OP1dB measurement (TX). Path loss is auto-applied to the SG/SA offsets
    (from Loss_data CSVs) inside the run, so SG level = chip input, SA read = chip output.
    e.g. op1db(freq_hz=28e9, gain_code=0).  Parameters: params('op1db'). CSV saved to out/."""
    return _run_test("op1db", kw)


def vdd_sensitivity(**kw):
    """VDD sensitivity (TX): repeat the OP1dB sweep at each FE1 supply voltage.
    Default steps 4.0 / 3.6 / 3.3 / 3.0 / 2.7 / 2.4 / 2.2 V; the chip is NOT re-brought-up
    between them, and the rail is always ramped back to its nominal 4.0 V at the end.
    e.g. vdd_sensitivity(freq_hz=28e9, vdd_list_v=[4.0, 3.0, 2.2]).
    Parameters: params('vdd_sensitivity'). One CSV (VDD_set_V column) saved to out/."""
    return _run_test("vdd_sensitivity", kw)


def gain_index_accuracy(**kw):
    """Gain index accuracy: SG fixed, sweep common/per-path (beam-table attenuator) gain codes.
    e.g. gain_index_accuracy(sg_level_dbm=0, channel_target='beamtable', channel_quad=1)
         gain_index_accuracy(channel_codes=[0])  # common sweep only
         gain_index_accuracy(..., log_psu=False) # skip PSU reads (faster, avoids timeouts)
    RX: direct call does NOT apply rx_default -> pass freq_hz/sg_level_dbm/sa_ref_level_dbm.
    Path loss auto-applied to SG/SA offsets. Parameters: params('gain_index_accuracy'). CSV saved."""
    return _run_test("gain_index_accuracy", kw)


# RX Gain Accuracy 공통 기본값 (gain_index_accuracy_common/channel + rx_suite 공유).
# sg_level: max gain 에서 IP1dB(~-37 dBm) 보다 충분히 낮은 선형 구간(-45 -> 압축 <0.1 dB).
_RX_GAIN_SG_DBM = -45.0
_RX_GAIN_SA_REF_DBM = 10.0

# TX Gain Accuracy 공통 기본값 (tx_suite 공유). gain_index_accuracy TX item 기본값과 동일.
# 압축이 보이면 스텝 override 로 낮출 것: tx_suite('h1', gain_common={'sg_level_dbm': -10}).
_TX_GAIN_SG_DBM = 0.0
_TX_GAIN_SA_REF_DBM = 20.0


def gain_index_accuracy_common(freq_hz=19.5e9, sg_level_dbm=_RX_GAIN_SG_DBM, **kw):
    """RX Gain Accuracy - COMMON axis. Sweep common gain 0..63 with the channel
    beam-table attenuator held at max gain (0). SG fixed in the linear region. CSV tagged '_common_'.
    RX defaults baked in (19.5 GHz, -45 dBm, log_psu off). Override via kwargs,
    e.g. gain_index_accuracy_common(freq_hz=21e9, sg_level_dbm=-48)."""
    params = {"freq_hz": freq_hz, "sg_level_dbm": sg_level_dbm,
              "sa_ref_level_dbm": _RX_GAIN_SA_REF_DBM,
              "common_codes": list(range(64)), "channel_codes": [0],
              "channel_target": "beamtable", "log_psu": False}
    params.update(kw)
    return _run_test("gain_index_accuracy", params)


def gain_index_accuracy_channel(freq_hz=19.5e9, sg_level_dbm=_RX_GAIN_SG_DBM, **kw):
    """RX Gain Accuracy - CHANNEL axis (beam-table attenuator_setting). Sweep per-path gain
    0..63 with the common gain held at max. SG fixed in the linear region. CSV
    tagged '_chan_'. RX defaults baked in (19.5 GHz, -45 dBm, log_psu off).
    channel_quad auto-derives from the active channel (h0->0, h1->1, ...)."""
    params = {"freq_hz": freq_hz, "sg_level_dbm": sg_level_dbm,
              "sa_ref_level_dbm": _RX_GAIN_SA_REF_DBM,
              "common_codes": [0], "channel_codes": list(range(64)),
              "channel_target": "beamtable", "log_psu": False}
    params.update(kw)
    return _run_test("gain_index_accuracy", params)


def evm_rx(waveform_path="", freq_hz=19.5e9, pin_start_dbm=-75.0, pin_stop_dbm=-45.0,
           pin_step_db=1.0, setup_sa=False, modulation=None, **kw):
    """RX EVM bathtub: sweep input power and measure EVM vs power.

    Waveform handling (auto):
      - evm_rx()                  -> modulation='manual': use the waveform you
        already loaded on the SMW (and the FSVA NR app you set up by hand).
      - evm_rx('/var/user/nr.wv') -> modulation='load': the code loads that .wv
        on the SMW first.
    Override with modulation=... explicitly. The FSVA NR analyzer is assumed
    pre-configured (setup_sa=False); pass setup_sa=True to let the code set it (DL).
    RX defaults baked in (19.5 GHz, -70..-35 dBm, 1 dB step)."""
    if modulation is None:
        modulation = "load" if waveform_path else "manual"
    params = {"freq_hz": freq_hz, "modulation": modulation,
              "waveform_path": waveform_path, "setup_sa": setup_sa,
              "pin_start_dbm": pin_start_dbm, "pin_stop_dbm": pin_stop_dbm,
              "pin_step_db": pin_step_db}
    params.update(kw)
    return _run_test("evm", params)


def channel_gain_alignment(**kw):
    """Channel Gain Alignment: fix max gain, record output power per channel, check spread.
    Interactive: enter channel -> move SA cable -> 'y' measure / 'n' stop -> CSV saved.
    e.g. channel_gain_alignment(channel_mode='all')     # all channels ON, move cable
         channel_gain_alignment(channel_mode='single')  # switch channel per measurement
         channel_gain_alignment(channels_script='h0,h1,v0')  # non-interactive (auto)
    Path loss auto-applied per channel (SA offset updated per channel). PSU V/I also recorded.
    Parameters: params('channel_gain_alignment')."""
    return _run_test("channel_gain_alignment", kw)


def evm(**kw):
    """EVM (5G NR) vs output power. modulation='setup'(default)/'load'/'manual'.
    e.g. evm(freq_hz=28e9),  evm(modulation='load', waveform_path='...')
    Parameters: params('evm'). Path loss auto-applied to the SA offset. CSV saved."""
    return _run_test("evm", kw)


def acp(**kw):
    """ACP (adjacent channel power ratio) vs output power. modulation='setup'(default)/'load'/'manual'.
    Parameters: params('acp'). Path loss auto-applied to the SA offset. CSV saved."""
    return _run_test("acp", kw)


def ip1db(**kw):
    """IP1dB measurement (RX / Blueway). Path loss auto-applied (Loss_data CSVs) to SG/SA offsets.
    RX signal flow: SG -> channel port (antenna input) -> IC -> beam port -> SA.
    Example: ip1db(freq_hz=19.5e9, gain_code=0)
    Parameters: params('ip1db'). Results saved to out/ as CSV."""
    return _run_test("ip1db", kw)


def phase_index_accuracy(**kw):
    """Phase index accuracy: sweep beam-table RTPS phase codes (7-bit, 0..127)
    and read S21 gain/phase from the Anritsu MS4644B VNA per code.
    SETUP: cable VNA port1 -> DUT -> port2 and CALIBRATE THE VNA MANUALLY first --
    the code never presets it (configure_freq=False keeps your sweep setup).
    Path loss is NOT applied (the VNA user cal de-embeds cables). Not part of
    tx_suite/rx_suite (different cabling). Raw data only, no pass/fail.
    e.g. phase_index_accuracy()                               # all 128 codes, marker
         phase_index_accuracy(phase_codes=list(range(0,128,8)), read_mode='trace')
         phase_index_accuracy(read_mode='point', freq_step_hz=250e6)
    RX: direct call ignores rx_default -> pass freq_start_hz/freq_stop_hz (or
    marker_freq_hz) for the 19.5 GHz band.
    Parameters: params('phase_index_accuracy'). CSV saved to out/."""
    return _run_test("phase_index_accuracy", kw)


def rx_suite(channel="h0", freq_hz=19.5e9, beam=None, waveform_path="", **overrides):
    """Run the RX measurement suite for ONE channel and save a CSV per step.

    Steps (each saves its own CSV; a failing step is skipped, others continue):
      1. linearity    = ip1db   (max gain CW Pin sweep; also covers Total PDC)
      2. gain_common  = gain_index_accuracy (sweep common, channel held at max gain)
      3. gain_chan    = gain_index_accuracy (sweep channel beam-table attenuator, common at max gain)
      4. evm          = evm     (load waveform, EVM vs input power)
    Total PDC is derived later from the linearity CSV. Override a step's params
    with overrides[label], e.g. rx_suite('h0', linearity={'pin_stop_dbm': -8}).
    Move the SG cable to the channel's port and change the channel arg per channel.
    """
    if C is None:
        print("not started. call start(channels=['h0'], chip='rx') first.")
        return None
    chan_fn = _ns.get("chan")
    if chan_fn is None:
        print("rx_suite: 'chan' not available in session namespace.")
        return None
    # beam 미지정이면 현재 보드 beam 유지(b0 로 되돌리지 않음).
    bm = beam if beam is not None else getattr(B.board, "beam", "b0")
    chan_fn(channel, bm)
    steps = [
        ("linearity", "ip1db",
         {"freq_hz": freq_hz, "gain_code": 0, "pin_start_dbm": -50.0,
          "pin_stop_dbm": -20.0, "pin_step_db": 1.0}),
        ("gain_common", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _RX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _RX_GAIN_SA_REF_DBM,
          "common_codes": list(range(64)), "channel_codes": [0],
          "channel_target": "beamtable", "log_psu": False}),
        ("gain_chan", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _RX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _RX_GAIN_SA_REF_DBM,
          "common_codes": [0], "channel_codes": list(range(64)),
          "channel_target": "beamtable", "log_psu": False}),
        ("evm", "evm",
         {"freq_hz": freq_hz,
          "modulation": "load" if waveform_path else "manual",
          "waveform_path": waveform_path, "setup_sa": False,
          "pin_start_dbm": -75.0, "pin_stop_dbm": -45.0, "pin_step_db": 1.0}),
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


def _parse_freqs(freqs, fallback: float) -> list[float]:
    """'28e9,29e9' / [28e9, 29e9] / 28e9 / None -> 주파수 리스트[Hz]."""
    if freqs is None or freqs == "":
        return [float(fallback)]
    if isinstance(freqs, (int, float)):
        return [float(freqs)]
    if isinstance(freqs, str):
        return [float(x.strip()) for x in freqs.split(",") if x.strip()]
    return [float(x) for x in freqs]


def _parse_steps(steps, kind: str) -> list[str]:
    """'vdd_sensitivity,evm' / ['vdd_sensitivity','evm'] / '7,4'(메뉴 번호) -> test id 목록.

    번호는 그 칩에서 쓸 수 있는 테스트 목록(wizard 와 같은 순서) 기준이다.
    """
    avail = [t.id for t in list_tests() if kind in getattr(t, "chips", ("tx", "rx"))]
    raw = ([x.strip() for x in steps.split(",")] if isinstance(steps, str)
           else [str(x).strip() for x in steps])
    out: list[str] = []
    for tok in raw:
        if not tok:
            continue
        if tok.isdigit():
            i = int(tok) - 1
            if not (0 <= i < len(avail)):
                raise ValueError(f"step '{tok}' is out of range 1..{len(avail)}")
            out.append(avail[i])
        elif tok in avail:
            out.append(tok)
        else:
            raise ValueError(f"unknown test '{tok}' for {kind}. available: {avail}")
    if not out:
        raise ValueError("no test selected")
    return out


def _freqs_for(test_id: str, freqs: list[float]) -> list:
    """그 항목이 freq_hz 를 받으면 전 주파수, 아니면 [None](주파수 확장 없이 1회)."""
    names = {p.name for p in get_test(test_id).params}
    return list(freqs) if "freq_hz" in names else [None]


def _suite_build(kind: str):
    """대화형 suite 빌더. (channel, beam, freqs, [(test_id, params), ...]) 또는 None.

    항목 선택 -> 채널/빔 -> 주파수 목록 -> 항목별 파라미터(wizard 와 같은 프롬프트).
    freq_hz 만 앞에서 목록으로 한 번 받고 항목별 프롬프트에서는 빼는데, suite 는
    같은 주파수 집합을 전 항목에 적용하기 때문이다(항목마다 다르게 주려면 비대화형
    호출에서 overrides 로 준다).
    """
    rx = (kind == "rx")
    avail = [t for t in list_tests() if kind in getattr(t, "chips", ("tx", "rx"))]
    print(f"=== {kind.upper()} Suite Builder ===")
    print("Available tests:")
    for i, t in enumerate(avail, 1):
        print(f"  {i}. {t.id:<24} {(t.description or t.title)[:52]}")
    print("  q. quit")
    raw = input("Select tests in run order (e.g. 7,4) : ").strip().lower()
    if raw in ("", "q", "quit"):
        print("suite: cancelled.")
        return None
    try:
        test_ids = _parse_steps(raw, kind)
    except ValueError as exc:
        print(f"suite: {exc}")
        return None

    ch_default = (getattr(B.board, "active_channels", None) or ["h0"])[0]
    bm_default = getattr(B.board, "beam", "b0")
    channel = input(f"Channel [{ch_default}] : ").strip() or ch_default
    beam = input(f"Beam [{bm_default}] : ").strip() or bm_default
    f_default = 19.5e9 if rx else 28e9
    f_raw = input(f"Frequencies, comma-separated [{f_default:.6g}] : ").strip()
    try:
        freqs = _parse_freqs(f_raw or None, f_default)
    except ValueError as exc:
        print(f"suite: bad frequency list ({exc}).")
        return None

    plan: list[tuple[str, dict]] = []
    for i, tid in enumerate(test_ids, 1):
        cls = get_test(tid)
        print(f"\n--- params {i}/{len(test_ids)}: {tid} (Enter = keep default) ---")
        hidden = _WIZARD_HIDDEN.get(tid, set())
        # freq_hz 는 위에서 목록으로 받았으므로 여기서는 묻지 않는다.
        plan.append((tid, _prompt_params(cls, rx=rx, hidden=hidden,
                                         skip=("freq_hz",))))
    return channel, beam, freqs, plan


def _suite_run(kind: str, channel: str, beam: str, freqs: list[float],
               plan: list[tuple[str, dict]], *, order: str = "freq",
               overrides: dict | None = None):
    """계획대로 순차 실행. 스텝마다 CSV 저장, 실패해도 다음으로 넘어간다.

    order='freq' (기본): 주파수 하나에서 전 항목을 돌고 다음 주파수로 간다.
    order='step'       : 항목 하나를 전 주파수에서 돌고 다음 항목으로 간다.
    freq-major 는 주파수마다 SA 앱(spectrum <-> NR5G)을 오가므로 전환이 잦다.
    전환 자체는 FSVA3030._switch_app 이 확인/재시도로 방어하지만, 벤치에서 불안정하면
    order='step' 으로 전환 횟수를 항목 수만큼으로 줄일 수 있다.
    """
    chan_fn = _ns.get("chan")
    if chan_fn is None:
        print("suite: 'chan' not available in session namespace.")
        return None
    chan_fn(channel, beam)

    runs: list[tuple[str, float, dict]] = []
    if order == "step":
        for tid, kw in plan:
            for f in _freqs_for(tid, freqs):
                runs.append((tid, f, kw))
    else:
        # freq-major: 같은 주파수에서 전 항목을 먼저 돈다. 주파수축이 없는 항목
        # (freq_hz 파라미터가 없는 테스트)은 첫 주파수 사이클에서 한 번만 돈다.
        done_once: set[str] = set()
        for f in freqs:
            for tid, kw in plan:
                if _freqs_for(tid, freqs) == [None]:
                    if tid in done_once:
                        continue
                    done_once.add(tid)
                    runs.append((tid, None, kw))
                else:
                    runs.append((tid, f, kw))

    results = []
    rows = []
    for n, (tid, f, kw) in enumerate(runs, 1):
        params = dict(kw)
        if f is not None:
            params["freq_hz"] = f
        ov = (overrides or {}).get(tid)
        if isinstance(ov, dict):
            params.update(ov)
        fstr = f"{f / 1e9:.3f} GHz" if f is not None else "-"
        print(f"--- suite step {n}/{len(runs)}: {tid} @ {fstr} ---")
        try:
            r = _run_test(tid, params)
            results.append(r)
            rows.append((tid, fstr, "OK" if r is not None else "FAIL",
                         getattr(r, "summary", "")))
        except Exception as e:  # noqa: BLE001
            print(f"[suite  ] step '{tid}' @ {fstr} failed: {e} -- continuing")
            results.append(None)
            rows.append((tid, fstr, "FAIL", str(e)[:60]))

    ok = sum(1 for r in results if r is not None)
    print(f"\n=== suite done: {ok}/{len(runs)} runs OK "
          f"(channel={channel} beam={beam}) ===")
    for tid, fstr, status, summary in rows:
        print(f"  {status:<4} {tid:<22} {fstr:>11}  {summary[:60]}")
    return results


def _tx_preset(freq_hz: float, bm: str, waveform_path: str):
    """tx_suite 기본 프리셋(인자를 주고 steps 를 생략했을 때). 예전 동작 그대로."""
    return [
        # gain_target='common' + beam=bm: common gain 은 beam 에 종속(b0/b1/b2 각각
        # 자기 common_gain 필드)이라 gain_map.resolve_gain_params 가 beam 인자로
        # 유도한다. gain_code 0x00 = 최대 게인. SA ref 25 dBm(Psat ~24 dBm 커버).
        ("linearity", "op1db",
         {"freq_hz": freq_hz, "gain_target": "common", "beam": bm,
          "gain_code": 0x00, "sa_ref_level_dbm": 25.0, "pin_start_dbm": -22.0,
          "pin_stop_dbm": 10.0, "pin_step_db": 1.0}),
        ("gain_common", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _TX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _TX_GAIN_SA_REF_DBM,
          "common_codes": list(range(64)), "channel_codes": [0],
          "channel_target": "beamtable", "log_psu": False}),
        ("gain_chan", "gain_index_accuracy",
         {"freq_hz": freq_hz, "sg_level_dbm": _TX_GAIN_SG_DBM,
          "sa_ref_level_dbm": _TX_GAIN_SA_REF_DBM,
          "common_codes": [0], "channel_codes": list(range(64)),
          "channel_target": "beamtable", "log_psu": False}),
        ("evm", "evm",
         {"freq_hz": freq_hz,
          "modulation": "load" if waveform_path else "manual",
          "waveform_path": waveform_path, "setup_sa": False,
          "pin_start_dbm": -50.0, "pin_stop_dbm": 0.0, "pin_step_db": 1.0}),
    ]


def tx_suite(channel=None, freq_hz=28e9, beam=None, waveform_path="",
             steps=None, freqs=None, order="freq", **overrides):
    """Run a TX measurement suite: pick the test items, their order and frequencies.

    Three ways in:
      tx_suite()                       interactive builder (pick tests / channel /
                                       frequencies / params, then run)
      tx_suite('h1')                   the classic 4-step preset, unchanged:
                                       op1db -> gain_index_accuracy x2 -> evm
      tx_suite('h1', steps='vdd_sensitivity,evm', freqs='28e9,29e9,30e9')
                                       run those items, in that order, at each freq

    steps  : test ids or menu numbers ('vdd_sensitivity,evm' or '7,4').
    freqs  : one or more frequencies ('28e9,29e9' or [28e9, 29e9]). Omitted -> freq_hz.
    order  : 'freq' (default) runs every item at one frequency before moving to the
             next; 'step' runs one item at every frequency before the next item.
             'freq' switches the SA between spectrum and NR5G once per frequency;
             use 'step' if that proves flaky on the bench.
    Each step saves its own CSV (the frequency is in the filename) and a failing
    step is skipped so the rest still run. Override one item's params with
    overrides[test_id], e.g. tx_suite('h1', steps='evm', evm={'pin_stop_dbm': -5}).
    Move the SA cable to the channel's port and change the channel arg per channel.
    """
    if C is None:
        print("not started. call start(channels=['h1']) first.")
        return None
    if channel is None and steps is None:
        built = _suite_build("tx")
        if built is None:
            return None
        channel, beam, freq_list, plan = built
        print(f"\n=== Plan: {len(plan)} test(s) x {len(freq_list)} freq(s) ===")
        for f in freq_list:
            for tid, _ in plan:
                print(f"  {tid:<24} {f / 1e9:.3f} GHz")
        if input("Run now? [Y/n]: ").strip().lower() not in ("", "y", "yes"):
            print("suite: cancelled.")
            return None
        return _suite_run("tx", channel, beam, freq_list, plan, order=order)

    channel = channel or "h0"
    # beam 미지정이면 현재 보드 beam 유지(b0 로 되돌리지 않음).
    bm = beam if beam is not None else getattr(B.board, "beam", "b0")
    if steps is None:
        # 예전 프리셋 경로: 라벨 기반 overrides 를 그대로 지원한다.
        preset = _tx_preset(freq_hz, bm, waveform_path)
        chan_fn = _ns.get("chan")
        if chan_fn is None:
            print("tx_suite: 'chan' not available in session namespace.")
            return None
        chan_fn(channel, bm)
        results = []
        for label, test_id, kw in preset:
            ov = overrides.get(label)
            if isinstance(ov, dict):
                kw.update(ov)
            print(f"--- tx_suite step: {label} ({test_id}) ---")
            try:
                results.append(_run_test(test_id, kw))
            except Exception as e:  # noqa: BLE001
                print(f"[tx_suite] step '{label}' failed: {e} -- continuing")
                results.append(None)
        ok = sum(1 for r in results if r is not None)
        print(f"=== tx_suite({channel}) done: {ok}/{len(preset)} steps OK ===")
        return results

    try:
        test_ids = _parse_steps(steps, "tx")
        freq_list = _parse_freqs(freqs, freq_hz)
    except ValueError as exc:
        print(f"tx_suite: {exc}")
        return None
    # evm 은 suite 안에서 SA 를 사용자가 잡아둔 NR 설정 그대로 쓰되(setup_sa=False),
    # center 주파수만 스텝 주파수를 따라간다(evm 의 sa_follow_center 기본 True).
    plan = [(tid, {"waveform_path": waveform_path,
                   "modulation": "load" if waveform_path else "manual",
                   "setup_sa": False} if tid == "evm" else {})
            for tid in test_ids]
    return _suite_run("tx", channel, bm, freq_list, plan, order=order,
                      overrides=overrides)


def split(on=None):
    """DIST splitter split mode (TX only). split() shows it, split(True/False) changes it.

    True  = split: 0x1009=783 turns the beam0 distribution network on for CH0..CH3
            (multi-channel combine) and 0x1068=0x8888 restores the CH0 captune word.
    False = thru: neither word is written, so only the active channel's branch is on.

    Changing the mode RE-RUNS THE FULL BRING-UP, because 0x1009=783 overwrites the
    beam_enables written earlier and there is no safe way to undo just that word.
    Anything you set by hand after start() -- gain(), chgain(), atten(), phase() --
    goes back to the bench.toml values. Re-apply it after the toggle.

    NOTE: 0x1009 is the b0 register (center_dist_b{n} = 0x1009+n), so split on a
    b1/b2 beam still writes b0's word. Unverified on silicon - keep split on b0.
    """
    if C is None or B is None:
        print("not started. call start(channels=['h1']) first.")
        return None
    cur = bool(getattr(B.board, "split_mode", False))
    if _chip_kind == "rx":
        # bring_up_rx 는 cfg.split_mode 를 읽지 않는다 -- 조용히 아무 일도 안 하는
        # 대신 그렇다고 말한다.
        print("split: TX (Stampede) only -- the RX bring-up ignores split_mode.")
        return None
    if on is None:
        print(f"split mode: {'ON (split)' if cur else 'OFF (thru)'}  "
              f"[beam={B.board.beam}, channels={B.board.active_channels}]")
        print("  split(True) = multi-channel combine / split(False) = thru")
        return cur
    want = bool(on)
    if want == cur:
        print(f"split mode already {'ON (split)' if cur else 'OFF (thru)'} "
              f"-- bring-up not re-run.")
        return cur
    B.board.split_mode = want
    print(f"[split  ] {'OFF -> ON (split)' if want else 'ON -> OFF (thru)'} "
          f"-- re-running bring-up...")
    try:
        bring_up_tx(C, B.board, require_version=not _fake)
    except Exception:
        B.board.split_mode = cur     # 실패 시 설정값이 실제 칩 상태와 어긋나지 않게 되돌린다
        print(f"[split  ] bring-up FAILED -- split_mode reverted to "
              f"{'ON' if cur else 'OFF'} in the config. The chip may be in a "
              f"half-configured state: re-run start() before measuring.")
        raise
    print(f"[split  ] split mode {'ON (split)' if want else 'OFF (thru)'}. "
          f"Manual gain/phase tweaks were reset to bench.toml values.")
    return want


def loss(freq_ghz=None):
    """Path loss lookup (from Loss_data CSVs). loss() shows the table,
    loss(28) shows in/out loss at 28 GHz. Shows manual override when active."""
    ov = getattr(B, "_loss_override", None) if B is not None else None
    if freq_ghz is None:
        print(loss_table())
        if ov is not None:
            print(f"  [manual override active] in_loss={ov[0]:.2f} "
                  f"out_loss={ov[1]:.2f} dB (set_loss() to clear)")
        return None
    f = float(freq_ghz) * 1e9
    if ov is not None:
        il, ol = ov
        tag = " [manual override]"
    else:
        try:
            il, ol = get_loss(f)
        except (FileNotFoundError, ValueError) as e:
            print(f"  loss unavailable: {e}")
            return None
        tag = ""
    print(f"  {float(freq_ghz):.3f} GHz: in_loss={il:.2f} dB, "
          f"out_loss={ol:.2f} dB{tag}")
    return il, ol


def set_loss(in_db=None, out_db=None):
    """Manually fix SG/SA loss offsets (overrides CSV auto-loss) for quick tests.
    set_loss(in_db, out_db) -> fix; set_loss() -> clear (back to CSV-auto)."""
    if B is None:
        print("not started.")
        return None
    if in_db is None and out_db is None:
        B.clear_loss_override()
        print("  loss override cleared -> CSV-auto")
        return None
    if in_db is None or out_db is None:
        print("  set_loss needs both in_db and out_db (or none to clear).")
        return None
    B.set_loss_override(in_db, out_db)
    print(f"  loss override set: in_loss={float(in_db):.2f} dB, "
          f"out_loss={float(out_db):.2f} dB")
    return None


def find_bias(channel=None, beam=None, write=True, **kw):
    """Find this channel's bias codes and record them in config/bench.toml (TX).

    Stages on the channel that is already cabled and routed: match the PTAT
    codes to the Sivers reference rail currents, screen the DIST code grid on
    current, keep only what sits inside the datasheet gain window (19..25 dB,
    the split row), take the highest OP1dB, then match PTAT once more on those
    DIST codes and measure the result. No power cycle and no bring-up -- move
    the cable, then call this.

    Takes 20 to 30 minutes with the defaults. The chip is left on the codes it
    picked, so a measurement can follow straight away; a failure puts the old
    codes back. Passing a channel routes it first (same as chan()).

    e.g. find_bias('h1')            # current channel's beam
         find_bias('h1', 'b0')
         find_bias('h1', grid_step=8)     # finer DIST grid, slower
         find_bias('h1', write=False)     # report only, leave bench.toml alone
         find_bias('h1', max_op1db=6)     # halve the slowest stage
         find_bias('h1', rematch_ptat=False)   # skip the second PTAT match
    Options: see FindBiasOpts in cloudchaser/bias_find.py. CSV saved to out/.
    """
    from .bias_find import FindBiasOpts, find_bias as _find_bias

    if B is None or C is None:
        print("not started.")
        return None
    if _chip_kind != "tx":
        print("find_bias is TX only (the DIST/FE bias columns are Stampede's).")
        return None
    ch = (channel or B.board.active_channels[0]).strip().lower()
    bm = (beam or B.board.beam).strip().lower()
    if channel is not None or beam is not None:
        # chan() 은 라우팅 + split 재적용 + 그 채널의 측정 bias 재기입까지 한다.
        _ns["chan"](ch, bm)
    fh = getattr(C, "_fh", None) or FH(C, getattr(B.board, "chip_id", 0))
    return _find_bias(B, fh, channel=ch, beam=bm, opts=FindBiasOpts(**kw),
                      config_path=DEFAULT_CONFIG, write_config=bool(write))


def peakc(freq_ghz=None):
    """Loss-compensated IC output power [dBm]. Applies path loss to the SA offset,
    then returns the peak (= chip beam-port output). freq defaults to current SG freq."""
    if B is None:
        print("not started.")
        return None
    f = float(freq_ghz) * 1e9 if freq_ghz else _ns.get("_sgstate", {}).get("freq", 28.0e9)
    B.apply_path_loss(f, log=lambda *_a: None)
    p = B.sa.measure_peak_dbm()
    print(f"  IC output (loss-compensated) = {p:.2f} dBm")
    return p


def _prompt_params(test_cls, *, rx: bool, hidden: set, skip: tuple = ()) -> dict:
    """한 테스트의 파라미터를 하나씩 물어 dict 로 모은다(Enter = 기본값).

    wizard() 와 tx_suite() 빌더가 공유한다 -- 프롬프트 규칙(숨김 목록, RX 기본값,
    잘못된 입력 처리)이 두 벌로 갈라지지 않게 하려는 것.
    skip : 여기서는 묻지 않을 파라미터 이름들(suite 는 freq_hz 를 앞에서 한 번에 받는다).
    """
    from .test_items.base import coerce as _coerce

    collected: dict = {}
    for p in test_cls.params:
        if p.name in hidden or p.name in skip:
            continue
        # RX 면 rx_default(있으면)를 기본값으로 -- Enter 만 쳐도 RX 값이 들어간다.
        eff_default = p.rx_default if (rx and p.rx_default is not None) else p.default
        unit_str = f" {p.unit}" if p.unit else ""
        label_str = p.help or p.label
        prompt = f"  {p.name:<22} [{eff_default}{unit_str}]  {label_str} : "
        raw_val = input(prompt).strip()
        if raw_val:
            try:
                collected[p.name] = _coerce(p, raw_val)
            except (ValueError, TypeError) as exc:
                print(f"    Bad value '{raw_val}': {exc}. Using default {eff_default!r}.")
        elif rx and p.rx_default is not None:
            collected[p.name] = p.rx_default   # Enter -> RX 기본값 적용
    return collected


def wizard():
    """Step-by-step guided measurement.

    Prompts for test selection and key parameters, then calls the
    corresponding session function. Path loss is auto-applied from
    Loss_data CSVs (same as calling the function directly).
    Usage: call after start().
    """
    if C is None:
        print("Not started. Call start(channels=['h1']) first.")
        return None

    kind = getattr(B, "chip_kind", "tx") if B else "tx"
    rx = (kind == "rx")
    # 이 칩에 의미있는 테스트만 보여준다(예: RX 면 op1db 숨기고 ip1db 표시).
    all_tests = [t for t in list_tests() if kind in getattr(t, "chips", ("tx", "rx"))]
    channels = getattr(B.board, "active_channels", []) if B else []
    beam = getattr(B.board, "beam", "b0") if B else "b0"

    print("=== Measurement Wizard ===")
    print(f"Active: chip={kind}  channels={channels}  beam={beam}")
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
    collected = _prompt_params(test_cls, rx=rx, hidden=hidden)

    # 실행 요약 + 확인
    key_items = [f"{k}={v}" for k, v in list(collected.items())[:4]]
    freq_hz = collected.get("freq_hz", test_cls.defaults().get("freq_hz"))
    freq_str = f"{freq_hz / 1e9:.3f} GHz" if freq_hz else ""

    print(f"\n=== Ready to run ===")
    print(f"  Test   : {test_cls.title}")
    if freq_str:
        print(f"  Freq   : {freq_str}")
    if key_items:
        print(f"  Params : {'  '.join(key_items)}")
    if uses_loss:
        print("  Loss   : auto (applied to SG/SA offsets from Loss_data CSVs)")
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


def _run_test(test_id: str, kw: dict):
    if C is None:
        print("not started. call start(channels=['h1']) first.")
        return None
    from . import runner  # 지연 import(순환 방지)
    test = get_test(test_id)()
    resolved = test.resolve(kw)
    ctx = TestContext(bench=B, chip=C, fake=_fake)
    result = test.run(ctx, resolved)
    try:
        runner._save_csv(result, resolved, runner.DEFAULT_OUT)
    except Exception as e:
        print(f"(csv save failed: {e})")
    print(f"=== {result.summary} ===")
    return result


def params(test_id: str):
    """Print parameter spec (name / type / default / description) for a test."""
    from . import runner
    runner._print_info(get_test(test_id))


def tests():
    """List all available test items."""
    for t in list_tests():
        print(f"  {t.id:16} {t.title}")


# ----------------------------------------------------------------------
# 상태 / 도움말
# ----------------------------------------------------------------------
def status():
    """Print current session state: active channels, gain codes, SG frequency/level."""
    if C is None:
        print("not started. call start(channels=['h1']).")
        return
    print("=== session status ===")
    try:
        # C.path.active is the vendor Python object's cached attribute -- raw
        # register writes (route_channels/chan()) never update it, so it goes
        # stale/empty the moment routing moves off the raw path (the same bug
        # class Ruling 28 fixed in manual.py's paths()). Reuse that helper --
        # it re-derives active routing from quad_enables/quad_pwrdn registers
        # each call instead of trusting a shadow cache.
        paths_fn = _ns.get("paths")
        if paths_fn is not None:
            paths_fn()
        else:
            print("  active paths : (unavailable -- 'paths' not in session namespace)")
    except Exception:
        pass
    try:
        # 빔은 B.board 에서 가져온다 -- "b0_common_gain" 하드코딩은 chan('h0','b1')
        # 뒤에 엉뚱한 빔의 게인을 현재 값인 척 보여줬다. 레지스터에서 직접 읽는다
        # (0x1005 + beam index, 6-bit): 벤더 필드 캐시를 거치지 않는 쪽이 위 paths()
        # 와도 같은 계약이다.
        board = getattr(B, "board", None)
        beam = getattr(board, "beam", None) or "b0"
        fh = _ns.get("fh") or FH(C, getattr(board, "chip_id", 0))
        print(f"  common_gain  : {hex(get_gain(fh, 'common', beam=beam))} "
              f"(beam {beam}, 0=max gain, 0x3f=max atten)")
    except Exception:
        pass
    st = _ns.get("_sgstate", {})
    if st:
        print(f"  SG           : {st.get('freq', 0)/1e9:.3f} GHz @ "
              f"{st.get('level', 0):.1f} dBm")
    print(f"  fake / power : {_fake} / (rails powered if you ran power=True)")
    print("  tip: vi() for live rail V/I, peak() for SA reading.")


# help() 카테고리. (명령, 설명) — 짧게. 상세는 help('name').
_HELP = {
    "setup": [
        ("start(channels=['h1'], power=True, fake=False)", "connect + power + bring-up"),
        ("restart(channels=['h1'])", "close and start again"),
        ("shutdown()", "ramp rails to 0 V in reverse order (also auto-runs on exit())"),
    ],
    "board": [
        ("chan('h1')", "bring up ONE channel measurement-ready (center bias+RTPS+max gain)"),
        ("enable('h1') / disable('h1')", "turn channel(s) on/off"),
        ("gain(0)", "common gain (atten code, 0=max gain)"),
        ("chgain('h1', c) / atten('h1', c)", "per-channel gain / attenuation"),
        ("phase('h1', 0x40)", "per-channel RTPS phase (beam-table 7-bit code, beam 0)"),
        ("rtps()", "show beam-table atten/phase per quad"),
        ("biasscan('h1')", "sweep each stage bias, detect dead stage"),
        ("rd('field') / wrf('field', v)",
         "read / write ONE register field by name (wrf masks, so the rest of "
         "the word survives). Names are lower case -- table: COMMANDS.md app. B"),
        ("fh.rd(0x104C) / fh.wr_verify(0x104C, v)", "raw 16-bit word read / write"),
        ("dump() / regdiff(ref)", "read the live register state / diff vs a reference dump"),
        ("paths()", "show active beam->channel routing"),
    ],
    "SG (signal gen)": [
        ("rf(True, freq=28e9, level=-10)", "set freq/level then RF ON"),
        ("rfoff()", "RF OFF"),
        ("level(-10)", "change output level [dBm]"),
    ],
    "SA (analyzer)": [
        ("saconf(center=28e9, span=100e6, ref=20)", "configure SA"),
        ("peak()", "raw SA marker peak [dBm]"),
        ("peakc(28)", "loss-compensated IC output = raw + out_loss"),
    ],
    "power": [
        ("vi()", "read all rail V / I"),
    ],
    "board mode": [
        ("split() / split(True) / split(False)",
         "[TX] show / set DIST splitter mode. True=split(multi-channel combine, "
         "0x1009=783 + 0x1068=0x8888), False=thru(single channel). "
         "Changing it RE-RUNS bring-up, so manual gain/phase tweaks are reset."),
    ],
    "bias": [
        ("find_bias('h1')",
         "[TX] find this channel's bias codes (PTAT current match -> DIST grid "
         "-> gain window 19..25 dB -> best OP1dB) and write them into "
         "config/bench.toml. Cable and route the channel first; ~8 min.",
         "Key: beam, write=False(report only), grid_step, freq_ghz  |  "
         "help('find_bias')"),
    ],
    "loss (path comp)": [
        ("loss() / loss(28)", "show loss table / loss at a freq (from Loss_data CSVs)"),
        ("set_loss(in, out) / set_loss()", "manual loss override / clear (back to CSV-auto)"),
    ],
    "measure": [
        # ("!warn", message, "")  -> printed as  !!  message
        # 3-tuple: (signature, purpose, key-params hint)
        ("op1db(freq_hz=28e9, gain_code=0)",
         "CW power sweep -> output 1-dB compression point. CSV -> out/.",
         "Key: gain_code(0=max), pin_start/stop_dbm, log_idd  |  params('op1db')"),
        ("gain_index_accuracy(sg_level_dbm=0)",
         "Sweep common & per-path(beam-table attenuator) gain codes, record gain vs index.",
         "Key: channel_target('beamtable'), channel_quad  |  params('gain_index_accuracy')"),
        ("channel_gain_alignment(channel_mode='all')",
         "Move SA cable per channel, record output level spread.",
         "channel_mode: 'all'(all ON, move cable) / 'single'(switch per ch)  |  params('channel_gain_alignment')"),
        ("evm(freq_hz=28e9)",
         "5G NR modulation quality (EVM[dB]) vs output power.",
         "Key: modulation(setup/load/manual), waveform_path  |  params('evm')"),
        ("acp(freq_hz=28e9)",
         "Adjacent channel power ratio[dBc] vs output power.",
         "Key: modulation  |  params('acp')"),
        ("phase_index_accuracy()",
         "[TX/RX] sweep RTPS phase codes (0..127), read S21 gain/phase on the "
         "MS4644B VNA. Calibrate the VNA manually first (code never presets it).",
         "Key: read_mode(marker/point/trace), phase_codes, marker_freq_hz  |  "
         "params('phase_index_accuracy')"),
        ("vdd_sensitivity(freq_hz=28e9)",
         "[TX] OP1dB sweep repeated at each FE1 supply voltage (4.0 down to 2.2 V). "
         "One CSV with a VDD_set_V column; the rail always returns to 4.0 V.",
         "Key: vdd_list_v, gain_code, pin_start/stop_dbm  |  params('vdd_sensitivity')"),
        ("tx_suite() / tx_suite('h1', steps=..., freqs=...)",
         "[TX] suite: pick test items, their order and frequencies. No args = "
         "interactive builder; 'h1' alone = the classic 4-step preset. CSV per step.",
         "Key: steps('vdd_sensitivity,evm'), freqs('28e9,29e9'), order(freq|step), "
         "per-item overrides e.g. evm={'pin_stop_dbm': -5}"),
        # RX (Blueway)
        ("ip1db(freq_hz=19.5e9, gain_code=0)",
         "[RX] CW power sweep -> input 1-dB compression point (IP1dB). CSV -> out/.",
         "Key: gain_code(0=max), pin_start/stop_dbm  |  params('ip1db')"),
        ("rx_suite('h0')",
         "[RX] full suite for ONE channel: ip1db + gain accuracy(2 axes) + evm. CSV per step.",
         "Key: freq_hz, beam, waveform_path, per-step overrides e.g. linearity={'pin_stop_dbm': -8}"),
        ("params('op1db')", "show that test's parameters & defaults", ""),
        ("tests()", "list available tests", ""),
        ("wizard()", "guided step-by-step measurement  <-- start here", ""),
    ],
    "info": [
        ("status()", "current channel / gain / SG state"),
        ("help() / help('rf')", "this list / detail of one command"),
        ("wizard()", "guided step-by-step measurement"),
    ],
}


def help(topic=None):
    """Command reference. help() = full list. help('rf') = detail for one command."""
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
