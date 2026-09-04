"""레지스터 덤프 로드/저장/비교 검증.

xlsx 형식은 실제 Sivers 레퍼런스 덤프(reference/Data_260729_DoosanSTMP_RegDump.xlsx)를
직접 열어 확인한 모양을 따른다 (Task 11 조사):
  - 시트 1개('Sheet1'), 데이터는 열 B(주소)/C(값)에 있고 열 A는 항상 비어 있다.
  - 헤더 행은 'Register Adress'/'Value' (오타 포함, 'addr'로 시작하지 않는다).
  - 주소 열은 세 가지 형식이 섞여 있다: 헥사 자릿수를 그대로 십진수로 오인식한
    int(예: 1004 -> 실제 주소 0x1004), 'XXXX' 헥사 문자열(0x 접두 없음, A-F 포함
    시), '0xXXXX' 문자열(파일 끝부분). 값 열은 항상 10진 int.
  - Excel 이 '10E0'~'10E9' 셀 10개를 지수표기 숫자(10, 100, ..., 1e10)로 자동
    변환해버려 그 10개 행의 원본 주소를 복구할 수 없다(레지스터 값은 전부 0).
    로더는 이 10개를 엉뚱한 주소(특히 기존 0x1000과 충돌하는 값)로 잘못
    흡수하면 안 되고, Ruling 34: 조용히 버려서도 안 된다 -- 건너뛴 행 수/추정
    범위를 RegDump.skipped 에 담고 로드 시점에 note 로 찍는다.
"""
from pathlib import Path

import pytest

from cloudchaser.regdump import format_skip_notes, load_dump, main, regdiff, save_dump

REAL_XLSX = (
    Path(__file__).resolve().parents[1] / "reference" / "Data_260729_DoosanSTMP_RegDump.xlsx"
)


def test_load_addr_value_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("addr,value\n0x1000,0xDC11\n0x1001,0x0000\n", encoding="utf-8")
    assert load_dump(p) == {0x1000: 0xDC11, 0x1001: 0x0000}


def test_load_values_only_csv_uses_base(tmp_path):
    """주소 없이 값만 나열된 파일(MATLAB mem_dump)은 base 부터 순차 주소."""
    p = tmp_path / "v.csv"
    p.write_text("3\n7\n", encoding="utf-8")
    assert load_dump(p, base=0x1008) == {0x1008: 3, 0x1009: 7}


def test_load_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("# note\n\n0x1000,1\n", encoding="utf-8")
    assert load_dump(p) == {0x1000: 1}


def test_save_and_reload_roundtrip(tmp_path):
    d = {0x1000: 0xDC11, 0x104C: 3378}
    p = tmp_path / "o.csv"
    save_dump(d, p)
    assert load_dump(p) == d


