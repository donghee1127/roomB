"""pytest fixtures shared across the test suite.

FH raw-register tests use a fake SPI transport so bitpacking can be verified
without hardware. Kept here (not in a test module) so later tasks can import
`FakeChip` / `MemSPI` via a fixture instead of `from tests.test_x import ...`,
which would fail because `tests/` has no `__init__.py` and pytest is
configured with only `pythonpath = ["src"]`.
"""
import pytest

from cloudchaser.board.firehawk import FH


class MemSPI:
    """주소->값 딕셔너리 SPI. 쓴 값을 그대로 돌려준다."""

    def __init__(self):
        self.mem = {}
        self.writes = []
        self.fake = True

    def wr(self, cid, addr, val):
        self.mem[addr] = val & 0xFFFF
        self.writes.append((addr, val & 0xFFFF))

    def rd(self, cid, addr):
        return self.mem.get(addr, 0)

    def reset(self):
        pass

    def beam_up(self):
        pass


class FakeChip:
    def __init__(self):
        self.spi = MemSPI()


@pytest.fixture
def fh():
    return FH(FakeChip(), 0)
