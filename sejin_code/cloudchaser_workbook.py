"""CloudChaser Manual Workbook -- IPython copy-paste reference.

Usage:
  1. Open this file alongside an IPython terminal.
  2. Edit [PARAMETERS] section for your session.
  3. Paste each [STEP] block into IPython one at a time.
     - Each block is self-contained and can be re-pasted to re-run.
     - Mid-session change blocks (3b/3c/3d/3e) can be pasted any time.
  4. End with [STEP 7] SHUTDOWN.

Objects available after STEP 3: bench, chip, sg, sa, fh (raw register engine)
Helpers available after STEP 3:  rd, gain, chgain, atten, phase,
                                  chan, enable, disable, paths, biasscan,
                                  load_golden, rf, rfoff, level,
                                  saconf, peak, vi, shutdown

NOTE: bring-up writes raw registers directly (fh.wr_verify) -- pulse bits are
      packed into the same word, so there is no separate latch()/commit()
      step (those vendor shadow-cache helpers no longer exist). Use
      fh.wr_verify(addr, val) for a one-off raw write; rd(field) still reads
      by vendor field name (read-only, safe).

NOTE: a new TX EVB is installed; the old EVB's H0/V0/H2 driver faults
      do not apply. All channels usable (re-verification in progress).
"""

# =============================================================================
# [PARAMETERS] -- the only section you normally need to edit
# =============================================================================

# --- Instrument IPs ----------------------------------------------------------
#  Change these to match your bench network config.
PSU1_IP   = "192.168.5.18"   # Keysight E36313A #1  (FE1_4V0 / CORE_1V0 / IO_ANA_1V8)
PSU2_IP   = "192.168.5.19"   # Keysight E36313A #2  (DIST_1V8 / FE2_1V8 / FE3_1V8)
SG_IP     = "192.168.5.14"   # R&S SMW200A signal generator
SA_IP     = "192.168.5.12"   # R&S FSVA3030 spectrum analyzer
SCPI_PORT = 5025              # SCPI-over-LAN port (change only if port-forwarded)

# --- Chip / Board ------------------------------------------------------------
CHIP = "tx"
#   "tx"  = Stampede2731 TX EVB  (use config/bench.toml)
#   "rx"  = Blueway RX EVB       (use config/bench_rx.toml)

CHANNELS = ["h1"]
#   List of antenna channels to enable (all routed to the same beam).
#   TX/RX: "h0"~"h3", "v0"~"v3"  (new TX EVB: all channels usable)
#   Multi-channel example: ["h1", "h3"]

BEAM = "b0"
#   Beam port to route channels to.
#   "b0" or "b1"

CAL_FREQ = 0x0
#   cal_freq_sel code -- selects calibration frequency band (see Sivers datasheet table).
#   0x0 = default / broadband.  Other codes enable band-specific calibration.
#   NOTE: bring-up no longer applies this knob (not in the raw sequence -- see
#   board/bringup.py's "ignored" log). Kept here only for reference.

COMMON_GAIN = 0x00
#   b{n}_common_gain: 6-bit beam-wide attenuation code (applies to all channels).
#   0x00 = max gain (0 dB attenuation)     <- start here
#   0x08 = ~2 dB attenuation
#   0x10 = ~5 dB attenuation
#   0x20 = ~10 dB attenuation
#   0x3F = max attenuation (~18 dB)

CH_GAIN = {"h1": 0x08}
#   Per-channel gain_control_{pol}{idx} code (TX only; ignored on RX Blueway).
#   6-bit code.  0x00 = max gain, 0x3F = min gain.
#   Include each channel in CHANNELS, e.g. {"h1": 0x08, "h3": 0x08}
#   Missing channels fall back to bench.toml [board.ch_gain] defaults.
#   NOTE: bring_up_tx no longer applies this knob (not in the raw sequence --
#   see board/bringup.py's "ignored" log). Setting it here only changes what
#   bring-up logs as ignored; use chgain()/atten() after bring-up instead.

CH_ATTEN = {"h1": 0x00}
#   Per-channel ch{idx}_{pol}_b{beam}_attn_cal code (digital attenuation per path).
#   0x00 = no attenuation.  Typical range 0x00~0x0F.
#   Include each channel in CHANNELS, e.g. {"h1": 0x00, "h3": 0x00}

