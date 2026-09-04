"""게인/위상 타깃 -> 레지스터 매핑, 그리고 채널 라우팅의 raw 대체.

벤더 고수준 쓰기 API(fields 쓰기 / path / beam table 객체)를 쓰지 않기 위한 계층이다.
근거는 설계 스펙 2장·6장.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다.
"""

from __future__ import annotations

from .firehawk import COMMON_GAIN, FE_GAIN_ADDR, FH, VERSION_ID_RX, VERSION_ID_TX, parse_ch

GAIN_TARGETS = ("common", "fe", "beamtable")

# Field width per target, in bits. set_gain rejects codes that don't fit --
# see Ruling 16: silently truncating (write) or widening the read side would
# both hide caller error, so the write side validates instead.
_FIELD_BITS = {"common": 6, "fe": 4, "beamtable": 7}


def set_gain(fh, target, code, *, beam="b0", channel="h0"):
    """Set a gain code on the selected target.

    target : "common"    -> beam-wide attenuation, 0x1005 + beam index (6-bit, 0 = max gain)
             "fe"        -> per-channel FE gain, 0x1018 + channel index (4-bit)
             "beamtable" -> RTPS attenuator, beam-table word (7-bit, 0 = max gain)

    Raises ValueError if `code` does not fit the target's field width.
    """
    if target not in GAIN_TARGETS:
        raise ValueError(f"unknown gain target: {target!r} (use one of {GAIN_TARGETS})")
    code = int(code)
    width = _FIELD_BITS[target]
    maxval = (1 << width) - 1
    if not (0 <= code <= maxval):
        raise ValueError(
            f"gain code {code} does not fit target {target!r} ({width}-bit, max {maxval})"
        )
    if target == "common":
        fh.wr_verify(COMMON_GAIN + int(beam[-1]), code & 0xFFFF)
    elif target == "fe":
        pol, ci = parse_ch(channel)
        cur = fh.rd(FE_GAIN_ADDR + ci)
        # FE gain 은 4-bit 다: gain_control_h{i} = 0x1018[3:0], gain_control_v{i} =
        # 0x1018[11:8]. 같은 워드의 bit12 는 pulse_en_ch{i}_4 이므로 V 쪽을 8-bit 로
        # 쓰면 그걸 지워버린다(H 쪽만 보존하던 같은 함수 안의 비대칭). 두 분기 모두
        # 자기 니블만 갈아끼운다 -- bringup.py 의 리드백이 이미 & 0xF 로 고친 것과 동일 계약.
        if pol == "v":
            new = (cur & ~0x0F00) | ((code & 0xF) << 8)
        else:
            new = (cur & ~0x000F) | (code & 0xF)
        fh.wr_verify(FE_GAIN_ADDR + ci, new & 0xFFFF)
    elif target == "beamtable":
        _, ci = parse_ch(channel)
        cur = fh.rd(ci)
        fh.wr(ci, (cur & ~0x7F) | (code & 0x7F))
        fh.beam_up()


def get_gain(fh, target, *, beam="b0", channel="h0"):
    """Read back the gain code from the selected target."""
    if target == "common":
        return fh.rd(COMMON_GAIN + int(beam[-1])) & 0x3F
    if target == "fe":
        pol, ci = parse_ch(channel)
        w = fh.rd(FE_GAIN_ADDR + ci)
        # 4-bit 필드다(위 set_gain 주석 참고). 8-bit 로 읽으면 V 쪽에 bit12(pulse_en)가
        # 결과 bit4 로 새어 나와 방금 쓴 코드와 다른 값이 리드백된다.
        return (w >> 8) & 0xF if pol == "v" else w & 0xF
    if target == "beamtable":
        _, ci = parse_ch(channel)
        return fh.rd(ci) & 0x7F
    raise ValueError(f"unknown gain target: {target!r} (use one of {GAIN_TARGETS})")


