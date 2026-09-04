"""PSU SCPI 응답성 진단 — MEAS 타임아웃이 났을 때 어느 계층이 죽었는지 가른다.

`bench.power_up()` 의 `read_all_vi()` 가 `MEAS:CURR?` 에서 socket timeout 으로 죽는
증상을 만났을 때, 원인이 (a) 계측기/LAN 무응답인지 (b) 쿼리 desync(off-by-one)인지
(c) 특정 명령만 느린 것인지를 구분한다. 보드 상태는 건드리지 않는다 — 읽기 전용
쿼리만 보내고 전압/출력/보호 설정은 일절 쓰지 않는다.

실행:
  python scripts/psu_probe.py                  # config/bench.toml
  python scripts/psu_probe.py --config config/bench_rx.toml
  python scripts/psu_probe.py --repeat 5       # 간헐적 증상 잡기

  # read_all_vi() 소요시간 분포 -- MEAS_TIMEOUT_S 를 정하는 근거를 만든다.
  python scripts/psu_probe.py --vi 100
  python scripts/psu_probe.py --vi 100 --meas-timeout 3   # 후보 값을 미리 시험

읽는 법:
  - 전부 빠르게(<2s) 응답 -> 계측기는 멀쩡하다. 타이밍/desync 쪽을 본다.
  - 특정 명령만 timeout -> 그 명령이 이 펌웨어에서 지원되지 않거나 느린 것.
  - resync 가 바이트를 버렸다고 나오면 -> 그 시점에 desync 가 있었다는 직접 증거.
  - 전부 timeout -> LAN/계측기 자체. 계측기 전면 패널·랜케이블부터 본다.

`--vi` 읽는 법:
  - 성공 읽기의 p95 와 max 가 곧 필요한 timeout 의 하한이다. 지금 기본값 15s 는
    정상 1.4s(2026-06-25 실측)의 10배라, 실패 1회에 15.3s 를 그냥 기다린다.
  - 실패 표본의 소요시간이 전부 timeout 값에 딱 붙어 있으면 '기다리다 포기'한
    것이고, 재시도가 즉시 성공하면 느린 게 아니라 유실된 것이다 -> timeout 을
    줄이고 재시도를 늘리는 쪽이 이득이다.
  - `--meas-timeout 3` 으로 후보 값을 걸고 실패율이 얼마나 오르는지 직접 본다.

주의: 사용자에게 보이는 출력/예외는 영어로 작성한다(콘솔 한글 깨짐 방지).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloudchaser.bench import Bench  # noqa: E402
from cloudchaser.setup_tx import DEFAULT_CONFIG, _force_utf8_stdout  # noqa: E402

# 읽기 전용 쿼리만. 순서에 의미가 있다: *IDN? 이 되면 소켓은 살아있는 것이고,
# 그 다음부터 개별 명령의 응답성을 하나씩 가른다.
PROBES = [
    "*IDN?",
    "STAT:QUES:COND? (@{ch})",   # ramp 중 tripped() 가 쓰는 쿼리 (조용히 자기비활성화됨)
    "MEAS:VOLT? (@{ch})",
    "MEAS:CURR? (@{ch})",        # 실제로 timeout 이 나던 쿼리
    "CURR:RANG? (@{ch})",        # 전류 레인지(autorange 의심 시)
    "OUTP? (@{ch})",
]


def probe_psu(psu, *, repeat: int) -> int:
    """Run the read-only probe list against one PSU. Returns the failure count."""
    chans = ",".join(str(r.ch) for r in sorted(psu.rails.values(), key=lambda r: r.ch))
    rails = ", ".join(f"ch{r.ch}={r.name}" for r in
                      sorted(psu.rails.values(), key=lambda r: r.ch))
    print(f"\n=== {psu.name} @ {psu.host}  [{rails}] ===")
    print(f"  socket timeout = {psu.timeout:.1f}s, "
          f"MEAS timeout = {psu.MEAS_TIMEOUT_S:.1f}s")
    failures = 0
    for n in range(1, repeat + 1):
        if repeat > 1:
            print(f"  -- pass {n}/{repeat} --")
        for tpl in PROBES:
            cmd = tpl.format(ch=chans)
            t0 = time.time()
            try:
                resp = psu.query(cmd)
                dt = time.time() - t0
                flag = "  <-- SLOW" if dt > 2.0 else ""
                print(f"  {cmd:28} {dt:6.2f}s  {resp!r}{flag}")
            except Exception as e:  # noqa: BLE001
                dt = time.time() - t0
                failures += 1
                print(f"  {cmd:28} {dt:6.2f}s  {type(e).__name__}: {e}")
                dropped = psu.resync()
                # resync 가 뭔가 버렸다면, 그 바이트가 곧 desync 의 증거다.
                print(f"  {'  -> resync':28} {'':6}  dropped {dropped} byte(s)"
                      + ("  <-- DESYNC EVIDENCE" if dropped else ""))
        errs = psu.drain_errors()
        print(f"  {'  -> error queue':28} {'':6}  "
              + (", ".join(errs) if errs else "(empty)"))
    return failures


def _pct(vals: list[float], q: float) -> float:
    """정렬된 표본의 q 분위(0..1). 표본이 적어도 죽지 않게 최근접 순위법을 쓴다."""
    if not vals:
        return float("nan")
    s = sorted(vals)
    i = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[i]


def vi_stats(bench, *, samples: int, retries: int, log=print) -> int:
    """Time `read_all_vi()` repeatedly and report the duration distribution.

    This is the call that actually times out during a sweep -- MEAS:VOLT? and
    MEAS:CURR? back to back on every PSU, under the raised MEAS timeout. The
    per-command probe above cannot answer "what timeout is right": it queries
    once, at the default socket timeout, and prints no distribution.

    Read-only -- no output, voltage or protection setting is touched.
    """
    ok: list[float] = []
    bad: list[float] = []
    t_all = time.time()
    for n in range(1, samples + 1):
        t0 = time.time()
        try:
            bench.read_all_vi(retries=retries, log=lambda *a, **k: None)
            ok.append(time.time() - t0)
        except OSError:
            bad.append(time.time() - t0)
        if n % 10 == 0 or n == samples:
            log(f"  {n}/{samples} sampled   ok={len(ok)} failed={len(bad)}")
    total = time.time() - t_all
    log("")
    log(f"[vi-stats] samples={samples}  ok={len(ok)}  "
        f"failed={len(bad)} ({100.0 * len(bad) / max(1, samples):.1f}%)  "
        f"retries={retries}")
    if ok:
        log(f"  ok   [s]  min {min(ok):6.2f}  p50 {_pct(ok, 0.5):6.2f}  "
            f"p90 {_pct(ok, 0.9):6.2f}  p95 {_pct(ok, 0.95):6.2f}  "
            f"max {max(ok):6.2f}")
    if bad:
        log(f"  fail [s]  min {min(bad):6.2f}  p50 {_pct(bad, 0.5):6.2f}  "
            f"max {max(bad):6.2f}   sum {sum(bad):7.2f}")
    line = f"  wall {total:.1f} s"
    if bad:
        line += (f"   failures cost {sum(bad):.1f} s "
                 f"({100.0 * sum(bad) / total:.0f}% of the run)")
    log(line)
    if ok:
        # MEAS_TIMEOUT_S 는 read_all_vi 전체가 아니라 **쿼리 하나**에 걸린다.
        # 한 번 읽기는 PSU 당 2개(MEAS:VOLT?/MEAS:CURR?)를 보내므로, 위 소요시간을
        # 쿼리 수로 나눈 값이 비교 대상이다. 이걸 안 나누면 필요한 값의 4배를 제안한다.
        nq = 2 * max(1, len(bench.psus))
        log(f"  {nq} queries per read ({len(bench.psus)} PSU(s) x VOLT?/CURR?) "
            f"-> about {max(ok) / nq:.2f}s for the slowest single query")
        log(f"  -> a MEAS timeout of {max(2.0, 2 * max(ok) / nq):.1f}s still "
            f"clears it. The timeout is per query, not per read.")
    return len(bad)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Probe PSU SCPI responsiveness (read-only; does not change "
                    "any output, voltage or protection setting)")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--repeat", type=int, default=1,
                   help="probe passes per PSU (raise to catch intermittent faults)")
    p.add_argument("--vi", type=int, default=0, metavar="N",
                   help="instead of the per-command probe, time N read_all_vi() "
                        "calls and report the duration distribution -- that is "
                        "the call that times out during a sweep")
    p.add_argument("--meas-timeout", type=float, default=None, metavar="S",
                   help="override the MEAS socket timeout [s] for this run, so a "
                        "candidate value can be tried before changing the code")
    p.add_argument("--retries", type=int, default=0,
                   help="--vi: retries per sample (default 0, so every timeout is "
                        "counted instead of being hidden by a retry)")
    p.add_argument("--fake", action="store_true",
                   help="run without hardware (structure check only)")
    args = p.parse_args(argv)

    bench = Bench.from_toml(args.config, fake=args.fake)
    failures = 0
    try:
        # PSU 만 연결한다. SG/SA/VNA 는 이 진단과 무관하고, 연결 자체가 느릴 수 있다.
        for psu in bench.psus:
            psu.connect()
            if args.meas_timeout is not None:
                psu.MEAS_TIMEOUT_S = float(args.meas_timeout)
        if args.vi:
            print()
            print(f"=== read_all_vi x{args.vi}   "
                  f"(MEAS timeout {bench.psus[0].MEAS_TIMEOUT_S:.1f}s, "
                  f"retries {args.retries}) ===")
            failures = vi_stats(bench, samples=args.vi, retries=args.retries)
        else:
            for psu in bench.psus:
                failures += probe_psu(psu, repeat=args.repeat)
    finally:
        for psu in bench.psus:
            try:
                psu.close()
            except Exception:  # noqa: BLE001, S110
                pass
    noun = "sample" if args.vi else "query"
    print(f"\n[psu-probe] {failures} failing {noun}{'' if failures == 1 else 's'}. "
          "Power outputs and protection settings were not touched.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
