"""Test Item 레지스트리.

모든 테스트 아이템을 한 곳에 모아 등록한다. runner 와 (나중의) GUI 는 여기서
사용 가능한 테스트 목록을 가져온다.

★ 새 테스트 추가 방법:
   1) test_items/ 에 새 모듈 작성 (TestItem 상속)
   2) 아래 import 에 추가
   3) _ALL 리스트에 클래스 추가
   끝. runner/GUI 가 자동으로 인식한다.
"""

from __future__ import annotations

from .acp import ACPTest
from .base import Param, TestContext, TestItem, TestResult, coerce
from .channel_gain_alignment import ChannelGainAlignmentTest
from .evm import EVMTest
from .gain_index_accuracy import GainIndexAccuracyTest
from .ip1db import IP1dBTest
from .op1db import OP1dBTest
from .phase_index_accuracy import PhaseIndexAccuracyTest
from .vdd_sensitivity import VDDSensitivityTest

# 등록된 모든 테스트 클래스(추가 시 여기에 한 줄).
_ALL: list[type[TestItem]] = [
    OP1dBTest,
    GainIndexAccuracyTest,
    ChannelGainAlignmentTest,
    EVMTest,
    ACPTest,
    IP1dBTest,
    PhaseIndexAccuracyTest,
    VDDSensitivityTest,
]

# id -> 클래스 매핑(레지스트리)
REGISTRY: dict[str, type[TestItem]] = {t.id: t for t in _ALL}


def get_test(test_id: str) -> type[TestItem]:
    """id 로 테스트 클래스를 찾는다. 없으면 KeyError."""
    if test_id not in REGISTRY:
        raise KeyError(f"unknown test id '{test_id}'. available: {list(REGISTRY)}")
    return REGISTRY[test_id]


def list_tests() -> list[type[TestItem]]:
    """등록된 모든 테스트 클래스 목록(GUI 테스트 선택 목록용)."""
    return list(_ALL)


__all__ = ["Param", "TestContext", "TestItem", "TestResult", "coerce",
           "REGISTRY", "get_test", "list_tests"]