# --- Signal Generator (SG) ---------------------------------------------------
FREQ_HZ   = 28.0e9
#   Measurement frequency [Hz].
#   Examples: 25.0e9, 27.0e9, 28.0e9, 28.5e9, 39.0e9

LEVEL_DBM = -20.0
#   SG output level [dBm] = chip INPUT level after path loss is applied.
#   The workbook applies Loss_data CSVs offsets automatically so this value
#   reflects what the DUT actually receives, not what the SG outputs.
#   Typical range: -40.0 to +5.0 dBm (chip input)

RF_ON = False
#   True  = RF output ON immediately at rf() call in STEP 4
#   False = RF stays OFF until you explicitly call rf(True, ...)

# --- Spectrum Analyzer (SA) --------------------------------------------------
SA_SPAN  = 100e6
#   SA display span [Hz].  Examples: 10e6, 100e6, 500e6, 1e9

SA_REF   = 20.0
#   SA reference level [dBm] -- set ~10 dB above the expected peak.
#   After path loss offset: this is the chip OUTPUT reference level.

SA_RBW   = 1e6
#   SA resolution bandwidth [Hz].  Narrower = more accurate but slower.
#   Examples: 100e3, 1e6, 3e6

SA_ATTEN = 10.0
#   SA input attenuator [dB].  Higher = protects SA mixer, lowers sensitivity.
#   0 = most sensitive.  10 = typical.  30 = high-power signals.

# --- Misc --------------------------------------------------------------------
FAKE = False
#   True  = dry-run mode: no TCP connections, no SPI writes (for code testing)
#   False = real hardware  <- use this for actual measurements

# =============================================================================
# [STEP 1] CONNECT INSTRUMENTS
# =============================================================================
# Paste this block ONCE at the start of each IPython session.
# What it does:
#   1. Loads bench config from bench.toml (stable rail voltages/limits stay in TOML)
#   2. Overrides all IPs and board settings from [PARAMETERS] above
#   3. Opens TCP sockets to all 4 instruments and drains stale error queues
#
# Re-paste if a connection drops during the session.
# Exports: bench, sg, sa
# =============================================================================
from pathlib import Path
from cloudchaser.bench import Bench
from cloudchaser.board.bringup import (
    make_chip, make_chip_rx, bring_up_tx, bring_up_rx,
)
from cloudchaser.manual import build_namespace

# Select TOML based on chip type (rail voltages and limits live in TOML)
_workbook_toml = (
    Path("config/bench_rx.toml") if CHIP == "rx"
    else Path("config/bench.toml")
)
bench = Bench.from_toml(_workbook_toml, fake=FAKE)

# Override instrument IPs from [PARAMETERS] (bench.toml IPs are ignored)
bench.psu1.host = PSU1_IP;  bench.psu1.port = SCPI_PORT
bench.psu2.host = PSU2_IP;  bench.psu2.port = SCPI_PORT
bench.sg.host   = SG_IP;    bench.sg.port   = SCPI_PORT
bench.sa.host   = SA_IP;    bench.sa.port   = SCPI_PORT

# Override board settings from [PARAMETERS]
bench.board.active_channels = list(CHANNELS)
bench.board.beam            = BEAM
bench.board.cal_freq_code   = CAL_FREQ
bench.board.common_gain     = COMMON_GAIN
bench.board.ch_gain         = {k: int(v) for k, v in CH_GAIN.items()}
bench.board.ch_atten        = {k: int(v) for k, v in CH_ATTEN.items()}
bench.chip_kind             = CHIP

bench.connect_all()     # opens sockets + drains stale error queues (prints each connection)
sg = bench.sg           # shorthand for SG in this session
sa = bench.sa           # shorthand for SA in this session

print(f"[OK] Connected: PSU1={PSU1_IP}  PSU2={PSU2_IP}  SG={SG_IP}  SA={SA_IP}")
print(f"     chip={CHIP}  channels={CHANNELS}  beam={BEAM}  fake={FAKE}")

