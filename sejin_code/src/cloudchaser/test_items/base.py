"""테스트 아이템 프레임워크의 토대(베이스).

이 파일은 "모든 Test Item 이 공통으로 따르는 규격"을 정의한다. 새 테스트를 추가할 때
이 규격(특히 TestItem 클래스)만 지키면, runner 와 (나중의) GUI 가 자동으로 인식한다.

구성 요소:
- Param      : 테스트 입력 파라미터 1개의 명세. GUI 가 이걸 보고 입력 폼을 자동 생성.
- TestResult : 테스트 실행 결과(요약 + 측정 데이터 표).
- TestContext: 테스트가 쓸 수 있는 자원(계측기 bench + 보드 chip).
- TestItem   : 모든 테스트가 상속하는 추상 클래스(id/title/params/run 정의).
- coerce()   : 문자열 입력("28e9" 등)을 파라미터 타입에 맞게 변환(CLI·GUI 공용).

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# 지원하는 파라미터 타입(문자열 식별자). GUI 가 위젯 종류를 고를 때도 사용.
PARAM_TYPES = ("float", "int", "str", "bool", "choice", "int_list", "float_list")


@dataclass
class Param:
    """테스트 입력 파라미터 1개의 명세.

    name    : 코드에서 쓰는 키(예: "freq_hz")
    label   : GUI 에 표시할 사람용 라벨(예: "CW Frequency")
    type    : PARAM_TYPES 중 하나
    default : 기본값
    unit    : 단위 표시(예: "Hz", "dBm"). 없으면 빈 문자열.
    choices : type=="choice" 일 때 선택지 목록
    help    : 도움말(GUI 툴팁/CLI 설명)
    """

    name: str
    label: str
    type: str
    default: Any
    unit: str = ""
    choices: list | None = None
    help: str = ""
    rx_default: Any = None   # RX(Blueway) 측정 시 wizard 가 쓰는 기본값(None 이면 default 사용)


@dataclass
class TestResult:
    """테스트 실행 결과.

    columns/rows 는 측정 데이터를 표 형태로 담는다(그대로 CSV 저장/그래프에 사용).
    passed 는 합격 판정(없으면 None).
    """

    test_id: str
    title: str
    passed: bool | None
    summary: str                       # 사람이 읽는 한 줄 요약
    columns: list[str]                 # 데이터 표 헤더
    rows: list[list]                   # 데이터 표 행들
    meta: dict = field(default_factory=dict)  # 부가 정보(스칼라 결과 등)


@dataclass
class TestContext:
    """테스트가 사용할 자원 묶음.

    bench : 계측기 4대(PSU/SG/SA) 관리 객체 (cloudchaser.bench.Bench)
    chip  : 이미 bring-up 된 sivers_api Stampede 객체
    fake  : 가짜 모드 여부(하드웨어 없는 dry-run)
    타입을 Any 로 둔 이유: bench/board 를 import 하면 순환 참조가 되므로.
    """

    bench: Any
    chip: Any
    fake: bool = False


class TestItem(ABC):
    """모든 Test Item 이 상속하는 추상 클래스.

    새 테스트를 만들려면:
      1) 이 클래스를 상속
      2) id / title / description / params 를 채우고
      3) run() 을 구현
      4) test_items/__init__.py 의 REGISTRY 에 등록
    그러면 runner·GUI 가 자동으로 인식한다.
    """

    id: str = ""                 # 고유 식별자(예: "gain_accuracy")
    title: str = ""              # 표시 이름(예: "Gain Accuracy Test")
    description: str = ""        # 설명
    chips: tuple[str, ...] = ("tx", "rx")  # 이 테스트가 의미있는 칩 종류(wizard 필터용)
    params: list[Param] = []     # 입력 파라미터 명세 목록

    @classmethod
    def defaults(cls) -> dict:
        """파라미터 기본값 dict 반환(GUI 초기값/CLI 미입력 시 사용)."""
        return {p.name: p.default for p in cls.params}

    def resolve(self, params: dict | None) -> dict:
        """기본값 위에 사용자 입력(params)을 덮어써서 최종 파라미터 dict 생성."""
        merged = self.defaults()
        if params:
            merged.update(params)
        return merged

    @abstractmethod
    def run(self, ctx: TestContext, params: dict, log=print) -> TestResult:
        """테스트 본체. 계측기/보드를 제어해 측정하고 TestResult 를 반환한다."""
        raise NotImplementedError


def coerce(param: Param, raw: str) -> Any:
    """문자열 입력(raw)을 파라미터 타입에 맞는 값으로 변환한다.

    CLI(`--param k=v`)와 GUI(텍스트 입력) 양쪽에서 공용으로 쓴다.
    예: "28e9"→28000000000.0, "0,8,16"→[0,8,16](int_list).
    """
    t = param.type
    if t == "float":
        return float(raw)
    if t == "int":
        return int(raw, 0)          # "0x20" 같은 16진수도 허용
    if t == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if t == "choice":
        if param.choices and raw not in param.choices:
            raise ValueError(f"{param.name}: '{raw}' not in {param.choices}")
        return raw
    if t == "int_list":
        return [int(x.strip(), 0) for x in raw.split(",") if x.strip()]
    if t == "float_list":
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    return raw                        # "str"


# ----------------------------------------------------------------------
# PSU 레일 전류 로깅 헬퍼 — 모든 측정 아이템이 '전 레일 전류 + 총 Idd' 를 공통으로
# 기록하기 위한 도구. 컬럼 순서를 한 번 고정(rail_names)하고, 측정점마다 같은 순서로
# 값을 읽어 채운다(읽기 실패해도 길이가 어긋나지 않게 0 으로 채움).
# ----------------------------------------------------------------------
# read_rail_vi() 꼬리 두 열의 위치. 순서를 바꾸면 여기만 고친다.
_IDD_INDEX = -2
_PDC_INDEX = -1


def psu_rail_names(bench) -> list[str]:
    """현재 PSU 레일 이름 목록(전류 컬럼 순서 고정용).

    정적 구성(psu.rails)에서 채널 순서대로 읽는다 — PSU 통신 timeout 과 무관하게
    항상 채워지므로, 측정 시작 시 단 한 번의 read 실패로 레일별 컬럼이 통째로
    사라져 'Idd 만 기록' 되던 문제를 막는다. 순서는 read_all_vi 와 동일하게
    (bench.psus 순서) x (채널 번호 오름차순) 로 맞춘다.
    구성 접근이 안 되면 live read 로 폴백, 그것도 실패하면 빈 리스트.
    """
    try:
        names: list[str] = []
        for psu in bench.psus:
            for r in sorted(psu.rails.values(), key=lambda r: r.ch):
                names.append(r.name)
        if names:
            return names
    except Exception:  # noqa: BLE001
        pass
    try:
        return list(bench.read_all_vi().keys())
    except Exception:  # noqa: BLE001
        return []


def rail_vi_columns(rail_names: list[str]) -> list[str]:
    """레일 V/I 컬럼 헤더: 각 레일 '<name>_V','<name>_mA' + 'Idd_mA' + 'Pdc_mW'.

    Pdc 는 CSV 전용이다 -- 측정 항목들의 콘솔 로그는 Idd 만 찍으므로, 이 열을
    더해도 화면 출력은 그대로다. 매번 엑셀에서 V x I 를 손으로 계산하던 걸 없앤다.
    """
    cols: list[str] = []
    for n in rail_names:
        cols += [f"{n}_V", f"{n}_mA"]
    return cols + ["Idd_mA", "Pdc_mW"]


def rail_idd_ma(rail: list[float]):
    """read_rail_vi() 반환값에서 총 Idd[mA]. 빈 리스트면 None.

    ★ 인덱스를 호출부에 하드코딩하지 말 것. 예전엔 Idd 가 마지막 원소라 rail[-1]
    이 여섯 군데 흩어져 있었는데, Pdc 를 뒤에 붙이는 순간 전부 Pdc 를 Idd 로
    읽게 됐다. 열이 또 늘어도 호출부가 안 깨지도록 접근자로 고정한다.
    """
    return rail[_IDD_INDEX] if rail else None


def rail_pdc_mw(rail: list[float]):
    """read_rail_vi() 반환값에서 총 소비전력[mW]. 빈 리스트면 None."""
    return rail[_PDC_INDEX] if rail else None


def read_rail_vi(bench, rail_names: list[str], log=print) -> list[float]:
    """rail_names 순서대로 [V, mA] 쌍 + 합산 Idd[mA] + 총 소비전력 Pdc[mW].

    반환 길이는 항상 2*len(rail_names)+2 로 고정(컬럼과 정렬 보장). 읽기 실패 시
    0 으로 채우고 경고만 남긴다(측정을 막지 않음). 끝의 두 원소는 rail_idd_ma()/
    rail_pdc_mw() 로 꺼낸다 -- 인덱스를 직접 쓰지 말 것.

    Pdc = sum(V_i x I_i) [mW]. 반올림 전 원값으로 곱해 누적한다(레일별로 먼저
    반올림하면 6개를 더하는 동안 오차가 쌓인다).
    """
    try:
        vi = bench.read_all_vi()
    except Exception as e:  # noqa: BLE001
        log(f"[warn  ] rail V/I read failed: {e}")
        vi = {}
    out: list[float] = []
    idd = 0.0
    pdc_w = 0.0
    for n in rail_names:
        v = vi.get(n, {}).get("v", 0.0)
        i = vi.get(n, {}).get("i", 0.0)
        ma = round(i * 1000.0, 1)
        out += [round(v, 3), ma]
        idd += ma
        pdc_w += v * i
    return out + [round(idd, 1), round(pdc_w * 1000.0, 1)]