def test_save_dump_orders_by_address(tmp_path):
    """save_dump 는 addr 오름차순으로 써야 한다 (round-trip 만으로는 순서를 못 잡는다:
    dict 비교는 순서를 안 보므로, 정렬이 깨져도 load_dump(save_dump(d)) == d 는
    여전히 참이다 -- 그래서 raw 텍스트 줄 순서를 직접 확인한다)."""
    d = {0x1005: 1, 0x1000: 2, 0x1003: 3}
    p = tmp_path / "o.csv"
    save_dump(d, p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "addr,value"
    addrs = [int(line.split(",")[0], 16) for line in lines[1:]]
    assert addrs == sorted(addrs)


def test_regdiff_reports_only_differences(capsys):
    theirs = {0x1000: 1, 0x1001: 2, 0x1002: 3}
    ours = {0x1000: 1, 0x1001: 9, 0x1002: 3}
    diffs = regdiff(theirs, ours)
    assert diffs == [0x1001]
    out = capsys.readouterr().out
    assert "0x1001" in out
    assert "1 differing / 3 compared" in out


def test_regdiff_handles_missing_addresses(capsys):
    diffs = regdiff({0x1000: 1, 0x1005: 5}, {0x1000: 1})
    assert diffs == [0x1005]
    assert "--" in capsys.readouterr().out


def test_regdiff_reports_zero_when_identical(capsys):
    d = {0x1000: 1, 0x1001: 2}
    diffs = regdiff(d, dict(d))
    assert diffs == []
    assert "0 differing / 2 compared" in capsys.readouterr().out


def test_load_xlsx_explicit_hex_strings(tmp_path):
    """'0x'로 시작하는 헥사 문자열 주소/값은 그대로 읽는다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["addr", "value"])
    ws.append(["0x1000", "0xDC11"])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    assert load_dump(p) == {0x1000: 0xDC11}


def test_load_xlsx_int_addr_cells_are_hex_digits(tmp_path):
    """실제 Sivers 파일에서 int 로 저장된 주소 셀은 '헥사 자릿수를 그대로 십진수로
    적은 것'이다 (예: 셀 값 1004 는 주소 0x1004, 즉 int 4100). 파이썬 정수 0x1004
    (=4100) 를 그대로 넣은 게 아니다 -- Excel 이 텍스트 '1004'를 숫자로 자동
    타입변환한 결과가 이 모양이기 때문이다. 실제 파일 조사로 확인한 규칙."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])   # 실제 파일과 동일한 오타 헤더
    ws.append([1004, 15])       # -> addr 0x1004, value 15 (실제 파일 row 7과 동일)
    ws.append(["100A", 0])      # 헥사 문자열, 0x 접두 없음
    p = tmp_path / "d.xlsx"
    wb.save(p)
    assert load_dump(p) == {0x1004: 15, 0x100A: 0}


def test_load_xlsx_data_in_columns_b_c(tmp_path):
    """열 A가 항상 빈 실제 파일 레이아웃(데이터는 B/C)에서도 제대로 읽어야 한다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B1"] = "Register Adress"
    ws["C1"] = "Value"
    ws["B2"] = 1000
    ws["C2"] = 56320
    p = tmp_path / "d.xlsx"
    wb.save(p)
    assert load_dump(p) == {0x1000: 56320}


def test_load_xlsx_skips_excel_scientific_notation_corruption(tmp_path, capsys):
    """Excel 이 '10E0'~'10E9' 같은 텍스트를 지수표기 숫자로 뭉개버린 행은(원본
    주소를 복구할 수 없으므로) 건너뛰어야 한다. 특히 이걸 안 걸러내면 뭉개진
    값이 이미 읽은 다른 정상 주소(예: 0x1000)와 충돌해 그 값을 덮어쓸 위험이
    있다 -- 실제 파일의 row 227~236 이 정확히 이 패턴이라, 그 10개 값(10, 100,
    ..., 1e10 = '10E0'~'10E9'가 지수표기로 뭉개진 결과)을 그대로 재현한다.

    Ruling 34: 건너뛴 사실을 조용히 숨기면 안 된다 -- .skipped 가 (추정)
    구간과 개수를 담고, 로드 시점에 그 사실을 note 로 찍어야 한다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])
    ws.append(["10DF", 7])  # 정상 주소, 원래 시퀀스의 마지막
    # 뭉개진 '10E0'~'10E9' 10개 (전부 지수표기 -> 10, 100, ..., 1e10). 값은 실제
    # 파일과 같이 전부 0. row229(1000)는 진짜 0x1000(다른 레지스터)과 충돌할
    # 위험이 있는 값이라 절대 흡수하면 안 됨.
    for exp in range(10):
        ws.append([10 * 10 ** exp, 0])
    ws.append(["10EA", 8])  # 뭉개진 구간 뒤 다시 정상으로 복귀
    p = tmp_path / "d.xlsx"
    wb.save(p)
    d = load_dump(p)
    assert d == {0x10DF: 7, 0x10EA: 8}
    assert 0x1000 not in d
    assert d.skipped == [{"start": 0x10E0, "end": 0x10E9, "count": 10}]
    out = capsys.readouterr().out
    assert "10 row(s) at 0x10E0-0x10E9 could not be parsed and were not compared" in out


def test_load_xlsx_reports_unparseable_value_with_known_address(tmp_path, capsys):
    """주소는 멀쩡한데 값 칸이 깨진 행(예: 텍스트 'N/A')은 -- 실제 파일의
    지수표기 오염(주소가 깨짐)과 반대 방향의 실패 모드다. 이 경우는 정확한
    주소를 알고 있으므로, .skipped 가 그 구체적인 주소를 담아야 한다(범위
    추정이 아니라). 주소를 알려진 레지스터 범위(0x1000-0x1204) 안으로 잡아서
    Ruling 35 plausibility 경고가 안 섞여 들어오게 한다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])
    ws.append(["0x1100", 1])
    ws.append(["0x1101", "N/A"])   # 값 칸이 깨짐 -- 주소(0x1101)는 안전하게 안다
    ws.append(["0x1102", 2])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    d = load_dump(p)
    assert d == {0x1100: 1, 0x1102: 2}   # 나머지 정상 행은 그대로 로드됨
    assert 0x1101 not in d
    assert d.skipped == [{"start": 0x1101, "end": 0x1101, "count": 1}]
    out = capsys.readouterr().out
    assert "1 row(s) at 0x1101 could not be parsed and were not compared" in out
    assert "warning:" not in out  # 주소 자체는 알려진 범위 안이라 plausibility 경고는 없어야 함


def test_load_xlsx_warns_when_addresses_look_implausible(tmp_path, capsys):
    """Ruling 35: _addr_from_xlsx_cell 의 'int 셀 = 헥사 자릿수' 관례는 이
    Sivers 파일 전용이다. 평범한 정수-주소 관례로 만들어진 xlsx(셀 4096 이
    진짜 정수 4096 = 0x1000 을 뜻하는 경우)를 그 관례로 읽으면 주소가 전부
    엉뚱한 값(예: int('4096', 16) = 0x4096 = 16534)으로 읽히고, 그 값들은
    알려진 레지스터 범위(0x0000-0x03FF, 0x1000-0x1203) 밖으로 떨어진다.
    자동으로 해석을 바꾸지는 않지만(Ruling 35: 잘못된 추측을 조용히 적용하는
    것도 위험), 경고는 반드시 찍어야 하고 벗어난 개수를 정확히 말해야 한다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["addr", "value"])
    # 평범한 정수-주소 관례: 4096..4100 은 진짜 0x1000..0x1004 를 뜻하는
    # 의도였지만, 이 로더는 '헥사 자릿수' 관례로 읽는다.
    for addr in range(4096, 4101):
        ws.append([addr, 0])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    d = load_dump(p)
    assert len(d) == 5  # 5개 행 모두 (틀리게) 로드는 된다 -- 그게 위험한 지점
    out = capsys.readouterr().out
    assert "addresses were read assuming hex-digits-as-decimal" in out
    assert "5 of 5 parsed addresses fall outside the known register range" in out
    assert "plain decimal addresses instead" in out