# =============================================================================
# [STEP 2] POWER UP RAILS
# =============================================================================
# Ramps PSU rails in the order defined in bench.toml [ramp] power_up_order:
#   CORE_1V0 -> DIST_1V8 -> IO_ANA_1V8 -> FE2_1V8 -> FE3_1V8 -> FE1_4V0
# Each rail ramps from 0V to target in 0.2V steps with 0.1s settle per step.
# Prints V and I [mA] for every rail after they all reach target.
#
# SKIP this block if rails are already powered from a previous session.
# (Re-paste STEP 1 only to reconnect sockets without re-powering.)
#
# To power SPI-only rails first (for chip auto-detect without FE risk):
#   bench.power_up(rails=bench.detect_rail_names)
# =============================================================================
bench.power_up()
# Expected current after bring-up: FE1_4V0 ~50-200 mA (depends on channels enabled)
# If FE current is 0 mA after bring-up, check cable / board power connector.

# =============================================================================
# [STEP 2b] READ RAIL V/I  -- paste any time during session
# =============================================================================
# for name, m in bench.read_all_vi().items():
#     print(f"  {name:12}: {m['v']:.3f} V   {m['i']*1000:.1f} mA")

# =============================================================================
# [STEP 3] CHIP INIT + BRING-UP + HELPER FUNCTIONS
# =============================================================================
# What it does:
#   1. Creates the sivers_api chip object (Stampede or Blueway)
#   2. Runs chip.init() + eFuse load + version_id check (SPI sanity test)
#   3. Enables centerbias_en + centermirror_en (required; NOT done by path.enable)
#   4. Routes CHANNELS to BEAM, sets cal_freq / common_gain / ch_gain / ch_atten
#   5. Commits all register writes to hardware in one burst
#   6. Builds the helper function set and assigns them to local names
#
# After this block: chip is ready, helpers are in scope.
# Re-paste this block to fully re-initialize the chip (e.g. after a register corruption).
# Exports: chip, fh, rd, gain, chgain, atten, phase, chan, enable, disable, paths,
#          biasscan, load_golden, rf, rfoff, level, saconf, peak, vi, shutdown
# =============================================================================
_make_fn    = make_chip_rx if CHIP == "rx" else make_chip
_bringup_fn = bring_up_rx  if CHIP == "rx" else bring_up_tx

chip = _make_fn(bench.board, fake=FAKE)
_bringup_fn(chip, bench.board, require_version=not FAKE)

print(f"[OK] Bring-up done: chip={CHIP}  channels={bench.board.active_channels}"
      f"  beam={bench.board.beam}")

# Build helper namespace and unpack into local names.
# All helpers use the current bench + chip state.
_ns = build_namespace(bench, chip, bench.board.beam)
fh        = _ns["fh"]          # raw register engine: fh.rd(addr) / fh.wr_verify(addr, val)
rd        = _ns["rd"]          # rd("field")          read register field + print value
enable    = _ns["enable"]      # enable("h1")          route channel(s) to beam
disable   = _ns["disable"]     # disable() / disable("h1")  turn path(s) off
paths     = _ns["paths"]       # paths()               print active beam->channel routing
gain      = _ns["gain"]        # gain(code)            set common beam gain (6-bit atten, 0=max)
chgain    = _ns["chgain"]      # chgain("h1", code)    set per-channel FE gain (DEAD on this silicon)
atten     = _ns["atten"]       # atten("h1", code)     set per-channel RTPS attenuator (beam-table)
phase     = _ns["phase"]       # phase("h1", code)     set per-channel RTPS phase (9-bit)
load_golden = _ns["load_golden"] # load_golden()       restore known-good register state
chan      = _ns["chan"]         # chan("h1")            bring ONE channel to measurement-ready
biasscan  = _ns["biasscan"]    # biasscan("h1")        sweep PTAT bias, diagnose dead stages
rf        = _ns["rf"]          # rf(True, freq=28e9, level=-20)  SG control + path loss apply
rfoff     = _ns["rfoff"]       # rfoff()               SG RF OFF (safe shortcut)
level     = _ns["level"]       # level(-15)            change SG level only [dBm]
saconf    = _ns["saconf"]      # saconf(center=28e9, span=100e6, ref=20)  configure SA
peak      = _ns["peak"]        # peak()                single sweep, return SA peak [dBm]
vi        = _ns["vi"]          # vi()                  read + print all rail V/I
shutdown  = _ns["shutdown"]    # shutdown()            RF off + ramp all rails to 0V

# NOTE: gain()/chgain()/atten()/enable()/chan() all write raw registers via fh
# immediately (pulse bits are packed into the same word) -- there is no
# separate latch()/commit() step anymore.

print()
print("  Helpers ready: rd gain chgain atten phase chan enable disable paths")
print("                 biasscan load_golden rf rfoff level saconf peak vi shutdown fh")

