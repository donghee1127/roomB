"""실측으로 확정한 채널별 bias 코드 적용 (`bench.toml` 의 `[board.bias.<ch>]`).

`bias_v4.py` 와는 성격이 다르다: 저쪽은 Sivers v4 시트가 준 값이고, 여기는
`bias_match` 로 **이 보드/이 다이에서 직접 찾은** 값이다. 채널마다 다르므로
채널 키로 관리한다.

왜 별도 단계가 필요한가 -- bring-up step 18 의 `DIRECT_REGS_TX` 가
`0x104C = 3378`(DIST st1=50, st2_0=13 = v4 Casper)을 하드코딩으로 기입해서 step 10 의
`set_dist_bias()` 를 덮는다. 그 하드코딩은 evb_full 과의 레지스터 동일성 근거라
건드리지 않고, 대신 **그 뒤에 한 번 더** 실측값을 얹는다.

DIST 는 빔당 1행(3x6)이라 한 빔의 채널들이 서로 다른 DIST 코드를 동시에 가질 수 없다.
따라서 채널을 바꾸면(`chan()`) 그 채널의 DIST 로 다시 기입해야 한다 -- split 모드가
`route_channels()` 에 덮여 게인이 8 dB 어긋났던 것과 같은 구조다(main d7b76c5).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .firehawk import fe_row, parse_ch

CODE_MIN, CODE_MAX = 0, 63
# [board.bias.<ch>] 가 가질 수 있는 키. 값은 모두 6-bit 코드 3개.
#   ptat = [ptat_st1, ptat_st2, ptat_st3]      -> FE bias 행의 열 0..2
#   dist = [dist_st1, dist_st2_0, dist_st2_1]  -> DIST bias 행의 열 0..2
_KEYS = ("ptat", "dist")


def _check_channel(ch) -> str:
    """'H1' -> 'h1'. parse_measured_bias 와 같은 규칙으로 검증한다."""
    name = str(ch).strip().lower()
    if (len(name) != 2 or name[0] not in ("h", "v")
            or not name[1].isdigit() or not 0 <= int(name[1]) <= 3):
        raise ValueError(f"bad channel key {ch!r}: expected h0..h3 or v0..v3")
    return name


def _check_codes(name: str, key: str, codes) -> list[int]:
    """3개의 6-bit 코드인지 검사하고 int 리스트로 돌려준다."""
    out = [int(v) for v in codes]
    if len(out) != 3:
        raise ValueError(f"[board.bias.{name}] {key} needs 3 codes, got {len(out)}")
    for c in out:
        if not CODE_MIN <= c <= CODE_MAX:
            raise ValueError(f"[board.bias.{name}] {key} code {c} out of range "
                             f"{CODE_MIN}..{CODE_MAX}")
    return out


def parse_measured_bias(raw) -> dict[str, dict[str, list[int]]]:
    """Validate the `[board.bias]` table and return it as plain ints.

    Raises ValueError on a malformed entry rather than silently biasing the
    chip with something unintended -- a wrong code here is written straight
    into the amplifier bias.
    """
    out: dict[str, dict[str, list[int]]] = {}
    for ch, entry in dict(raw or {}).items():
        name = str(ch).strip().lower()
        # parse_ch() 는 검증을 안 한다("z9" -> ("z", 9)). 여기서 막지 않으면
        # fe_row() 가 8행 밖을 가리키거나 엉뚱한 편파에 bias 를 쓴다.
        if (len(name) != 2 or name[0] not in ("h", "v")
                or not name[1].isdigit() or not 0 <= int(name[1]) <= 3):
            raise ValueError(f"[board.bias] bad channel key {ch!r}: "
                             "expected h0..h3 or v0..v3")
        got: dict[str, list[int]] = {}
        for key in _KEYS:
            if key not in entry:
                continue
            codes = [int(v) for v in entry[key]]
            if len(codes) != 3:
                raise ValueError(f"[board.bias.{name}] {key} needs 3 codes, "
                                 f"got {len(codes)}")
            for c in codes:
                if not CODE_MIN <= c <= CODE_MAX:
                    raise ValueError(f"[board.bias.{name}] {key} code {c} out of "
                                     f"range {CODE_MIN}..{CODE_MAX}")
            got[key] = codes
        if got:
            out[name] = got
    return out


def apply_measured_bias(fh, cfg, channel: str, *, beam_idx: int, log=print) -> bool:
    """Write the measured codes for `channel`, if the config has any.

    Returns True when something was written. Leaves every other field alone:
    FE CTAT/CBIAS and the DIST cbias columns keep whatever bring-up put there.
    """
    table = getattr(cfg, "measured_bias", None) or {}
    entry = table.get(str(channel).strip().lower())
    if not entry:
        return False
    pol, idx = parse_ch(channel)
    wrote = []
    if "ptat" in entry:
        bias = fh.get_fe_bias()
        row = fe_row(idx, pol)
        bias[row][0:3] = entry["ptat"]
        fh.set_fe_bias(bias)
        wrote.append(f"ptat={entry['ptat']}")
    if "dist" in entry:
        dist, ctat = fh.get_dist_bias()
        dist[beam_idx][0:3] = entry["dist"]
        fh.set_dist_bias(dist, ctat)
        wrote.append(f"dist={entry['dist']}")
    if wrote:
        log(f"[bias   ] measured bias for {channel}: " + "  ".join(wrote))
    return bool(wrote)


def apply_measured_bias_bringup(fh, cfg, active_channels, *, beam_idx: int,
                                log=print) -> None:
    """Bring-up hook: FE rows for every configured active channel, DIST once.

    FE bias has a row per channel so every configured channel can be written at
    once. DIST has a single row per beam, so only one channel's DIST can be in
    effect; the first configured active channel wins and the rest are reported.
    Switching channels later must re-apply -- see `apply_measured_bias`.
    """
    table = getattr(cfg, "measured_bias", None) or {}
    if not table:
        return
    configured = [ch for ch in active_channels
                  if str(ch).strip().lower() in table]
    if not configured:
        return
    # FE 는 채널마다 행이 따로라 전부 기입할 수 있다.
    for ch in configured:
        entry = table[str(ch).strip().lower()]
        if "ptat" in entry:
            bias = fh.get_fe_bias()
            pol, idx = parse_ch(ch)
            bias[fe_row(idx, pol)][0:3] = entry["ptat"]
            fh.set_fe_bias(bias)
            log(f"[bias   ] measured ptat for {ch}: {entry['ptat']}")
    # DIST 는 빔당 1행 -- 첫 채널 것만 들어간다.
    with_dist = [ch for ch in configured
                 if "dist" in table[str(ch).strip().lower()]]
    if not with_dist:
        return
    owner = with_dist[0]
    codes = table[str(owner).strip().lower()]["dist"]
    dist, ctat = fh.get_dist_bias()
    dist[beam_idx][0:3] = codes
    fh.set_dist_bias(dist, ctat)
    log(f"[bias   ] measured dist for {owner}: {codes}")
    others = with_dist[1:]
    if others:
        log(f"[bias   ] NOTE: DIST is one row per beam, so {owner}'s codes are "
            f"in effect; {', '.join(others)} also define dist and will only "
            f"take effect when chan() switches to them")


# ---------------------------------------------------------------------
# bench.toml 기입 (find_bias 가 찾은 코드를 되돌려 적는다)
# ---------------------------------------------------------------------
# 키 뒤에 붙이는 고정 주석. 코드 3개가 각각 무엇인지 파일만 봐도 알게 한다.
_INLINE = {
    "ptat": "# ptat_st1(PA), ptat_st2(DRV), ptat_st3(Comb)",
    "dist": "# dist_st1, dist_st2_0, dist_st2_1",
}
_NOTE_PREFIX = "# find_bias"
_KEY_RE = re.compile(r"\s*(ptat|dist)\s*=")
_BIAS_HEADER_RE = re.compile(r"\s*\[board\.bias\.([hv]\d)\]\s*$")


def _fmt_line(key: str, codes: list[int]) -> str:
    return f"{key} = [{', '.join(str(c) for c in codes)}]   {_INLINE[key]}"


def _section_end(lines: list[str], start: int) -> int:
    """`start` 헤더 다음의 첫 테이블 헤더 인덱스(없으면 EOF)."""
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            return i
    return len(lines)


def write_measured_bias(path, channel, *, ptat=None, dist=None,
                        note: str | None = None) -> None:
    """Write one channel's measured bias codes into a bench TOML, in place.

    Only the `ptat` / `dist` lines of `[board.bias.<channel>]` are rewritten,
    so every comment in the file survives -- reloading the document with a TOML
    library and dumping it back would throw all of them away, and this file's
    comments carry the reasoning behind the numbers.

    A `# find_bias ...` line inside the section records where the codes came
    from; rewriting the same channel replaces that line instead of stacking a
    new one. Nothing is written when the codes are rejected.
    """
    name = _check_channel(channel)
    entries: dict[str, list[int]] = {}
    if ptat is not None:
        entries["ptat"] = _check_codes(name, "ptat", ptat)
    if dist is not None:
        entries["dist"] = _check_codes(name, "dist", dist)
    if not entries:
        raise ValueError("write_measured_bias needs ptat, dist or both")

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    note_line = f"{_NOTE_PREFIX} {date.today():%Y-%m-%d}"
    if note:
        note_line += f": {note}"

    header = f"[board.bias.{name}]"
    start = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
    if start is not None:
        end = _section_end(lines, start)
        # 이 섹션 안의 옛 provenance 줄만 걷어낸다. 다른 주석은 뒤따르는 테이블의
        # 설명일 수 있어(예: [board.ch_gain] 앞 NOTE 블록) 절대 지우지 않는다.
        body = [ln for ln in lines[start + 1:end]
                if not ln.lstrip().startswith(_NOTE_PREFIX)]
        seen = set()
        for i, ln in enumerate(body):
            m = _KEY_RE.match(ln)
            if m and m.group(1) in entries:
                body[i] = _fmt_line(m.group(1), entries[m.group(1)])
                seen.add(m.group(1))
        missing = [k for k in _KEYS if k in entries and k not in seen]
        if missing:
            idxs = [i for i, ln in enumerate(body) if _KEY_RE.match(ln)]
            at = max(idxs) + 1 if idxs else 0
            body[at:at] = [_fmt_line(k, entries[k]) for k in missing]
        body.insert(0, note_line)
        lines[start + 1:end] = body
    else:
        block = [header, note_line] + [_fmt_line(k, entries[k])
                                       for k in _KEYS if k in entries]
        # 새 섹션은 기존 [board.bias.*] 묶음 끝에 붙인다 -- 파일 맨 뒤에 두면
        # TOML 로는 같지만 사람이 읽을 때 관련 없는 자리에 떨어진다.
        last = None
        for i, ln in enumerate(lines):
            if _BIAS_HEADER_RE.match(ln):
                last = i
        if last is None:
            lines += ([""] if lines and lines[-1].strip() else []) + block
        else:
            end = _section_end(lines, last)
            keys = [i for i in range(last + 1, end) if _KEY_RE.match(lines[i])]
            at = (max(keys) + 1) if keys else last + 1
            lines[at:at] = [""] + block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
