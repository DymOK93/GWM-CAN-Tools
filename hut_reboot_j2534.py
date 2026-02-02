#!/usr/bin/env python
# -*- coding: utf-8 -*-
from udsoncan.connections import J2534Connection
import argparse
import logging
import uds

#
#
#
def rebootHutToTarget(target: str, uds_mode: str, windll: str) -> None:
    print(f'Reboot HUT to {target}')
    with uds.HarmanHut(uds.getModeValue(uds_mode), 
                       lambda txid, rxid: J2534Connection(windll, rxid, txid)) as hut:
        hut.reboot(target)

#
# Does processing
#
def main():
    print('HUT reboot using J2534 compatible scanner')

    parser = argparse.ArgumentParser()
    parser.add_argument('target', type = str, default = 'normal', choices = [], help = 'Boot target')
    parser.add_argument('--uds-mode', type = str, default = 'user', choices = ['user', 'developer'], help = 'Work mode')
    parser.add_argument('--windll', type = str, default = 'smj2534.dll', help = 'Path to J2534 shared library')
    parser.add_argument('--loglevel', default = 'ERROR', choices = ['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    args = parser.parse_args()

    logging.basicConfig(level = getattr(logging, args.loglevel))
    rebootHutToTarget(args.target, args.uds_mode, args.windll)

#
# Launches main
#
if __name__ == "__main__":
    main()   