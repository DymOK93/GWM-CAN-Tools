#!/usr/bin/env python
# -*- coding: utf-8 -*-
from udsoncan.connections import J2534Connection
import argparse
import logging
import uds

#
#
#
def rebootIp(uds_mode: str, windll: str) -> None:
    print(f'Reboot IP')
    with uds.CymIp(uds.getModeValue(uds_mode), 
                       lambda txid, rxid: J2534Connection(windll, rxid, txid)) as ip:
        ip.callSafe(lambda: ip.resetHard())

#
# Does processing
#
def main():
    print('IP reboot using J2534 compatible scanner')

    parser = argparse.ArgumentParser()
    parser.add_argument('--uds-mode', type = str, default = 'user', choices = ['user', 'developer'], help = 'Work mode')
    parser.add_argument('--windll', type = str, default = 'smj2534.dll', help = 'Path to J2534 shared library')
    parser.add_argument('--loglevel', default = 'ERROR', choices = ['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    args = parser.parse_args()

    logging.basicConfig(level = getattr(logging, args.loglevel))
    rebootIp(args.uds_mode, args.windll)

#
# Launches main
#
if __name__ == "__main__":
    main()   