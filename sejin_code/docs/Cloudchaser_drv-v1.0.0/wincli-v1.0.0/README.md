# WinCLI

## Requirements:

### Python
- Requires `Python 3.10+`:  
https://www.python.org/downloads/

### FTDI drivers (FTD2xx.dll)

- This project requires the FTDI D2XX drivers (FTD2xx.dll) to communicate with FTDI-based USB devices.
- Download the appropriate driver for your Windows architecture from the FTDI website: https://ftdichip.com/drivers/d2xx-drivers/
- After installing the driver, verify it by:
Connecting the FTDI dongle to the PC and then run:

```powershell
python cloudchaser_cli.py
```

### Included drivers

- `Cloudchaser.dll` - Chip specific driver  
No install needed. Keep in place
- `libMPSSE_MX.dll` - FTDI related  
No install needed. Keep in place