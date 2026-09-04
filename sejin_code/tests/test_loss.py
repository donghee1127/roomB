"""경로 손실(VNA CSV) 조회 로직 테스트 -- max(S12,S21) + cable + trace/2."""

from __future__ import annotations

import pytest

from cloudchaser.loss import (
    get_loss,
    latest_files,
    load_loss_csv,
    loss_table,
)

# 최소 VNA CSV: 헤더 몇 줄 + PNT 헤더 + 데이터 2행.
# 컬럼: PNT,FREQ1,LOGMAG1(S11),PHASE1,FREQ2,LOGMAG2(S12),PHASE2,
#       FREQ3,LOGMAG3(S21),PHASE3,FREQ4,LOGMAG4(S22),PHASE4
def _csv(rows: list[tuple[float, float, float]]) -> str:
    """rows = [(freq_ghz, s12_db, s21_db), ...] -> VNA CSV 문자열."""
    head = (
        "MS4644B\n!comment\n!IF.BANDWIDTH: 1KHZ\n"
        "PNT,FREQ1.GHZ,LOGMAG1,PHASE1.DEG,FREQ2.GHZ,LOGMAG2,PHASE2.DEG,"
        "FREQ3.GHZ,LOGMAG3,PHASE3.DEG,FREQ4.GHZ,LOGMAG4,PHASE4.DEG\n"
    )
    body = ""
    for i, (f, s12, s21) in enumerate(rows, start=1):
        body += (f"{i},{f},-40,0,{f},{s12},0,{f},{s21},0,{f},-40,0\n")
    return head + body


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(_csv(rows), encoding="utf-8")
    return p


def test_load_loss_csv_takes_max_abs(tmp_path):
    # S12=-3.0, S21=-3.2 -> loss = max(3.0, 3.2) = 3.2
    p = _write(tmp_path, "SG_Cable_Loss_260626.csv",
               [(28.0, -3.0, -3.2), (30.0, -4.0, -3.9)])
    rows = load_loss_csv(p)
    assert rows == [(28.0e9, 3.2), (30.0e9, 4.0)]


def _write_set(tmp_path, date="260626", sg=None, sa=None, tr=None):
    sg = sg or [(28.0, -3.0, -2.8), (30.0, -3.0, -2.8)]   # loss 3.0
    sa = sa or [(28.0, -1.0, -0.9), (30.0, -1.0, -0.9)]   # loss 1.0
    tr = tr or [(28.0, -2.0, -1.9), (30.0, -2.0, -1.9)]   # loss 2.0
    _write(tmp_path, f"SG_Cable_Loss_{date}.csv", sg)
    _write(tmp_path, f"SA_Cable_Loss_{date}.csv", sa)
    _write(tmp_path, f"Board_Trace_Loss_{date}.csv", tr)


def test_get_loss_cable_plus_half_trace(tmp_path):
    _write_set(tmp_path)
    il, ol = get_loss(28.0e9, tmp_path)
    assert il == pytest.approx(3.0 + 2.0 / 2)   # sg + trace/2 = 4.0
    assert ol == pytest.approx(1.0 + 2.0 / 2)   # sa + trace/2 = 2.0


def test_get_loss_interpolates(tmp_path):
    _write_set(tmp_path)
    # 29 GHz = 28/30 중간. 값이 일정하므로 동일.
    il, ol = get_loss(29.0e9, tmp_path)
    assert il == pytest.approx(4.0)
    assert ol == pytest.approx(2.0)


def test_get_loss_clamps_out_of_range(tmp_path):
    _write_set(tmp_path)
    assert get_loss(10.0e9, tmp_path) == get_loss(28.0e9, tmp_path)
    assert get_loss(40.0e9, tmp_path) == get_loss(30.0e9, tmp_path)


def test_latest_files_picks_newest_date(tmp_path):
    _write_set(tmp_path, date="260101")
    _write_set(tmp_path, date="260626")
    files = latest_files(tmp_path)
    assert files["sg"].name == "SG_Cable_Loss_260626.csv"
    assert files["sa"].name == "SA_Cable_Loss_260626.csv"
    assert files["trace"].name == "Board_Trace_Loss_260626.csv"