def check_gain_codes(target, codes):
    """Validate every code in `codes` fits `target`'s field width before a sweep starts.

    set_gain() itself raises ValueError on an out-of-range code, but only when that
    particular code is written -- i.e. potentially mid-sweep, after instruments were
    already configured and earlier points already measured (Ruling 20). Call this
    first on the full code list so a bad sweep fails atomically, before anything
    else happens.
    """
    if target not in GAIN_TARGETS:
        raise ValueError(f"unknown gain target: {target!r} (use one of {GAIN_TARGETS})")
    width = _FIELD_BITS[target]
    maxval = (1 << width) - 1
    bad = sorted({int(c) for c in codes if not (0 <= int(c) <= maxval)})
    if bad:
        raise ValueError(
            f"gain codes {bad} do not fit target {target!r} ({width}-bit, max {maxval}) "
            f"-- aborted before any measurement"
        )


def set_phase(fh, code, *, beam="b0", channel="h0", atten=0):
    """Set the 9-bit RTPS phase (coarse beam-table + fine phase-cal RAM)."""
    pol, ci = parse_ch(channel)
    fh.set_rtps_attn(int(atten), int(code), ci, int(beam[-1]), 1 if pol == "v" else 0)


def chip_kind(fh):
    """Identify whether `fh` is talking to a TX (Stampede) or RX (Blueway) chip.

    Reads the identity/version_id word (FH.get_short_id) instead of trusting a
    caller-supplied or hardcoded "tx"/"rx" string. route_channels()'s H/V bit
    positions are mirrored between TX and RX -- a wrong/stale "kind" routes the
    opposite polarity silently, with output that still looks plausible. That is
    the same failure mode found on real silicon during the Sivers trip (Ruling 21).
    version_id is a read-only identity field, so this works whether or not a
    bring-up ran.
    """
    _, version_id = fh.get_short_id()
    if version_id == VERSION_ID_TX:
        return "tx"
    if version_id == VERSION_ID_RX:
        return "rx"
    if version_id == 0:
        raise ValueError(
            "cannot determine chip kind: version_id read 0x0 -- board is likely "
            "unpowered or SPI is not responding (expected TX 0xDC or RX 0xD4)"
        )
    raise ValueError(
        f"cannot determine chip kind: unexpected version_id 0x{version_id:02X} "
        f"(expected TX 0x{VERSION_ID_TX:02X} or RX 0x{VERSION_ID_RX:02X})"
    )


def route_channels(fh, channels, beam, kind):
    """Enable ONLY the listed channels on the given beam (raw replacement for path.enable).

    quad_pwrdn 의 H/V 6-bit 위치는 TX 와 RX 가 반대다(Sivers 출장 중 실칩 버그 원인):
    TX(Stampede) H=bits[5:3]/V=bits[2:0], RX(Blueway) H=bits[2:0]/V=bits[5:3].
    """
    beam_i = int(str(beam)[-1])
    enbit = 1 << beam_i
    qen = [[0, 0, 0] for _ in range(4)]
    qpd = [[0, 0, 0, 0, 0] for _ in range(4)]
    mask = 0
    for ch in channels:
        pol, ci = parse_ch(ch)
        qen[ci] = [enbit, enbit, 0]
        # TX 는 h=[5:3]/v=[2:0], RX 는 반대다.
        if kind == "tx":
            base = 0 if pol == "v" else 3
        else:
            base = 3 if pol == "v" else 0
        qpd[ci] = [0b111 << base, 1, 1, 0, 0]
        mask |= 1 << ci
    fh.set_quad_enables(qen)
    fh.set_quad_pwrdn(qpd)
    be = [[0, 0, 0, 0] for _ in range(3)]
    be[beam_i] = [mask, 1, 1 if kind == "tx" else 4, 0]
    fh.set_beam_enables(be)


def disable_all(fh):
    """Turn every channel and beam off (raw replacement for path.disable_all)."""
    fh.set_quad_pwrdn([[0, 0, 0, 0, 0] for _ in range(4)])
    fh.set_quad_enables([[0, 0, 0] for _ in range(4)])
    fh.set_beam_enables([[0, 0, 0, 0] for _ in range(3)])


