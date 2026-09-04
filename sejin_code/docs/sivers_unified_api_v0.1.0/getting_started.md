# Requirements

> **Python 3.13 or later is required.** Earlier versions are not supported.

# Installation

There are 2 installation options:

## 1. Using uv — For virtual environment based

uv manages a self-contained virtual environment and keeps dependencies isolated from your system Python. Install uv first if you haven't already (see the [official docs](https://docs.astral.sh/uv/getting-started/installation/)):

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create a project and add the package:

```powershell
uv init my_project
cd my_project
uv add C:\path\to\sivers_unified_api-0.1.0-py3-none-any.whl
```

Run your scripts:

```powershell
cd my_project
uv run my_script.py
```

---

## 2. Using pip — system Python install

Installs the package globally into your Python installation. No virtual environment required, but dependencies are shared with everything else on the system.

```powershell
cd C:\path\to\
pip install sivers_unified_api-0.1.0-py3-none-any.whl
```

After installation, import and use directly:

```python
from sivers_api import Stampede
```

---

# Getting started — writing scripts with sivers_api for Cloudchaser BFIC

## 1. Create and initialise a chip

```python
from sivers_api import Stampede, Blueway

chip = Stampede()          # chip_id defaults to 0
chip.init()                # reset chip, read all registers, apply eFuse sequence
```

Use `fake_spi=True` when no hardware is connected:

```python
chip = Stampede(fake_spi=True)
chip.init()
```

`init()` must be called before reading or writing anything. It leaves the chip in a known state ready for configuration.

---

## 2. Reading and writing fields

Fields are the primary interface. Names come directly from the register map.

```python
# Read a field (always fetches from hardware)
val = chip.fields.rd("some_field")

# Write a field (commits to hardware immediately by default)
chip.fields.wr("some_field", 0x3)

# Convenience bit operations
chip.fields.set("some_field", 0b01)   # OR mask into field
chip.fields.clr("some_field", 0b01)   # AND-NOT mask from field
chip.fields.toggle("some_field", 0b11)
chip.fields.step("some_field", 1)     # increment
```

You can also use `[]` getitem access, which is useful for quick interactive exploration or when batching writes:

```python
val = chip.fields["some_field"]      # returns the locally cached value — no SPI read
chip.fields["some_field"] = 0x3      # updates local cache and marks register as dirty
chip.commit()                        # flushes all dirty registers to hardware in one go
```

The key difference from `.rd()` / `.wr()` is that `[]` never touches hardware on its own:
- **Read** `[]` — returns what is in the local cache from the last `init()`, `reset()`, or `.rd()` call.
- **Read** `.rd()` — always does a live SPI read first, then returns the updated value.
- **Write** `[]=` — stages the change locally. Nothing is sent to the chip until `chip.commit()` is called (or auto-commit sends it automatically).

```python
val = chip.fields.rd("some_field")   # SPI read → updates cache → returns value
val = chip.fields["some_field"]      # returns cache as-is, no SPI
```

The returned value also supports in-place bit operators, which read-modify-write the cache:

```python
chip.fields["some_field"] |= 0b01    # set bit 0
chip.fields["some_field"] &= ~0b10   # clear bit 1
chip.fields["some_field"] ^= 0b11    # toggle bits 0 and 1
chip.commit()
```

---

## 3. Reading and writing registers

Use register access when you need to work below the field level, or with addresses not in the register map.

```python
# By register name
val = chip.regs.rd("REG_NAME")
chip.regs.wr("REG_NAME", 0xABCD)

# By address
val = chip.regs.rd(0x1050)
chip.regs.wr(0x1050, 0xABCD)

# Bit helpers
chip.regs.set(0x1050, 0x0001)    # set bits
chip.regs.clr(0x1050, 0x0001)    # clear bits

# Getitem works here too, by address or by register name.
# Like fields[], this only touches the local cache — no SPI transaction happens
# until chip.commit() is called. This makes it easy to stage multiple changes
# and send them in one burst.
raw = chip.regs[0x1050]              # read from local cache
chip.regs[0x1050] = 0xABCD           # stage a write
chip.regs["REG_NAME"] = 0xABCD       # same, by name

# In-place operators perform a cached read-modify-write
chip.regs[0x1050] |= 0x0006          # set bits 1 and 2
chip.regs["REG_NAME"] &= ~0x0001     # clear bit 0
chip.commit()                        # send all staged changes to hardware
```

---

## 4. Batching writes (auto-commit)

By default every write goes to hardware immediately (`auto_commit=True`). For bulk configuration, disable auto-commit and flush once at the end:

```python
chip.cfg.set_auto_commit(False)

chip.fields.wr("field_a", 1)
chip.fields.wr("field_b", 2)
chip.fields.wr("field_c", 3)

chip.commit()                  # sends all pending writes in address-sorted bursts

chip.cfg.set_auto_commit(True)
```

Check what is pending before committing:

```python
pending = chip.pending()       # returns set of dirty register names
```

---

## 5. Path setup (Cloudchaser)

Cloudchaser chips expose a `path` interface for routing antenna channels to beams. Channels are `h0–h3` / `v0–v3`, beams are `b0` / `b1`.

```python
chip.path.single("h0", "b0")            # one channel → one beam
chip.path.enable(["h0", "h1"], "b0")    # several channels → one beam
chip.path.enable_all("h", "b0")         # all H channels → b0

chip.path.disable_single(channel="h0")  # remove one channel
chip.path.disable_all()                 # power everything down
```

See [cloudchaser_setups.md](cloudchaser_setups.md) for more examples including split-beam setups.

---

## 6. Reset

`reset()` issues a hardware reset and re-applies the eFuse sequence. Internal path state is cleared — re-apply any routing afterwards.

```python
chip.reset()
chip.path.single("h0", "b0")
```

---

## 7. Debugging

Dump all field values to the console (pass `update=True` to refresh from hardware first):

```python
chip.fields.dump(update=True)
chip.fields.dump(save_to_file=True, filename="fields.csv")
```

Dump raw register values over an address range:

```python
chip.regs.dump(start=0x1000, stop=0x1100)
chip.regs.dump(save_to_file=True, filename="regs.csv")
```

---

> **Note:** The `chip.adc` and `chip.beam_table` interfaces are currently untested and should not be relied upon. Functionality may be incomplete or incorrect.