# =============================================================================
# [STEP 3b] CHANGE CHANNEL -- paste any time (no restart needed)
# =============================================================================
# Switches to a single measurement channel without re-running STEP 3.
# What it does: disable all paths -> centerbias ON -> route channel to beam
#               -> RTPS beam table zeroed -> common gain max (code 0)
#
# Examples:   chan("h1")   chan("h3")   chan("v1")   chan("v2")   chan("v3")
# After running: move SA cable to the new channel's RF port, then re-run STEP 4.
#
# RF port to SA cable:
#   chan("h1") -> RF_CH1_HPOL     chan("h3") -> RF_CH3_HPOL
#   chan("v1") -> RF_CH1_VPOL     chan("v2") -> RF_CH2_VPOL     chan("v3") -> RF_CH3_VPOL
# =============================================================================
# chan("h1")


# =============================================================================
# [STEP 3c] CHANGE COMMON GAIN -- paste any time
# =============================================================================
# Sets b{n}_common_gain: a single 6-bit attenuation code applied to ALL channels
# on the beam. Applied immediately as a raw write -- no separate latch() step.
#
# Code reference:
#   gain(0x00)   # max gain    (0 dB attenuation)   <- start here
#   gain(0x08)   # ~2 dB attenuation
#   gain(0x10)   # ~5 dB attenuation
#   gain(0x20)   # ~10 dB attenuation
#   gain(0x3F)   # max attenuation (~18 dB)
# =============================================================================
# gain(0x00)


# =============================================================================
# [STEP 3d] CHANGE PER-CHANNEL GAIN -- paste any time (TX only)
# =============================================================================
# Sets per-channel FE gain (0x1018 + channel index, 4-bit). DEAD on this
# silicon -- the working per-path knob is atten() (STEP 3e, beam-table RTPS
# attenuator). Applied immediately as a raw write -- no separate latch() step.
#
# Examples:
#   chgain("h1", 0x08)   # H1: 4-bit gain code (no measurable effect on real HW)
#   chgain("h3", 0x0F)   # H3
# =============================================================================
# chgain("h1", 0x08)


# =============================================================================
# [STEP 3e] CHANGE PER-CHANNEL ATTENUATION -- paste any time
# =============================================================================
# Sets the channel RTPS attenuator (beam-table word, 7-bit, 0=max gain). This
# is the working per-path gain knob on this silicon (chgain()/FE gain is
# DEAD). Applied immediately as a raw write + beam_up() -- no separate
# latch() step.
#
# Examples:
#   atten("h1", 0x00)   # max gain (min attenuation)
#   atten("h3", 0x10)   # more attenuation on H3
# =============================================================================
# atten("h1", 0x00)


# =============================================================================
# [STEP 4] SG / SA SETUP + SIGNAL CHECK
# =============================================================================
# Sets up signal generator + spectrum analyzer, then reads a peak.
# Path loss from Loss_data CSVs is applied automatically to SG and SA offsets:
#   - SG level offset set so that LEVEL_DBM = chip input level
#   - SA ref level offset set so that peak() = chip output level
# After rf() + saconf(), just call peak() repeatedly to read signal.
# RF output state is controlled by RF_ON in [PARAMETERS]. If RF_ON=False, rf() configures
# the SG but leaves RF off -- call rf(True) to enable manually.
#
# rf(on, freq=Hz, level=dBm)
#   on    : True = RF output ON  |  False = RF OFF
#   freq  : [Hz]  e.g. 25e9, 27e9, 28.0e9, 39e9
#   level : [dBm] chip INPUT level (path loss auto-compensated)
#
# saconf(center=Hz, span=Hz, ref=dBm, rbw=Hz, atten_db=dB)
#   center   : [Hz]  defaults to current SG frequency if omitted
#   span     : [Hz]  display span.  Default 100 MHz
#   ref      : [dBm] reference level (set ~10 dB above expected chip output)
#   rbw      : [Hz]  resolution bandwidth.  Default 1 MHz
#   atten_db : [dB]  input attenuator.  Default 10 dB
#
# peak() -> float [dBm]
#   Single sweep + marker to peak.  Returns chip output power [dBm] (loss-compensated).
# =============================================================================
rf(RF_ON, freq=FREQ_HZ, level=LEVEL_DBM)
saconf(center=FREQ_HZ, span=SA_SPAN, ref=SA_REF, rbw=SA_RBW, atten_db=SA_ATTEN)
p = peak()
print(f"  chip output ~= {p:.1f} dBm")