_LEGACY_HINT = ("[deprecated] {old} is deprecated; use {new}. "
                "Mapped to {mapping}")


def resolve_legacy(params, board, log=print):
    """구 파라미터(필드 이름 문자열)를 신규 타깃 계약으로 매핑한다.

    반환: params 사본 + 신규 키. 구 키가 없으면 그대로 통과시킨다.
    """
    out = dict(params)
    field = out.pop("gain_field", "") or ""
    if field and not out.get("gain_target"):
        if field.endswith("_common_gain"):
            out["gain_target"] = "common"
            out["beam"] = field.split("_")[0]
            mapping = f"gain_target=common, beam={out['beam']}"
        elif field.startswith("gain_control_"):
            out["gain_target"] = "fe"
            out["channel"] = field[len("gain_control_"):]
            mapping = f"gain_target=fe, channel={out['channel']}"
        else:
            out["gain_target"] = "common"
            mapping = "gain_target=common"
        log(_LEGACY_HINT.format(old="gain_field", new="gain_target", mapping=mapping))

    cfield = out.pop("common_field", "") or ""
    if cfield and not out.get("common_target"):
        out["common_target"] = "common"
        if cfield.endswith("_common_gain"):
            out["beam"] = cfield.split("_")[0]
        log(_LEGACY_HINT.format(old="common_field", new="common_target",
                                mapping="common_target=common"))

    kind = out.pop("channel_kind", "") or ""
    chfield = out.pop("channel_field", "") or ""
    if kind and not out.get("channel_target"):
        out["channel_target"] = "beamtable" if kind == "beamtable" else "fe"
        log(_LEGACY_HINT.format(old="channel_kind", new="channel_target",
                                mapping=f"channel_target={out['channel_target']}"))
    if chfield and out.get("channel_target") == "fe" and not out.get("channel"):
        out["channel"] = chfield[len("gain_control_"):] if chfield.startswith(
            "gain_control_") else chfield

    return out


def resolve_gain_params(params, bench, chip, log=print):
    """Resolve legacy fields, then derive the (params, fh, beam, channel) 4-tuple
    every gain-target test item (op1db/ip1db/gain_index_accuracy/channel_gain_alignment)
    needs at the top of run() -- pulled out per Ruling 19 so this ~8-line block isn't
    copy-pasted a fourth time.

    beam/channel fall back to bench.board's active beam / first active channel when
    params doesn't override them (both blank by default -- see Ruling 17). fh falls
    back to a bare FH wrapper when chip._fh is missing (Ruling 1): manual.py's
    --no-enable path only runs the vendor init (chip.init), never bring-up, so _fh is never
    attached, and the fake-mode test helper _make_ctx() has the same gap.
    """
    params = resolve_legacy(params, bench.board, log=log)
    beam = params.get("beam") or getattr(bench.board, "beam", "b0")
    chans = getattr(bench.board, "active_channels", []) or []
    channel = params.get("channel") or (chans[0] if chans else "h0")
    fh = getattr(chip, "_fh", None) or FH(chip, getattr(bench.board, "chip_id", 0))
    return params, fh, beam, channel


def setup_single_channel(fh, beam, ch):
    """Bring exactly one channel into the measurable state; disable the rest.

    Vendor high-level write APIs (path / fields writes / beam-table objects) are
    NOT used: they are read-modify-write against a Python shadow cache and can
    revert the raw 0x1008/0x100C/0x1010 writes made by bring-up.
    """
    disable_all(fh)
    # centerbias_en / centermirror_en (0x1008 bits 0/1) ON.
    fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    # TX/RX 라우팅 극성은 칩 identity 레지스터로 런타임 판별한다.
    route_channels(fh, [ch], beam, chip_kind(fh))
    fh.load_beam_table(0, [[0] * 8])
    fh.beam_up()
    set_gain(fh, "common", 0, beam=beam)