def test_latest_files_picks_newest_per_kind_independently(tmp_path):
    """종류별로 따로 최신을 고른다 -- 케이블만 다시 재고 board trace 는 예전 것을
    그대로 쓰는 경우(실제 2026-08-21 상황: SG/SA=260821, trace=260626)."""
    _write_set(tmp_path, date="260626")
    _write(tmp_path, "SG_Cable_Loss_260821.csv", [(28.0, -9.0, -9.0)])
    _write(tmp_path, "SA_Cable_Loss_260821.csv", [(28.0, -7.0, -7.0)])
    files = latest_files(tmp_path)
    assert files["sg"].name == "SG_Cable_Loss_260821.csv"
    assert files["sa"].name == "SA_Cable_Loss_260821.csv"
    assert files["trace"].name == "Board_Trace_Loss_260626.csv"   # 갱신 안 된 종류는 유지


def test_latest_files_date_beats_mtime(tmp_path):
    """오래된 파일을 나중에 복사해 mtime 이 더 새것이어도, 파일명 날짜가 이긴다.
    (실험 PC <-> 개발 PC 로 CSV 를 옮기면 mtime 은 쉽게 뒤집힌다.)"""
    import os
    import time
    _write_set(tmp_path, date="260821")
    old = _write(tmp_path, "SG_Cable_Loss_260101.csv", [(28.0, -1.0, -1.0)])
    os.utime(old, (time.time() + 3600, time.time() + 3600))   # 미래 mtime
    assert latest_files(tmp_path)["sg"].name == "SG_Cable_Loss_260821.csv"


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_loss(28.0e9, tmp_path / "nope")


def test_missing_kind_raises(tmp_path):
    _write(tmp_path, "SG_Cable_Loss_260626.csv", [(28.0, -3.0, -3.0)])
    with pytest.raises(FileNotFoundError):
        latest_files(tmp_path)   # SA / trace 없음


