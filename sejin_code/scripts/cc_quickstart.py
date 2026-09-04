# =============================================================
# Cloudchaser EVB Quick-Start Script
# - Target : Stampede2731 (TX) / Blueway1721 (RX) EVB
# - Requires: Python 3.13+, sivers_unified_api-0.1.0 installed,
#             FTDI D2XX driver (FTD2xx) installed on Windows
# - Usage  :
#     python cc_quickstart.py                  # Stampede(TX), real HW
#     python cc_quickstart.py --chip blueway   # Blueway(RX)
#     python cc_quickstart.py --fake           # HW 없이 SW 동작 확인
# =============================================================
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Cloudchaser EVB quick-start")
    parser.add_argument("--chip", choices=["stampede", "blueway"],
                        default="stampede", help="stampede=TX EVB, blueway=RX EVB")
    parser.add_argument("--fake", action="store_true",
                        help="fake SPI mode (no hardware required)")
    parser.add_argument("--dump", action="store_true",
                        help="dump all fields to fields.csv after init")
    args = parser.parse_args()

    # --- 0. Import check -----------------------------------------
    try:
        from sivers_api import Stampede, Blueway
    except ImportError:
        sys.exit("[ERROR] sivers_api not installed.\n"
                 "  pip install sivers_unified_api-0.1.0-py3-none-any.whl")

    # --- 1. Create chip object ----------------------------------
    chip_cls = Stampede if args.chip == "stampede" else Blueway
    chip = chip_cls(fake_spi=args.fake)          # chip_id defaults to 0
    print(f"[1/4] {chip_cls.__name__} object created (fake_spi={args.fake})")

    # --- 2. Initialize: reset + read all regs + eFuse sequence ---
    chip.init()
    print("[2/4] chip.init() OK  -> chip is in known state")

    # --- 3. SPI link sanity check --------------------------------
    # Live read of one register page; init() succeeding already implies
    # SPI communication is working, this is an explicit confirmation.
    chip.regs.dump(start=0x1000, stop=0x1010)
    print("[3/4] register dump OK -> SPI link verified")

    if args.dump:
        chip.fields.dump(save_to_file=True, filename="fields.csv")
        print("      all fields saved to fields.csv")

    # --- 4. Minimal path setup: one channel -> one beam ----------
    # TX(Stampede): b0 input  -> h0 antenna port
    # RX(Blueway) : h0 antenna -> b0 output
    chip.path.single("h0", "b0")
    print("[4/4] path set: h0 <-> b0")
    print("      active paths:", chip.path.active)

    # -------------------------------------------------------------
    # Next steps (uncomment as needed):
    #
    # chip.path.enable_all("h", "b0")      # H0~H3 all -> b0
    # chip.path.enable_all("v", "b1")      # dual-beam: V0~V3 -> b1
    # chip.path.disable_all()              # power down all paths
    #
    # val = chip.fields.rd("field_name")   # live SPI read
    # chip.fields.wr("field_name", 0x3)    # immediate write
    #
    # Bulk config (one SPI burst):
    # chip.cfg.set_auto_commit(False)
    # chip.fields.wr("field_a", 1)
    # chip.fields.wr("field_b", 2)
    # chip.commit()
    # chip.cfg.set_auto_commit(True)
    # -------------------------------------------------------------
    print("\nDone. Apply RF signal and measure.")


if __name__ == "__main__":
    main()
