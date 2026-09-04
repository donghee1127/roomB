"""테스트 실행기(runner) — 선택한 Test Item 을 자동 실행하는 백엔드.

흐름:
  1) 계측기 연결 + 전원 램프업 + 보드 bring-up  (= 측정 준비)
  2) 선택한 Test Item 의 run() 실행
  3) 결과를 CSV 로 저장
  4) (성공/실패 무관) SG RF OFF + 소켓 닫기

이 모듈의 run_test() 가 핵심 진입점이다. 나중에 GUI 의 "Run" 버튼은 사용자가 고른
test_id 와 파라미터 dict 를 모아 run_test() 를 호출하기만 하면 된다.

CLI:
  python -m cloudchaser.runner list                      # 테스트 목록
  python -m cloudchaser.runner info gain_index_accuracy   # 파라미터 보기
  python -m cloudchaser.runner run gain_index_accuracy --fake  # 실행(dry-run)
  python -m cloudchaser.runner run op1db --param gain_code=0x20 --param pin_stop_dbm=0

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from .bench import Bench
from .board.bringup import bring_up_tx, make_chip
from .setup_tx import DEFAULT_CONFIG, _force_utf8_stdout
from .test_items import TestContext, TestResult, coerce, get_test, list_tests

# 결과 CSV 저장 기본 폴더(repo 루트 기준). .gitignore 에 out/ 이 있어 git 엔 안 올라감.
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "out"


def prepare_session(config: Path, *, fake: bool, log=print) -> TestContext:
    """측정 준비: 계측기 연결 → 전원 램프업 → 보드 bring-up. TestContext 반환.

    setup_tx 와 동일한 준비 단계를 거치되, SG/SA 의 측정 파라미터는 각 테스트가
    스스로 설정하므로 여기서는 건드리지 않는다.
    """
    bench = Bench.from_toml(config, fake=fake)
    bench.connect_all(log=log)
    bench.power_up(log=log)
    chip = make_chip(bench.board, fake=fake)
    bring_up_tx(chip, bench.board, require_version=not fake, log=log)
    return TestContext(bench=bench, chip=chip, fake=fake)


def run_test(test_id: str, params: dict | None = None, *,
             config: Path = DEFAULT_CONFIG, fake: bool = False,
             out_dir: Path | None = DEFAULT_OUT, log=print) -> TestResult:
    """선택한 테스트를 준비→실행→저장까지 한 번에 수행하고 결과를 반환한다.

    GUI 의 "Run" 이 호출할 핵심 함수. params 는 {파라미터명: 값} dict.
    """
    test = get_test(test_id)()
    resolved = test.resolve(params)        # 기본값 + 사용자 입력 병합
    log(f"=== Run test '{test_id}' === (fake={fake})")

    ctx = prepare_session(config, fake=fake, log=log)
    try:
        result = test.run(ctx, resolved, log=log)
    finally:
        # 테스트 끝나면 RF 는 반드시 끈다(안전). 전원 레일은 유지(연속 테스트 대비).
        try:
            ctx.bench.sg.rf_output(False)
        except Exception:
            pass
        ctx.bench.close_all()

    if out_dir is not None:
        _save_csv(result, resolved, out_dir, log=log)
    log(f"=== Result: {result.summary} ===")
    return result


def _save_csv(result: TestResult, params: dict, out_dir: Path, *, log=print) -> Path:
    """측정 데이터(표)와 파라미터/요약(주석 헤더)을 CSV 로 저장한다.

    파일명: <test_id>_<yymmdd>_<BEAM>_<CHANNEL>_<freq>_<HHMMSS>.csv
    (파일명만 보고 무엇을 측정했는지 알 수 있게 빔/채널/주파수를 포함.)
    beam/channel 은 result.meta 에서, 주파수는 meta 또는 params 에서 가져온다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")          # 주석 헤더용(기존 포맷 유지)
    ymd, hms = now.strftime("%y%m%d"), now.strftime("%H%M%S")
    meta = result.meta or {}

    def _tag(val, fallback):
        # 파일명 안전: '?', 공백 등 금지문자 제거(특히 Windows). 비면 fallback.
        s = "".join(ch for ch in str(val).strip().upper() if ch.isalnum())
        return s if s and s != "NONE" else fallback

    beam = _tag(meta.get("beam"), "Bx")
    channel = _tag(meta.get("channel"), "CHx")
    freq_hz = meta.get("freq_hz", params.get("freq_hz"))
    freq = f"{float(freq_hz) / 1e6:.0f}MHz" if freq_hz else "FREQx"
    # 고정 게인 코드가 있으면(op1db/ip1db 등) 파일명에 포함 — 측정 조건 식별용.
    gain = meta.get("gain_code")
    gtag = f"_G{int(gain):02X}" if gain is not None else ""
    # gain_index_accuracy 의 common/chan sweep 을 구분하는 축 태그(없으면 무영향).
    axis = meta.get("axis")
    atag = f"_{axis}" if axis else ""
    path = out_dir / f"{result.test_id}_{ymd}_{beam}_{channel}_{freq}{gtag}{atag}_{hms}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # 주석(#) 헤더에 메타정보 기록 — 나중에 사람이 보거나 파싱하기 쉽게.
        w.writerow([f"# test: {result.title} ({result.test_id})"])
        w.writerow([f"# time: {stamp}"])
        w.writerow([f"# passed: {result.passed}"])
        w.writerow([f"# summary: {result.summary}"])
        for k, v in params.items():
            w.writerow([f"# param.{k}: {v}"])
        for k, v in result.meta.items():
            w.writerow([f"# meta.{k}: {v}"])
        w.writerow(result.columns)   # 데이터 표 헤더
        w.writerows(result.rows)     # 데이터 행
    log(f"[save  ] results -> {path}")
    return path


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def _parse_params(test_cls, pairs: list[str]) -> dict:
    """CLI 의 `--param key=value` 들을 파라미터 타입에 맞게 변환해 dict 로 만든다."""
    by_name = {p.name: p for p in test_cls.params}
    out: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param expects key=value, got '{pair}'")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in by_name:
            raise SystemExit(f"unknown param '{key}'. available: {list(by_name)}")
        out[key] = coerce(by_name[key], raw)
    return out