def test_header_only_csv_raises(tmp_path):
    # PNT 헤더만 있고 데이터 행이 없는 파일 -- ValueError 를 기대.
    p = tmp_path / "SG_Cable_Loss_260626.csv"
    p.write_text(
        "MS4644B\nPNT,FREQ1.GHZ,LOGMAG1,PHASE1.DEG,FREQ2.GHZ,LOGMAG2,"
        "PHASE2.DEG,FREQ3.GHZ,LOGMAG3,PHASE3.DEG,FREQ4.GHZ,LOGMAG4,PHASE4.DEG\n",
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_loss_csv(p)


def test_loss_table_handles_unparseable(tmp_path):
    # SA / trace 정상, SG 는 헤더만 있는 파일(파싱 불가) -> loss_table 이 친절한 메시지 반환.
    _write_set(tmp_path)  # 정상 3종 작성
    (tmp_path / "SG_Cable_Loss_260626.csv").write_text(
        "MS4644B\nPNT,FREQ1.GHZ,LOGMAG1,PHASE1.DEG,FREQ2.GHZ,LOGMAG2,"
        "PHASE2.DEG,FREQ3.GHZ,LOGMAG3,PHASE3.DEG,FREQ4.GHZ,LOGMAG4,PHASE4.DEG\n",
        encoding="utf-8")
    out = loss_table(tmp_path)
    assert "unavailable" in out.lower()


# --- VNA 저장 형식 차이(PHASE 열 유무) -------------------------------------
# MS4644B 는 저장 설정에 따라 PHASE 열을 빼고 내보낸다(260820 파일이 그 경우).
# 열 번호를 고정해두면 FREQ3 를 S12 로, LOGMAG4(S22) 를 S21 로 읽어서
# "loss = 주파수 숫자" 라는 조용히 틀린 값이 나온다.
def _csv_no_phase(rows: list[tuple[float, float, float]]) -> str:
    """PHASE 열이 없는 4-trace CSV. 컬럼: PNT,FREQ1,LOGMAG1,FREQ2,LOGMAG2,..."""
    head = (
        "MS4644B\n!comment\n!IF.BANDWIDTH: 1KHZ\n"
        "PNT,FREQ1.GHZ,LOGMAG1,FREQ2.GHZ,LOGMAG2,FREQ3.GHZ,LOGMAG3,"
        "FREQ4.GHZ,LOGMAG4\n"
    )
    body = ""
    for i, (f, s12, s21) in enumerate(rows, start=1):
        body += f"{i},{f},-40,{f},{s12},{f},{s21},{f},-40\n"
    return head + body


def test_load_loss_csv_without_phase_columns(tmp_path):
    """PHASE 열이 없는 형식도 S12/S21 을 올바로 읽는다(주파수를 loss 로 읽지 않는다)."""
    p = tmp_path / "SA_Cable_Loss_260820.csv"
    p.write_text(_csv_no_phase([(28.0, -3.5, -3.6), (29.0, -3.8, -3.7)]),
                 encoding="utf-8")
    rows = load_loss_csv(p)
    assert rows == [(28.0e9, 3.6), (29.0e9, 3.8)]
    # 회귀 방지: 열을 고정하던 시절엔 FREQ3(=28.0)가 loss 로 읽혔다.
    assert rows[0][1] != pytest.approx(28.0)


def test_load_loss_csv_both_formats_agree(tmp_path):
    """같은 측정값이면 PHASE 유무와 무관하게 동일한 테이블이 나와야 한다."""
    data = [(28.0, -3.5, -3.6), (29.0, -3.8, -3.7)]
    a = tmp_path / "SA_Cable_Loss_260101.csv"
    a.write_text(_csv(data), encoding="utf-8")
    b = tmp_path / "SA_Cable_Loss_260102.csv"
    b.write_text(_csv_no_phase(data), encoding="utf-8")
    assert load_loss_csv(a) == load_loss_csv(b)


def test_load_loss_csv_rejects_header_missing_traces(tmp_path):
    """필요한 트레이스가 없는 헤더는 조용히 넘어가지 않고 명확히 실패한다."""
    p = tmp_path / "SA_Cable_Loss_260820.csv"
    p.write_text("MS4644B\nPNT,FREQ1.GHZ,LOGMAG1\n1,28.0,-3.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LOGMAG2"):
        load_loss_csv(p)


def test_get_loss_warns_when_frequency_outside_table(tmp_path, capsys):
    """범위 밖 주파수는 clamp 되므로, 어느 파일이 얼마나 모자라는지 알려야 한다."""
    _write_set(tmp_path)          # 28~30 GHz
    msgs: list[str] = []
    get_loss(19.5e9, tmp_path, log=msgs.append)
    assert len(msgs) == 1
    assert "19.500 GHz is outside" in msgs[0]
    assert "clamped" in msgs[0]
    assert "SG_Cable_Loss_260626.csv" in msgs[0]


def test_get_loss_quiet_when_frequency_in_range(tmp_path):
    """범위 안이면 경고하지 않는다(늑대를 외치는 경고는 무시당한다)."""
    _write_set(tmp_path)
    msgs: list[str] = []
    get_loss(29.0e9, tmp_path, log=msgs.append)
    assert msgs == []


def test_loss_table_shows_coverage_and_marks_clamped(tmp_path):
    """loss() 출력이 '이 표가 내 주파수를 덮는가'에 답해야 한다.

    파일 이름만 찍으면 260820(27-32GHz) 처럼 좁은 표를 받았을 때
    범위 밖 값이 정상값처럼 보인다.
    """
    _write_set(tmp_path)          # 28~30 GHz
    out = loss_table(tmp_path)
    assert "28.00-30.00 GHz" in out          # 커버리지 표시
    assert "CLAMPED" in out                  # 18/19.5/21 GHz 행
    # 범위 안 주파수 행에는 CLAMPED 가 붙지 않는다.
    in_range = [ln for ln in out.splitlines() if ln.strip().startswith("29.00")]
    assert in_range and "CLAMPED" not in in_range[0]
