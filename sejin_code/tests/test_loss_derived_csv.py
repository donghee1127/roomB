"""파생 loss CSV(SA_Cable_Loss_260902) 가이드레일.

2026-09-02 에 EVB -> SA 경로의 커넥터가 바뀌어 약 1 dB 손실이 늘었다. 케이블을
다시 재지 못해서, 직전 실측(260821)을 전 구간 1 dB 올린 파일을 새 날짜로 넣었다.
loss.latest_files 가 날짜 최신을 고르므로 설정 변경 없이 적용된다.

이 테스트가 지키는 것:
  - 새 파일이 실제로 선택되는가
  - 정확히 1.000 dB 만, 전 주파수에서, 균일하게 올랐는가(주파수 격자는 그대로)
  - 실측이 아니라는 표시가 파일 안에 남아 있는가
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cloudchaser.loss import latest_files, load_loss_csv

ROOT = Path(__file__).resolve().parents[1]
LOSS_DIR = ROOT / "Loss_data"
BASE = LOSS_DIR / "SA_Cable_Loss_260821.csv"
DERIVED = LOSS_DIR / "SA_Cable_Loss_260902.csv"

pytestmark = pytest.mark.skipif(
    not (BASE.exists() and DERIVED.exists()),
    reason="Loss_data CSVs not present")

SHIFT_DB = 1.0


def test_derived_file_is_the_one_selected():
    assert latest_files(LOSS_DIR)["sa"].name == DERIVED.name


def test_shift_is_exactly_one_db_at_every_point():
    old = dict(load_loss_csv(BASE))
    new = dict(load_loss_csv(DERIVED))
    assert old.keys() == new.keys(), "frequency grid must not change"
    assert old, "base file parsed empty"
    deltas = {round(new[f] - old[f], 9) for f in old}
    assert deltas == {SHIFT_DB}, f"non-uniform shift: {sorted(deltas)}"


def test_derived_file_says_it_is_not_a_measurement():
    """VNA 포맷 그대로라 실측으로 오인하기 쉽다 -- 파일이 스스로 밝혀야 한다."""
    head = DERIVED.read_text(encoding="utf-8", errors="replace")[:2000].upper()
    assert "DERIVED FILE" in head
    assert "NOT A VNA MEASUREMENT" in head
    assert BASE.name.upper() in head          # 출처를 명시
