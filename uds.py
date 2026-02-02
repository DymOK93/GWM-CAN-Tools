#!/usr/bin/env python
# -*- coding: utf-8 -*-
import udsoncan
from udsoncan.client import Client
from udsoncan.connections import BaseConnection, J2534Connection
from udsoncan import configs as Configs
from udsoncan import exceptions as Exceptions
from udsoncan import services as Services
import bidict
import struct
from abc import ABC
from enum import IntEnum
from typing import Callable

#
# Operating mode
#   - 'User' allows only safe operations 
#   - 'Developer' allows any operations, including those requiring physical access to the device
#
class Mode(IntEnum):
    User = 0
    Developer = 1

#
# Available operating mode
#
_kModes = bidict.bidict({
    'user': Mode.User,
    'developer': Mode.Developer
})

#
# Make operating mode from string
#
def getModeValue(name: str) -> Mode:
    value = _kModes.get(name)
    if value is None:
        raise ValueError(f'Unknown mode {name}')
    return value

#
# Converts operating mode to string
#
def getModeName(value: Mode) -> str:
    name = _kModes.inverse.get(value)
    if name is None:
        raise ValueError(f'Unknown mode {value}')
    return name

#
#
#
def isHardwareConnection(conn: BaseConnection) -> bool:
    return isinstance(conn, J2534Connection)

#
# Unit controlled by UDS
#
class Ecu(ABC):
    def __init__(self, mode: Mode, client: Client) -> None:
        super().__init__()
        self.client = client
        self.mode = mode

    def __enter__(self):
        self.client.__enter__()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.client.__exit__(exc_type, exc_value, traceback)

#
# Harman GWMv2
#
class HarmanHut(Ecu):
    #
    #
    #
    DefaultSecurityLevel = 1

    #
    # OEM DID
    #
    class DataIdentifier(udsoncan.DataIdentifier):
        PowerPolicy = 0xFDF0

    #
    # Pass-thru codec
    #
    class PowerPolicyCodec(udsoncan.DidCodec):
        #
        #
        #
        def encode(self, value: tuple) -> bytes:
            target, data = value
            return struct.pack('BB', target, data)

        #
        #
        #
        def decode(self, payload: bytes) -> tuple:
            target = payload[0]   
            data = payload[1]
            return (target, data)

        #
        #
        #
        def __len__(self):
            return 2
        
    #
    #
    #
    @staticmethod    
    def _generateKey(seed: int) -> int:
        if seed < 0 or seed > 0xFFFFFFFF:
            raise ValueError(f'Invalid UINT32 seed: {seed}')
        
        key = seed
        if key != 0:
            for idx in range (0, 35):
                msb = key & 0x80000000
                key = (key << 1) & 0xFFFFFFFF
                if msb != 0:
                    key ^= 0x48205554
        return key
    
    #
    #
    #
    @staticmethod
    def _securityAlgo(level: int, seed: bytes, params) -> bytes:
        if level != 1:
            raise ValueError(f'Security level {level} is not supported')

        key = HarmanHut._generateKey(int.from_bytes(seed, 'big'))
        return bytes(key.to_bytes(4, 'big'))

    #
    #
    #
    def __init__(self, mode: Mode, make_conn: Callable[[int, int], BaseConnection]) -> None:
        conn = make_conn(0x773, 0x7B3)
        config = Configs.default_client_config.copy()
        config['use_server_timing'] = not isHardwareConnection(conn)
        config['security_algo'] = HarmanHut._securityAlgo
        config['data_identifiers'] = {HarmanHut.DataIdentifier.PowerPolicy: HarmanHut.PowerPolicyCodec}
        super().__init__(mode, Client(conn, config))

    #
    #
    #
    def reboot(self, target: str) -> None:
        choices = {
            'normal': (0, Mode.User),
            'recovery': (1, Mode.User),
            'elk': (3, Mode.Developer)}
        choice = choices.get(target)
        if choice is None:
            raise ValueError(f'HUT reboot to {target} is not supported (available: {list(choices.keys())})')
        
        value, min_mode = choice
        if self.mode < min_mode:
            raise ValueError(f'HUT reboot to {target} requires at least {getModeName(min_mode)} mode')
            
        try:
            self.client.change_session(Services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
            self.client.unlock_security_access(HarmanHut.DefaultSecurityLevel)
            self.client.write_data_by_identifier(HarmanHut.DataIdentifier.PowerPolicy, bytes([0x4]) + value.to_bytes(1, 'big'))
            self.client.ecu_reset(Services.ECUReset.ResetType.hardReset)
        except Exceptions.TimeoutException as exc:
            print(f'HUT request timeout')
        except Exceptions.NegativeResponseException as exc:
            print(f'HUT refused reboot request with code {exc.response.code_name} (0x{exc.response.code:X})')
        except (Exceptions.InvalidResponseException, Exceptions.UnexpectedResponseException) as exc:
            print(f'HUT sent an invalid payload: {exc.response.original_payload}')