def test_load_xlsx_plausibility_check_quiet_when_addresses_look_right(tmp_path, capsys):
    """정상적인(이 파일 관례에 맞는) 주소만 있으면 plausibility 경고는 없다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])
    ws.append([1004, 15])
    ws.append(["100A", 0])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    load_dump(p)
    assert "warning:" not in capsys.readouterr().out


def test_load_dump_is_quiet_when_nothing_skipped(tmp_path, capsys):
    """깨끗한 파일은 note 를 찍지 않는다."""
    p = tmp_path / "d.csv"
    p.write_text("addr,value\n0x1000,1\n0x1001,2\n", encoding="utf-8")
    d = load_dump(p)
    assert d.skipped == []
    assert capsys.readouterr().out == ""


def test_load_csv_reports_line_with_known_address_bad_value(capsys, tmp_path):
    """CSV/txt 로더도 같은 규칙을 따른다: 주소 토큰은 파싱됐는데 값 토큰이
    깨진 줄은 그 주소를 정확히 보고한다."""
    p = tmp_path / "c.csv"
    p.write_text("0x1000,1\n0x1001,garbage\n0x1002,2\n", encoding="utf-8")
    d = load_dump(p)
    assert d == {0x1000: 1, 0x1002: 2}
    assert d.skipped == [{"start": 0x1001, "end": 0x1001, "count": 1}]
    assert "1 row(s) at 0x1001 could not be parsed and were not compared" in capsys.readouterr().out


def test_diff_cli_prints_skip_note_near_diff_line(tmp_path, capsys):
    """CLI 전체 경로: --ours/--diff 둘 다 파일이면 하드웨어 없이 돌아간다.
    note 가 diff 결과("N differing / M compared") 근처에서 같이 읽혀야 한다."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])
    ws.append(["0x1000", 1])
    ws.append(["0x1001", "N/A"])
    ws.append(["0x1002", 2])
    theirs_path = tmp_path / "theirs.xlsx"
    wb.save(theirs_path)

    ours_path = tmp_path / "ours.csv"
    ours_path.write_text("addr,value\n0x1000,1\n0x1001,9\n0x1002,2\n", encoding="utf-8")

    rc = main(["--ours", str(ours_path), "--diff", str(theirs_path)])
    out = capsys.readouterr().out
    # 0x1001 was dropped from theirs (bad value cell), so regdiff sees it as
    # missing-from-theirs vs present-in-ours -> counted as a real difference.
    # That's the point: the note explains *why* 0x1001 shows up as "theirs=--"
    # instead of the reader assuming theirs and ours simply agreed there.
    assert rc == 1
    note_line = "note: 1 row(s) at 0x1001 could not be parsed and were not compared"
    diff_line = "1 differing / 3 compared"
    assert note_line in out
    assert diff_line in out
    # note appears before the final tally line, i.e. right next to the diff output
    assert out.index(note_line) < out.index(diff_line)