# Quick one-liners for mid-session adjustments (paste individually as needed):
# RF state after pasting this block: ON if RF_ON=True in PARAMETERS, OFF if RF_ON=False
# level(-15)                                    # change SG level only
# rf(False)    # RF off (alternative: rfoff() below)
# rfoff()      # RF off shortcut
# peak()                                        # re-read SA peak
# rf(True, freq=28.5e9, level=-20)              # change frequency + re-apply loss
# saconf(center=28.5e9, ref=20)                 # reconfigure SA to new center
# vi()                                          # check all rail V/I


# =============================================================================
# [STEP 5a] READ / WRITE REGISTERS -- paste any time
# =============================================================================
# rd("field")             : read a vendor field by name, print hex+decimal, return int
#                            (read-only helper -- safe, reads HW directly)
# fh.rd(addr)              : read a raw register address (int, e.g. 0x1005)
# fh.wr_verify(addr, val)  : write a raw register address, applied immediately
#                            and verified by readback -- no latch()/commit()
#                            step (raw writes pack the pulse bit into the word)
#
# Common read fields (rd) / raw addresses (fh.wr_verify):
#   "b0_common_gain"  / 0x1005     6-bit beam-0 gain (0=max, 0x3F=max atten)
#   "b1_common_gain"  / 0x1006     6-bit beam-1 gain
#   "version_id"      / 0x1000     read-only chip ID (0xDC=TX Stampede, 0xD4=RX Blueway)
#
# For channel/beam gain and attenuation prefer gain()/chgain()/atten()
# (STEP 3c/3d/3e) over raw addresses -- they resolve the right beam/channel offset.
# =============================================================================
rd("b0_common_gain")
# fh.wr_verify(0x1005, 0x10)


# =============================================================================
# [STEP 5b] ENABLE / DISABLE CHANNELS -- paste any time
# =============================================================================
# enable("h1")                 route H1 to current beam
# enable("h1", "h3")           route H1 and H3 together
# disable()                    disable all active paths (all channels off)
# disable("h1")                disable only H1 path
# paths()                      print current beam -> channel routing
# =============================================================================
# paths()


# =============================================================================
# [STEP 5c] CENTERBIAS MANUAL OVERRIDE -- paste any time
# =============================================================================
# centerbias_en (bit 0) + centermirror_en (bit 1) of 0x1008 are NOT set by
# the vendor path-enable API. They are set during bring_up_tx/rx and by
# chan(). If you reset the chip or load a custom register state, you may
# need to re-enable them manually.
# =============================================================================
# fh.set_center_enables([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])   # 0x1008 = 3 (bandgap + mirror)


# =============================================================================
# [STEP 5d] BIAS STAGE DIAGNOSTICS -- paste any time
# =============================================================================
# Sweeps each amplifier stage's PTAT bias 0->63 and watches FE rail current delta.
# "NO RESPONSE" for a stage means that stage is not drawing power (likely dead).
# Run chan("hN") first to isolate one channel before running biasscan.
#
# biasscan("h1")   # diagnose H1
# biasscan("h3")   # diagnose H3
# =============================================================================
# chan("h1"); biasscan("h1")


# =============================================================================
# [STEP 5e] LOAD GOLDEN REGISTER STATE -- paste any time
# =============================================================================
# Restores the full register state captured from a known-good measurement.
# Source file: docs/golden_h0b0_25g.json (MATLAB mem_dump at 25 GHz, H0->B0)
# Use this to verify signal path integrity when starting from a blank state.
#
# load_golden()                             # load default golden file
# load_golden("path/to/custom.json")        # load a different capture
# =============================================================================
# load_golden()


# =============================================================================
# [STEP 6] TEST ITEMS
# =============================================================================
# Wire session globals so the test-item functions (op1db, evm, etc.) work
# using the current bench + chip state (no reconnect or restart needed).
# Paste the entire wiring block ONCE, then uncomment individual test calls below.
#
# All test functions:
#   - apply path loss from Loss_data CSVs to SG/SA offsets automatically
#   - save results as CSV in out/ directory
#   - print a summary line when done
# =============================================================================

