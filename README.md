# GWM Vehicle Can Emulator
## Description
Tools for emulating the sequence of CAN commands for running automotive units in the home lab.
## Requirements
Python 3.2 or newer.
CAN adapter with slcan support (e.g. MKS Canable V2.0)
## Usage
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
### Emulate SC-CAN
Devices on the bus: Gateway, HUT, T-Box, ADAS, IP (Cluster)
```
sc-can-emulator.py
sc-can> (see available commands below)
```
Commands:
* `ign=on` - turn on the ignition
* `ign=off` - turn off the ignition
* `hut-disp=on` - turn on the HUT display (works only when the ignition is on)
* `hut-disp=off` - turn off the HUT display
* `exit`- finish work
