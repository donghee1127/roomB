"""bench.toml 로딩 + 계측기 4대(전원 2대 / SG / SA) 통합 관리.

Bench 객체 하나가 '시험대 전체'를 대표한다. 계측기 연결, 전원 램프업/다운,
V/I 측정, SG/SA 셋업을 한 곳에서 다룬다. 모든 하드웨어 설정값은 코드가 아니라
config/bench.toml 에서 읽어오므로, 환경이 바뀌면 toml 만 고치면 된다.

전원 램프 순서: 두 PSU 에 걸친 ``power_up_stages`` (스테이지별 레일 이름 묶음)를
따른다. 한 스테이지 안의 레일은 함께(lockstep) 올리고, 스테이지 사이는
``stage_delay_s`` 이상 쉰다 — Sivers 확정 타이밍 다이어그램의 "min 500 ms between
each successive voltage-transition step" 요구다. toml 에 스테이지가 없으면
기존 ``power_up_order`` (레일 1개 = 스테이지 1개, 대기 없음)로 동작한다.
파워다운은 ``power_down_stages`` 의 plateau 를 따라 내려간다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import math
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .board.bias_measured import parse_measured_bias
from .board.bringup import BoardConfig
from .instruments import E36313A, FSVA3030, MS4644B, Rail, SMW200A
from .instruments.psu_e36313a import TripError
from .instruments.scpi import ScpiError
from .loss import get_loss


@dataclass
class Bench:
    """시험대 전체(계측기 4대 + 보드 설정 + 램프 파라미터)를 담는 컨테이너."""

    psu1: E36313A           # 전원공급기 1 (FE1/CORE/IO 레일)
    psu2: E36313A           # 전원공급기 2 (DIG/FE2/FE3 레일)
    sg: SMW200A             # 신호발생기
    sa: FSVA3030            # 스펙트럼 분석기
    board: BoardConfig      # 보드 bring-up 설정
    sg_cfg: dict            # toml [sg] 섹션 원본(주파수/레벨 등)
    sa_cfg: dict            # toml [sa] 섹션 원본(center/span 등)
    step_v: float           # 램프 1스텝 전압 증가량[V]
    settle_s: float         # 스텝 사이 안정화 대기[s]
    power_up_order: list[str]  # 레일 이름의 파워업 순서(스테이지를 평탄화한 것)
    fake: bool              # True 면 하드웨어 없이 동작
    # 파워업 스테이지: 한 묶음 안의 레일은 함께 올리고, 묶음 사이는 stage_delay_s 대기.
    power_up_stages: list[list[str]] = field(default_factory=list)
    stage_delay_s: float = 0.0   # 스테이지 사이 최소 대기[s]
    # toml 이 power_up_stages 를 직접 선언했는가(= 벤더 시퀀스가 확정된 보드인가).
    # False 면 power_up_order 를 레일 1개=스테이지 1개로 정규화한 것이다.
    staged: bool = False
    # 파워다운 계단식 강하 plateau(내림차순 전압). 비면 기존 역순 독립 강하로 fallback.
    power_down_stages: list[float] = field(default_factory=list)
    chip_kind: str = "tx"   # 'tx'(Stampede) or 'rx'(Blueway) — bring-up/chip 식별용
    _loss_override: tuple[float, float] | None = None  # 수동 loss override(set_loss)
    # VNA(MS4644B)는 옵션 장비: [vna] 섹션이 있을 때만 생성되고, connect_all 대상이
    # 아니다(phase_index_accuracy 실행 시 get_vna() 로 lazy connect). 그래서 VNA 가
    # 꺼져 있거나 없어도 기존 세션/측정은 영향받지 않는다.
    vna: MS4644B | None = None

    # -- 빌드(toml → Bench) ---------------------------------------------
    @classmethod
    def from_toml(cls, path: str | Path, *, fake: bool) -> "Bench":
        """bench.toml 을 읽어 Bench 객체를 만든다."""
        cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))

        def make_psu(sec: dict, label: str) -> E36313A:
            """toml 의 PSU 섹션(rails 배열 포함)으로 E36313A 드라이버를 만든다."""
            rails = [Rail(ch=r["ch"], name=r["name"], v_target=r["v_target"],
                         i_limit=r["i_limit"], ovp=r["ovp"],
                         detect=r.get("detect", False),
                         detect_v=r.get("detect_v")) for r in sec["rails"]]
            return E36313A(sec["host"], rails, port=sec.get("port", 5025),
                           fake=fake, name=label,
                           trip_poll=sec.get("trip_poll", True))

        ramp = cfg["ramp"]
        # 파워업 스테이지. toml 에 power_up_stages 가 있으면 그걸 쓰고, 없으면 기존
        # power_up_order 를 '레일 1개 = 스테이지 1개'로 정규화한다(동작 동일).
        stages_raw = ramp.get("power_up_stages")
        staged = bool(stages_raw)
        if stages_raw:
            stages = [list(s) for s in stages_raw]
            order = [n for s in stages for n in s]
        else:
            order = list(ramp["power_up_order"])
            stages = [[n] for n in order]
        board_raw = cfg["board"]
        # [board] 섹션을 BoardConfig 로 변환. ch_gain/ch_atten 값은 int 로 정규화.
        board = BoardConfig(
            chip_id=board_raw.get("chip_id", 0),
            beam=board_raw.get("beam", "b0"),
            active_channels=board_raw.get("active_channels", ["h0", "h1", "h2", "h3"]),
            cal_freq_code=board_raw.get("cal_freq_code", 0x0),
            common_gain=board_raw.get("common_gain", 0x00),
            ch_gain={k: int(v) for k, v in board_raw.get("ch_gain", {}).items()},
            ch_atten={k: int(v) for k, v in board_raw.get("ch_atten", {}).items()},
            ch_fe_attn={k: int(v) for k, v in board_raw.get("ch_fe_attn", {}).items()},
            split_mode=bool(board_raw.get("split_mode", True)),
            optimized_bias=bool(board_raw.get("optimized_bias", True)),
            dist_st2_1_ptat=int(board_raw.get("dist_st2_1_ptat", 13)),
            run_efuse_init=bool(board_raw.get("run_efuse_init", False)),
            measured_bias=parse_measured_bias(board_raw.get("bias", {})),
        )
        # [vna] 섹션은 옵션 — 있으면 드라이버만 만들고 연결은 안 한다(lazy).
        vna_sec = cfg.get("vna")
        vna = (MS4644B(vna_sec["host"], port=vna_sec.get("port", 5001),
                       timeout=vna_sec.get("timeout", 10.0), fake=fake)
               if vna_sec else None)
        return cls(
            psu1=make_psu(cfg["psu1"], "PSU1"),
            psu2=make_psu(cfg["psu2"], "PSU2"),
            sg=SMW200A(cfg["sg"]["host"], port=cfg["sg"].get("port", 5025), fake=fake),
            sa=FSVA3030(cfg["sa"]["host"], port=cfg["sa"].get("port", 5025), fake=fake),
            vna=vna,
            board=board,
            sg_cfg=cfg["sg"],
            sa_cfg=cfg["sa"],
            step_v=ramp["step_v"],
            settle_s=ramp["settle_s"],
            power_up_order=order,
            power_up_stages=stages,
            staged=staged,
            stage_delay_s=ramp.get("stage_delay_s", 0.0),
            power_down_stages=ramp.get("power_down_stages", []),
            fake=fake,
        )

    # -- 연결 -----------------------------------------------------------
    @property
    def psus(self) -> list[E36313A]:
        """전원공급기 2대 리스트."""
        return [self.psu1, self.psu2]

    @property
    def instruments(self):
        """계측기 4대 전체 리스트(연결/해제 일괄 처리용)."""
        return [self.psu1, self.psu2, self.sg, self.sa]

    def connect_all(self, log=print) -> None:
        """계측기 4대를 모두 연결하고, 각자의 에러 큐를 비운다."""
        for inst in self.instruments:
            inst.connect()
            log(f"[connect] {inst.name} @ {inst.host}:{inst.port}"
                + (" (fake)" if inst.fake else ""))
            # 시작 전에 에러 큐를 비운다. 과거에 쌓인 stale 에러(예: 부팅 시
            # 일시적 LAN IP 충돌)는 경고만 하고 진행한다 — 그래야 '우리 명령이
            # 만든 에러'만 이후 단계에서 정확히 잡아낼 수 있다.
            inst.clear_status()
            stale = inst.drain_errors()
            for e in stale:
                log(f"[warn  ] {inst.name} stale error in queue at startup "
                    f"(ignored): {e}")

    def close_all(self) -> None:
        """계측기 소켓을 모두 닫는다. (전원 출력은 끄지 않음 — '측정 직전 상태' 유지)"""
        for inst in self.instruments:
            inst.close()
        if self.vna is not None:
            self.vna.close()   # 미연결이어도 안전(close 가 _sock 가드)

    def get_vna(self, log=print) -> MS4644B:
        """VNA 핸들을 반환한다(필요 시 lazy connect).

        VNA 는 connect_all 대상이 아니므로, 이를 쓰는 측정(phase_index_accuracy)이
        처음 부를 때 여기서 연결한다. 이미 연결돼 있으면 그대로 반환(idempotent).
        [vna] 섹션이 없으면 설정 방법을 안내하는 에러를 던진다.
        """
        if self.vna is None:
            raise ScpiError(
                "no [vna] section in bench toml -- add host/port for the "
                "Anritsu MS4644B to run VNA-based tests")
        if self.vna._sock is None and not self.vna.fake:
            self.vna.connect()
            log(f"[connect] {self.vna.name} @ {self.vna.host}:{self.vna.port}")
            self.vna.clear_status()
            for e in self.vna.drain_errors():
                log(f"[warn  ] {self.vna.name} stale error in queue at startup "
                    f"(ignored): {e}")
        return self.vna

    def _psu_for_rail(self, name: str) -> E36313A:
        """레일 이름으로 그 레일이 속한 PSU 를 찾아 반환한다."""
        for psu in self.psus:
            if psu.has_rail(name):
                return psu
        raise KeyError(f"rail '{name}' in power_up_order not found on any PSU")

    def rail(self, name: str) -> Rail:
        """레일 이름으로 Rail 설정(전압/전류제한/detect_v 등)을 찾아 반환한다."""
        return self._psu_for_rail(name).rails[name]

    @property
    def detect_rail_names(self) -> list[str]:
        """chip auto-detect 1단계에서 켜는 레일(= toml 의 detect=true) 이름들.

        power_up_order 순서를 따른다. 이 레일들은 TX/RX 양쪽에서 전압이 동일해야
        하며(SPI 만 살리는 안전 레일), 보드 종류 확정 전에 먼저 켜도 안전하다.
        """
        marked = {r.name for psu in self.psus for r in psu.rails.values() if r.detect}
        return [n for n in self.power_up_order if n in marked]

    # -- 전원 시퀀스 ----------------------------------------------------
    def power_up(self, log=print, *, rails: list[str] | None = None,
                 detect_stage: bool = False) -> dict:
        """보호 설정 → (지정한) 레일 스테이지별 램프업 → 전체 V/I 측정.

        rails=None 이면 power_up_stages 전체를 올린다. rails 를 주면 그 이름들만
        남긴 스테이지를 순서대로 올린다(2단계 전원: 감지 레일 먼저, 그 다음 FE).
        한 스테이지 안의 레일은 함께(lockstep) 올라가고, 스테이지 사이에는
        stage_delay_s 만큼 쉰다(다이어그램의 min 500 ms).

        detect_stage=True 면 detect_v 가 설정된 레일을 그 중간 전압까지만 올린다
        (보드 종류 확정 전 TX/RX 공용 안전 전압). 확정 후 다시 power_up 에
        그 레일을 넘기면 현재 전압에서 v_target 까지 이어서 올라간다.

        보호(전류제한+OVP)는 '아직 0V 인 레일'에만 건다. 그래야 2단계에서 이미
        켜진 감지 레일을 VOLT 0 으로 건드려 brownout 시키지 않는다.

        반환: 레일별 측정 V/I dict.
        """
        if rails is None:
            stages = [list(s) for s in self.power_up_stages]
        else:
            want = set(rails)
            stages = [[n for n in s if n in want] for s in self.power_up_stages]
        stages = [s for s in stages if s]
        to_ramp = [n for s in stages for n in s]
        # 1) 아직 0V 인 레일에만 보호(전류제한+OVP) 설정. 이미 켜진 레일은 건드리지
        #    않는다 -- apply_protection 은 VOLT 0 을 걸어 brownout 을 일으킨다.
        ramp_set = {n for n in to_ramp
                    if self._psu_for_rail(n)._set_v.get(
                        self._psu_for_rail(n).rails[n].ch, 0.0) <= 0.0}
        if ramp_set:
            for psu in self.psus:
                psu.apply_protection(log=log, only=ramp_set)
            log(f"[power ] protection set for: "
                f"{', '.join(n for n in to_ramp if n in ramp_set)}")
        # 2) 스테이지 순서대로 올린다. 스테이지 사이에는 stage_delay_s 대기.
        for i, stage in enumerate(stages):
            if i:
                time.sleep(self.stage_delay_s)
            self._ramp_stage_up(stage, log=log, detect_stage=detect_stage)
        # 3) 올라간 뒤 실제 전압/전류를 측정해 보고한다(보드 상태 첫 신호).
        vi = self.read_all_vi()
        for name, m in vi.items():
            log(f"  {name}: {m['v']:.3f} V  {m['i']*1000:.1f} mA")
        return vi

    def _ramp_stage_up(self, names: list[str], *, log=print,
                       detect_stage: bool = False) -> None:
        """한 스테이지의 레일들을 현재 전압에서 목표 전압까지 함께(lockstep) 올린다.

        각 라운드마다 대상 레일을 모두 한 스텝씩 올린 뒤 settle_s 한 번 대기하고
        트립을 확인한다. 이미 목표에 도달한 레일은 건드리지 않으므로, 같은 레일이
        든 호출을 반복해도 0V 로 떨어졌다 올라가는 글리치가 없다.
        detect_stage=True 면 detect_v 가 있는 레일은 그 중간 전압까지만 올린다.
        """
        targets = []
        for n in names:
            psu = self._psu_for_rail(n)
            r = psu.rails[n]
            goal = (r.detect_v if (detect_stage and r.detect_v is not None)
                    else r.v_target)
            start = psu._set_v.get(r.ch, 0.0)
            if start < goal - 1e-6:
                targets.append((psu, r, goal, start))
                log(f"[ramp-up] {n} -> {goal:.2f}V")
        if not targets:
            return
        for psu, r, _, _ in targets:
            psu.output(True, [r.ch])   # 출력 ON (전압은 아직 현재값)
        # 스텝 전압은 시작값 기준으로 k 배해서 계산한다(누적 덧셈은 오차가 쌓여
        # 마지막 값이 목표에 정확히 안 맞는다). ceil 이라 마지막 스텝에서 목표 도달.
        max_k = max(math.ceil((g - s) / self.step_v) for _, _, g, s in targets)
        for k in range(1, max_k + 1):
            moving = []
            for psu, r, g, s in targets:
                v = min(g, s + self.step_v * k)
                if v > psu._set_v.get(r.ch, 0.0) + 1e-9:
                    psu.set_voltage(r.ch, v)
                    moving.append((psu, r))
            if not moving:
                continue
            time.sleep(self.settle_s)
            for psu, r in moving:
                if psu.tripped(r.ch):
                    raise TripError(
                        f"{psu.name} ch{r.ch}({r.name}) protection tripped during "
                        f"ramp-up @ {psu._set_v.get(r.ch, 0.0):.2f}V")

    def power_down(self, log=print) -> None:
        """전원을 안전하게 내린다.

        power_down_stages 가 설정돼 있으면 데이터시트 6.3 계단식 강하를 따른다:
        각 plateau 전압에서 '현재 전압이 그보다 높은 레일'을 모두 그 plateau 까지
        함께(lockstep) 내린다. 예) Stampede [1.8,1.0,0]: FE1 4->1.8, 전 1.8V 레일
        ->1V, 전체(VDD_DIG 포함)->0. plateau 사이에는 stage_delay_s 만큼 쉰다.
        각 레일의 목표전압이 아니라 '현재 인가 전압'(_set_v)을 기준으로 하므로,
        어떤 이유로 낮게 인가된 레일은 위로 올라가지 않고 자기보다 낮은 plateau
        부터만 하강한다.

        stages 가 비어 있으면 기존 방식(power_up_order 역순, 레일별 독립 강하)으로
        fallback 한다.
        """
        if not self.power_down_stages:
            for name in reversed(self.power_up_order):
                psu = self._psu_for_rail(name)
                psu.ramp_rail_down(name, step_v=self.step_v, settle_s=self.settle_s)
                log(f"[ramp-dn] {name} -> 0V")
            return
        for i, plateau in enumerate(self.power_down_stages):
            if i:
                time.sleep(self.stage_delay_s)   # plateau 사이 min 500 ms
            self._ramp_group_to(plateau, log=log)
        # 0V 도달 후 전 채널 출력 OFF.
        for psu in self.psus:
            psu.output(False)

    def _ramp_group_to(self, plateau: float, *, log=print) -> None:
        """두 PSU 를 통틀어 현재 전압이 plateau 보다 높은 레일들을 그 plateau 까지
        step_v 간격으로 함께(lockstep) 내린다. 각 라운드마다 대상 레일을 모두 한 스텝
        내린 뒤 settle_s 한 번 대기하고, 남은 레일이 없을 때까지 반복한다."""
        eps = 1e-6

        def above():
            out = []
            for psu in self.psus:
                for r in psu.rails.values():
                    cur = psu._set_v.get(r.ch, r.v_target)
                    if cur > plateau + eps:
                        out.append((psu, r))
            return out

        group = above()
        if not group:
            return
        names = ", ".join(r.name for _, r in group)
        log(f"[ramp-dn] {names} -> {plateau:.2f}V")
        while True:
            remaining = above()
            if not remaining:
                break
            for psu, r in remaining:
                cur = psu._set_v.get(r.ch, r.v_target)
                nv = max(plateau, cur - self.step_v)
                if nv - plateau < eps:
                    nv = plateau      # 누적 부동소수 오차를 plateau 로 스냅
                psu.set_voltage(r.ch, nv)
            time.sleep(self.settle_s)

    # -- 개별 레일 전압 조정(전압 민감도 측정용) -------------------------
    def rail_nominal_v(self, name: str) -> float:
        """레일의 정격(= bench.toml v_target) 전압[V]. 측정 후 복구 기준값."""
        return self._psu_for_rail(name).rails[name].v_target

    def set_rail_voltage(self, name: str, v: float, *, log=print) -> float:
        """레일 하나를 '현재 인가 전압'에서 v[V] 까지 step_v 간격으로 램프한다.

        ramp_rail(0->target) / ramp_rail_down(->0) 과 달리 임의의 중간 전압으로
        옮긴다. vdd_sensitivity 처럼 정격 아래로 내렸다가 되돌리는 측정에 쓴다.
        올릴 때는 ramp_rail 과 같이 스텝마다 트립을 확인한다(보드 보호).

        가드: 음수 거부 + 정격(v_target) 초과 거부 — toml 에 적힌 목표 위로는
        어떤 파라미터를 넣어도 올라가지 않는다(OVP/보드 과전압 사고 방지).
        반환: 실제로 인가한 전압[V].
        """
        psu = self._psu_for_rail(name)
        r = psu.rails[name]
        eps = 1e-6
        if v < -eps:
            raise ValueError(f"rail '{name}': negative voltage {v} V not allowed")
        if v > r.v_target + eps:
            raise ValueError(f"rail '{name}': {v} V exceeds its configured "
                             f"target {r.v_target} V (bench.toml) - refusing")
        v = max(0.0, min(v, r.v_target))
        cur = psu._set_v.get(r.ch, r.v_target)
        if abs(cur - v) <= eps:
            return v
        rising = v > cur
        while abs(cur - v) > eps:
            cur = min(v, cur + self.step_v) if rising else max(v, cur - self.step_v)
            psu.set_voltage(r.ch, cur)
            time.sleep(self.settle_s)
            if rising and psu.tripped(r.ch):
                raise TripError(f"{psu.name} ch{r.ch}({name}) protection tripped "
                                f"while ramping to {v:.2f}V (at {cur:.2f}V)")
        log(f"[rail   ] {name} -> {v:.2f}V")
        return v

    # -- 경로 손실 -> 계측기 오프셋 -------------------------------------
    def apply_path_loss(self, freq_hz: float, *, channel: str | None = None,
                        log=print) -> tuple[float, float]:
        """주파수의 경로 손실을 SG·SA 오프셋으로 '계측기에' 적용한다.

        - in_loss = sg_cable + trace/2, out_loss = sa_cable + trace/2 (Loss_data CSV).
        - SG: level offset = -(in_loss) -> set_level(P) 가 'DUT 입력 P' 를 의미(출력은
          P+in_loss 로 부스트). SA: ref level offset = +out_loss -> 읽기 = DUT 출력.
        - 수동 override(set_loss_override)가 있으면 CSV 대신 그 값을 쓴다.
        - channel 인자는 하위호환용으로 받기만 하고 무시한다(trace 는 채널 무관).
        - fake 모드에서 CSV 가 없으면 0 dB 로 경고만(실제 측정은 에러로 막는다).
        반환: (in_loss, out_loss) [dB] (CSV meta 기록용).
        """
        if self._loss_override is not None:
            in_loss, out_loss = self._loss_override
            src = "manual"
        else:
            try:
                in_loss, out_loss = get_loss(freq_hz, log=log)
                src = "csv"
            except FileNotFoundError as e:
                if not self.fake:
                    raise
                in_loss, out_loss = 0.0, 0.0
                src = "no-cal(fake)"
                log(f"[loss  ] WARNING: {e} -> using 0 dB (fake mode)")
        self.sg.set_level_offset(-in_loss)     # SG 출력 부스트 -> 칩 입력 = 명령값
        self.sa.set_ref_level_offset(out_loss)  # SA 읽기 = 칩 출력
        log(f"[loss  ] {freq_hz/1e9:.3f} GHz ({src}) -> "
            f"SG offset {-in_loss:+.2f} dB (in_loss {in_loss:.2f}), "
            f"SA offset {out_loss:+.2f} dB (out_loss {out_loss:.2f})")
        return in_loss, out_loss

    def set_loss_override(self, in_db: float, out_db: float) -> None:
        """SG/SA 오프셋을 직접 고정한다(CSV 자동값 무시). 간이 측정용."""
        self._loss_override = (float(in_db), float(out_db))

    def clear_loss_override(self) -> None:
        """수동 override 해제 -> 다시 CSV 자동 손실을 사용한다."""
        self._loss_override = None

    # MEAS? 가 간헐적으로 무응답이라 재시도한다. E36313A 의 고질적 증상으로,
    # 같은 명령을 다시 보내면 대개 바로 돌아온다(실측: 재실행하면 정상).
    # read_vi 가 예외를 올리기 전에 resync() 로 소켓을 정리해 두므로 재시도는 안전하다.
    # 이게 없으면 verify(56점 40분)처럼 긴 실행이 timeout 한 번에 통째로 죽는다.
    # timeout 이 3s 로 짧아진 만큼(psu_e36313a.MEAS_TIMEOUT_S) 시도를 한 번 늘린다 --
    # 회당 비용이 1/5 이라 3회를 다 써도 예전 1회(15s)보다 짧다.
    VI_RETRIES = 3

    def read_all_vi(self, *, retries: int | None = None,
                    log=print) -> dict[str, dict[str, float]]:
        """두 PSU 의 모든 레일 V/I 를 합쳐 하나의 dict 로 반환한다.

        일시적인 MEAS timeout 은 retries 회까지 재시도하고, 매번 로그를 남긴다.
        계속 실패하면 마지막 예외를 그대로 올린다(죽은 계측기를 숨기지 않는다).
        """
        n = self.VI_RETRIES if retries is None else int(retries)
        last: OSError | None = None
        for attempt in range(n + 1):
            try:
                merged: dict[str, dict[str, float]] = {}
                for psu in self.psus:
                    merged.update(psu.read_vi())
                if attempt:
                    log(f"[psu   ] rail read recovered on attempt {attempt + 1}")
                return merged
            except OSError as e:
                last = e
                if attempt < n:
                    log(f"[psu   ] rail read timed out ({e}) -- "
                        f"retry {attempt + 1}/{n}")
        raise last  # noqa: RSE102  -- 루프는 실패 경로에서 반드시 last 를 채운다

    # -- 신호계측기 셋업 ------------------------------------------------
    def setup_sg(self, log=print) -> None:
        """신호발생기(SG)를 측정 직전 상태로 설정한다(기본 RF 출력 OFF)."""
        self.sg.configure(
            freq_hz=float(self.sg_cfg["freq_hz"]),
            level_dbm=float(self.sg_cfg["level_dbm"]),
            rf_output=bool(self.sg_cfg.get("rf_output", False)),
            log=log,
        )
        log(f"[SG    ] freq={float(self.sg_cfg['freq_hz'])/1e9:.3f} GHz "
            f"level={float(self.sg_cfg['level_dbm']):.1f} dBm "
            f"RF={'ON' if self.sg_cfg.get('rf_output') else 'OFF'}")

    def setup_sa(self, log=print) -> None:
        """스펙트럼 분석기(SA)를 측정 직전 상태로 설정한다."""
        self.sa.configure(
            center_hz=float(self.sa_cfg["center_hz"]),
            span_hz=float(self.sa_cfg["span_hz"]),
            rbw_hz=float(self.sa_cfg["rbw_hz"]),
            ref_level_dbm=float(self.sa_cfg["ref_level_dbm"]),
            input_atten_db=float(self.sa_cfg["input_atten_db"]),
            spectrum_mode=bool(self.sa_cfg.get("spectrum_mode", True)),
            log=log,
        )
        log(f"[SA    ] center={float(self.sa_cfg['center_hz'])/1e9:.3f} GHz "
            f"span={float(self.sa_cfg['span_hz'])/1e6:.1f} MHz "
            f"RBW={float(self.sa_cfg['rbw_hz'])/1e6:.3f} MHz")
