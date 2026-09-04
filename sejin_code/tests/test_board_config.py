"""BoardConfig 신규 필드 + bench.toml 로딩 검증."""
from pathlib import Path

from cloudchaser.bench import Bench
from cloudchaser.board.bringup import BoardConfig

CONFIG = Path(__file__).resolve().parents[1] / "config" / "bench.toml"


def test_board_config_defaults():
    cfg = BoardConfig()
    assert cfg.split_mode is True
    assert cfg.optimized_bias is True
    assert cfg.dist_st2_1_ptat == 13
    assert cfg.run_efuse_init is False


def test_bench_toml_loads_new_fields():
    b = Bench.from_toml(CONFIG, fake=True)
    assert b.board.split_mode is True
    assert b.board.optimized_bias is True
    assert b.board.dist_st2_1_ptat == 13
    assert b.board.run_efuse_init is False


def test_missing_keys_fall_back_to_defaults(tmp_path):
    """구 bench.toml(신규 키 없음)도 그대로 로드돼야 한다."""
    src = CONFIG.read_text(encoding="utf-8")
    stripped = "\n".join(
        ln for ln in src.splitlines()
        if not ln.strip().startswith(("split_mode", "optimized_bias",
                                      "dist_st2_1_ptat", "run_efuse_init"))
    )
    p = tmp_path / "bench_old.toml"
    p.write_text(stripped, encoding="utf-8")
    b = Bench.from_toml(p, fake=True)
    assert b.board.split_mode is True
    assert b.board.optimized_bias is True


def test_common_gain_defaults_to_zero_everywhere():
    """common_gain 기본값은 0(최대 게인)이어야 한다 -- dataclass / 로더 / toml 세 곳.

    한 곳만 고치면 toml 을 지운 환경이나 BoardConfig() 직접 생성 경로에서
    옛 기본값(0x20)이 조용히 살아난다.
    """
    assert BoardConfig().common_gain == 0x00
    assert Bench.from_toml(CONFIG, fake=True).board.common_gain == 0x00


def test_common_gain_falls_back_to_zero_when_key_missing(tmp_path):
    src = CONFIG.read_text(encoding="utf-8")
    stripped = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("common_gain"))
    p = tmp_path / "bench_nogain.toml"
    p.write_text(stripped, encoding="utf-8")
    assert Bench.from_toml(p, fake=True).board.common_gain == 0x00