def _print_info(test_cls) -> None:
    """테스트의 파라미터 명세를 출력(CLI info / GUI 가 참고할 정보와 동일)."""
    print(f"{test_cls.id}: {test_cls.title}")
    print(f"  {test_cls.description}")
    print("  params:")
    for p in test_cls.params:
        unit = f" [{p.unit}]" if p.unit else ""
        ch = f" choices={p.choices}" if p.choices else ""
        print(f"    - {p.name} ({p.type}){unit} default={p.default!r}{ch}")
        if p.help:
            print(f"        {p.help}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(description="CloudChaser test runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list available test items")

    p_info = sub.add_parser("info", help="show a test's parameters")
    p_info.add_argument("test_id")

    p_run = sub.add_parser("run", help="run a test item")
    p_run.add_argument("test_id")
    p_run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p_run.add_argument("--fake", action="store_true", help="dry-run without hardware")
    p_run.add_argument("--out", type=Path, default=DEFAULT_OUT,
                       help="results output dir (default: repo out/)")
    p_run.add_argument("--param", action="append", default=[],
                       metavar="KEY=VALUE", help="test parameter override (repeatable)")
    args = p.parse_args(argv)

    if args.cmd == "list":
        for t in list_tests():
            print(f"  {t.id:16s} {t.title}")
        return 0

    if args.cmd == "info":
        _print_info(get_test(args.test_id))
        return 0

    if args.cmd == "run":
        test_cls = get_test(args.test_id)
        params = _parse_params(test_cls, args.param)
        result = run_test(args.test_id, params, config=args.config,
                          fake=args.fake, out_dir=args.out)
        return 0 if result.passed in (True, None) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