def test_load_xlsx_unresolved_corruption_run_does_not_crash(tmp_path, capsys):
    """Ruling 36 regression: an xlsx corruption run that NEVER resumes to a
    known-good address before end-of-file used to crash with
    'TypeError: unsupported format string passed to NoneType.__format__'
    (a skip run with a known start but an undetermined end -- start=1,
    end=None -- hit format_skip_notes' 'start == end' / else branches, both
    of which formatted `end` as hex even when it was None).

    Reproduces the reviewer's report: decimal address 0 as the first row,
    then a later row whose hex-digit reinterpretation jumps far enough to
    trip _XLSX_MAX_ADDR_GAP, with nothing afterward to resolve the run."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Register Adress", "Value"])
    ws.append([0, 1])       # accepted: addr 0x0000
    ws.append([9999, 2])    # hex-reinterpreted -> 0x9999-ish, far past the gap guard;
                             # nothing follows to resolve the run before EOF
    p = tmp_path / "d.xlsx"
    wb.save(p)

    d = load_dump(p)   # must not raise

    assert d == {0: 1}
    assert d.skipped == [{"start": 1, "end": None, "count": 1}]
    out = capsys.readouterr().out
    assert "1 row(s) starting at 0x0001" in out
    assert "end address undetermined" in out


def test_load_xlsx_1024_row_all_decimal_does_not_crash(tmp_path, capsys):
    """Same failure shape as above, reproduced closer to the reviewer's
    original 1024-row all-decimal fixture: addresses 0..1023 fed as plain
    int cells. Around addr=1000 the hex-digit reinterpretation jumps from
    ~0x999 to ~0x1000, tripping the gap guard, and the run never resolves
    (every later row keeps landing far from where it left off) -- so it's
    still open at end-of-file. Must not raise."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["addr", "value"])
    for addr in range(1024):
        ws.append([addr, 0])
    p = tmp_path / "d.xlsx"
    wb.save(p)

    d = load_dump(p)   # must not raise

    assert isinstance(d, dict)
    for run in d.skipped:
        assert isinstance(run["count"], int) and run["count"] > 0
    # whatever the split, every address actually loaded is < 1000's worth of
    # rows -- just a sanity check that something sane came out, not a crash.
    assert len(d) + sum(r["count"] for r in d.skipped) <= 1024


def test_format_skip_notes_handles_every_start_end_combination():
    """Direct unit test of Ruling 36's fix across all four start/end shapes
    -- including start=None/end=known, which no current loader path
    produces but format_skip_notes must still render safely rather than
    assume the loader will never hand it one."""
    notes = format_skip_notes([
        {"start": None, "end": None, "count": 3},
        {"start": 0x1005, "end": 0x1005, "count": 1},
        {"start": 0x1005, "end": 0x1007, "count": 3},
        {"start": 0x1005, "end": None, "count": 2},
        {"start": None, "end": 0x1007, "count": 4},
    ])
    assert notes == [
        "3 row(s) could not be parsed and were not compared",
        "1 row(s) at 0x1005 could not be parsed and were not compared",
        "3 row(s) at 0x1005-0x1007 could not be parsed and were not compared",
        "2 row(s) starting at 0x1005 (end address undetermined -- file ended "
        "before a known-good address resumed) could not be parsed and were "
        "not compared",
        "4 row(s) ending at 0x1007 (start address undetermined) could not be "
        "parsed and were not compared",
    ]


@pytest.mark.skipif(not REAL_XLSX.exists(), reason="reference xlsx not present (untracked file)")
def test_load_real_sivers_xlsx(capsys):
    """실제 Sivers 레퍼런스 덤프를 로더로 직접 읽는다(합성 테스트가 못 잡는 것을
    잡기 위한 테스트 -- 이 파일이 정본이다)."""
    d = load_dump(REAL_XLSX)
    # 0x1000..0x1203 연속 516개 중 지수표기로 뭉개진 0x10E0..0x10E9 10개만 손실.
    assert len(d) == 516 - 10
    assert min(d) == 0x1000
    assert max(d) == 0x1203
    # daisy 레지스터: bring-up 표(spec 4장) "0x1004 = 0x000F"와 일치.
    assert d[0x1004] == 0x000F
    # split-mode 값: bring-up 표 19번 "0x1009 = 783"과 일치.
    assert d[0x1009] == 783
    # 지수표기로 뭉개진 구간은 전부 빠지고, 그 앞뒤 정상 주소는 남아 있어야 한다.
    for a in range(0x10E0, 0x10EA):
        assert a not in d
    assert 0x10DF in d
    assert 0x10EA in d
    # Ruling 34: 이 10개가 조용히 사라지면 안 되고, 정확히 보고돼야 한다.
    assert d.skipped == [{"start": 0x10E0, "end": 0x10E9, "count": 10}]
    out = capsys.readouterr().out
    assert "10 row(s) at 0x10E0-0x10E9 could not be parsed and were not compared" in out
    # Ruling 35: 이 파일은 관례가 맞으므로(전부 0x1000-0x1203 안) plausibility
    # 경고는 뜨면 안 된다.
    assert "warning:" not in out
