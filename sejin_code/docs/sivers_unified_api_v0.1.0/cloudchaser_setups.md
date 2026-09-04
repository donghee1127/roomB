# Cloudchaser path setup examples

> **Note:** These examples assume the package is already installed. See [getting_started.md](getting_started.md) for installation instructions.

A **channel** is one antenna element connection: `h0–h3` (horizontal pol) or `v0–v3` (vertical pol).  
A **beam** is a beam-port connector: `b0` or `b1`.

Signal direction differs between chips:
- **Stampede (TX)** — signal flows **beam → channels** (distribute one input to many antennas)
- **Blueway (RX)** — signal flows **channels → beam** (combine many antenna inputs to one output)

---

## Stampede (TX)

### Route one channel

Feed a signal into **b0** and route it to a single antenna element **h0**.

```python
from sivers_api import Stampede

chip = Stampede()
chip.init()

chip.path.single("h0", "b0")

# A signal applied to the b0 beam port will now appear on the h0 antenna port.
```

---

### Route full channel

Feed **b0** and distribute to all four horizontal antenna elements.

```python
from sivers_api import Stampede

chip = Stampede()
chip.init()

chip.path.enable_all("h", "b0")

# Signal on b0 now appears on h0, h1, h2, h3.
# All four elements transmit the same beam.
```

---

### Dual-beam TX — two independent beams at the same time

Split the array: H polarisation goes to **b0**, V polarisation goes to **b1**.  
Both beam ports need their own signal source.

```python
from sivers_api import Stampede

chip = Stampede()
chip.init()

chip.path.enable_all("h", "b0")
chip.path.enable_all("v", "b1")

# Signal on b0 appears on h0–h3.
# Signal on b1 appears on v0–v3.
# The two beams are independent.
```

---

### Selective element TX

Route only two elements from each polarisation, on separate beams.

```python
from sivers_api import Stampede

chip = Stampede()
chip.init()

chip.path.enable(["h0", "h1"], "b0")
chip.path.enable(["v2", "v3"], "b1")

# Signal on b0 → h0, h1 only.
# Signal on b1 → v2, v3 only.
```

---

## Blueway (RX)

### Receive on one channel

Connect antenna element **h0** and collect the combined output at **b0**.

```python
from sivers_api import Blueway

chip = Blueway()
chip.init()

chip.path.single("h0", "b0")

# Signal received on the h0 antenna port is now routed to b0.
# Measure or process the signal at the b0 beam port.
```

---

### Receive full channel

Combine all four horizontal elements onto **b0**.

```python
from sivers_api import Blueway

chip = Blueway()
chip.init()

chip.path.enable_all("h", "b0")

# Signals from h0, h1, h2, h3 are combined and available at b0.
```

---

### Dual-beam RX — two independent receive beams

Separate the two polarisations into two independent output ports.

```python
from sivers_api import Blueway

chip = Blueway()
chip.init()

chip.path.enable_all("h", "b0")
chip.path.enable_all("v", "b1")

# h0–h3 combined → b0
# v0–v3 combined → b1
# Each beam port carries an independent receive stream.
```

---

### Selective element RX

Only use specific antenna elements — useful for diagnostic or sub-array testing.

```python
from sivers_api import Blueway

chip = Blueway()
chip.init()

chip.path.enable(["h0", "h2"], "b0")

# Only h0 and h2 contribute to the b0 output.
# h1 and h3 are powered off.
```

---

## Checking active paths

After any path setup you can inspect the current routing state:

```python
print(chip.path.active)
# {<Beam.B0: 'b0'>: [<Channel.H0: 'h0'>, <Channel.H1: 'h1'>], <Beam.B1: 'b1'>: []}
```

---

## Disabling paths

```python
chip.path.disable_single(channel="h0")       # remove one channel from all beams
chip.path.disable_single(beam="b0")          # tear down b0 entirely
chip.path.disable_single(channel="h0", beam="b0")  # remove channel, then tear down beam
chip.path.disable_all()                      # power everything down
```

---

## Reset

`chip.reset()` reloads the eFuse sequence and clears all path state. Re-apply routing afterwards.

```python
chip.reset()
chip.path.enable_all("h", "b0")
```