# --- Session wiring (paste this sub-block first) ----------------------------
import cloudchaser.session as _sess
_sess.B          = bench
_sess.C          = chip
_sess._fake      = FAKE
_sess._ns        = _ns
_sess._chip_kind = CHIP
from cloudchaser.session import (
    op1db, gain_index_accuracy, channel_gain_alignment, evm, acp, ip1db, params
)
print("[OK] Session wired: op1db / gain_index_accuracy / channel_gain_alignment / evm / acp / ip1db ready")
# Use params("op1db") etc. for full parameter descriptions after wiring

# --- OP1dB (TX output 1dB compression point) --------------------------------
# Sweeps SG input power from pin_start to pin_stop, measures output, fits 1dB compression.
#
# op1db(freq_hz=FREQ_HZ, gain_code=COMMON_GAIN)
# op1db(freq_hz=28e9, gain_code=0, pin_start_dbm=-30, pin_stop_dbm=5)
# params("op1db")    # show all parameters and their defaults

# --- Gain Index Accuracy -----------------------------------------------------
# Fixes SG level, sweeps common gain codes and (optionally) per-path RTPS codes.
#
# gain_index_accuracy(sg_level_dbm=0)
# gain_index_accuracy(sg_level_dbm=0, channel_target="beamtable", channel_quad=1)
# params("gain_index_accuracy")

# --- Channel Gain Alignment --------------------------------------------------
# Interactive or auto: measures output level per channel, reports spread [dB].
#   channel_mode="single"  : chip switches channel per measurement (auto SA)
#   channel_mode="all"     : all channels ON simultaneously, you move SA cable
#   channels_script="h1,h3": non-interactive script mode (no input() prompts)
#
# channel_gain_alignment(channel_mode="single")
# channel_gain_alignment(channels_script="h1,h3")
# params("channel_gain_alignment")

# --- EVM (5G NR modulation quality vs output power) -------------------------
# modulation="setup"  : SG creates waveform internally (default)
# modulation="load"   : load waveform from file (waveform_path required)
# modulation="manual" : waveform already loaded on SG, skip setup
#
# evm(freq_hz=FREQ_HZ)
# evm(freq_hz=28e9, modulation="load", waveform_path="waveforms/nr_fr2.wv")
# params("evm")

# --- ACP (Adjacent Channel Power Ratio vs output power) ---------------------
# acp(freq_hz=FREQ_HZ)
# params("acp")

# --- IP1dB (RX input 1dB compression -- Blueway EVB only) --------------------
# RX signal flow: SG -> channel port (antenna input) -> IC -> beam port -> SA
#
# ip1db(freq_hz=19.5e9, gain_code=0)
# params("ip1db")


# --- RX measurement suite (Blueway) -- one channel at a time ----------------
# Move the SG cable to the channel's antenna port, then run for that channel.
# Each test saves its own CSV to out/ (filename includes beam/channel/freq).
#
# rx_suite("h0", freq_hz=19.5e9, waveform_path="")    # full suite for one channel
#
# # or run the steps manually for more control:
# chan("h0")                                          # set channel (updates active_channels)
# ip1db(freq_hz=19.5e9)                                # Linearity (+PDC); default max gain, sweep -50..-20
# gain_index_accuracy_common()                        # Gain Accuracy (common axis); RX defaults
# gain_index_accuracy_channel()                        # Gain Accuracy (channel/RTPS axis); RX defaults
# evm_rx()                                             # EVM bathtub; uses waveform already loaded on SMW (set FSVA NR app first)
# evm_rx(waveform_path="/var/user/xxx.wv")             #   give a path to have the code load that .wv on the SG


# =============================================================================
# [STEP 7] SHUTDOWN
# =============================================================================
# Safely ends the session:
#   1. Turns RF output OFF (SG: RF off)
#   2. Ramps all PSU rails to 0V in reverse power-up order:
#      FE1_4V0 -> FE3_1V8 -> FE2_1V8 -> IO_ANA_1V8 -> DIST_1V8 -> CORE_1V0
#   3. Closes all TCP sockets
#
# Call shutdown() when you are done with the EVB for this session.
# Power stays OFF after this; re-paste STEP 1+2 to start a new session.
# =============================================================================
# rfoff()          # optional: turn RF off before shutdown (shutdown() does this too)
# shutdown()       # ramps rails to 0V
# bench.close_all()  # optional: close sockets after shutdown
