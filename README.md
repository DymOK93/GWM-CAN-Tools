# GWM Vehicle Can Emulator
## Description
Tools for emulating the sequence of CAN commands for running automotive units in the home lab.
## Requirements
Python 3.10 or newer with pyserial, python-can and udsoncan packages installed.
CAN adapter should support slcan (e.g. MKS Canable V2.0) or J2534 (limited set of features is available).
## Usage
Change the channel to the COM name (Windows) or the device path (Linux) in the `can.ini` configuration file.
### Replay traces
Can be recorded in the .candump format using tools such as Cangoroo.
```
replay.py [-h] [--time TIME] [--step STEP] [--range RANGE] trace

positional arguments:
  trace                 CAN trace in linux-candump format

options:
  -h, --help            show this help message and exit
  --time TIME, -t TIME  replay time in seconds
  --step STEP, -s STEP  step-by-step execution with pause
  --range RANGE, -r RANGE
                        first,last trace lines
```
### Emulate CAN
Supported devices: 
1. SC-CAN - HUT (only Harman GWMv2 is supported)
2. BD-CAN - IP (Cluster), HUD
```
usage: can_emulator.py [-h] [--uds-mode {user,developer}] [--loglevel {DEBUG,INFO,WARNING,ERROR}]

options:
  -h, --help            show this help message and exit
  --uds-mode {user,developer}
                        Work mode
  --loglevel {DEBUG,INFO,WARNING,ERROR}
                        Logging level

can> (see available commands below)
```
Commands:
* `ign=on` - turn on the ignition;
* `ign=off` - turn off the ignition;
* `hut-stb=on` - switch HUT to standby mode (works only when the ignition is on);
* `hut-stb=off` - switch HUT to background mode;
* `hut-reboot=<boot_target>` - reboot the HUT to `normal`, `recovery` or `ELK` (supported only in developer mode)
* `exit`, `q` - finish work.

### Reboot using a J2534-compatible adapter
Reboot HUT to the specified boot target:
```
usage: hut_reboot_j2534.py [-h] [--uds-mode {user,developer}] [--windll WINDLL]
                           [--loglevel {DEBUG,INFO,WARNING,ERROR}]
                           {}

positional arguments:
  {}                    Boot target

options:
  -h, --help            show this help message and exit
  --uds-mode {user,developer}
                        Work mode
  --windll WINDLL       Path to J2534 shared library
  --loglevel {DEBUG,INFO,WARNING,ERROR}
                        Logging level
```
The `ip_reboot_j2534.py` and `hud_reboot_j2534.py` are used to reboot the IP (cluster) and HUD, respectively.

### Enable navigation prompts on HUD using a J2534-compatible adapter
Enabling the display of navigation arrows and distance to maneuver requires changing the 10th HEX character of the configuration to "8".
```
usage: hud_enable_navi_j2534.py [-h] [--uds-mode {user,developer}] [--windll WINDLL]
                                [--loglevel {DEBUG,INFO,WARNING,ERROR}]

options:
  -h, --help            show this help message and exit
  --uds-mode {user,developer}
                        Work mode
  --windll WINDLL       Path to J2534 shared library
  --loglevel {DEBUG,INFO,WARNING,ERROR}
                        Logging level
```
