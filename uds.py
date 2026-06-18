#!/usr/bin/env python
# -*- coding: utf-8 -*-
import udsoncan
from udsoncan.client import Client
from udsoncan.connections import BaseConnection
from udsoncan import configs as Configs
from udsoncan import exceptions as Exceptions
from udsoncan import services as Services
import bidict
import struct
from abc import ABC
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, TypeVar

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
@dataclass
class SecurityParameters:
    poly: int
    mask: int = 0xFFFFFFFF

#
#
#
@dataclass
class VehicleConfigParameters:
    did: int
    length: int

#
# Unit controlled by UDS
#
class Ecu(ABC):
    #
    # OEM DID
    #
    class DataIdentifier(udsoncan.DataIdentifier):
        VehicleConfig = 0xF1B1

    #
    #
    #
    @dataclass
    class Settings:
        tx_id: int
        rx_id: int
        vehicle_config: VehicleConfigParameters | None
        security: SecurityParameters | None = None

    #
    #
    #
    class RawCodec(udsoncan.DidCodec):
        #
        #
        #
        def __init__(self, length):
            self.length = length

        #
        #
        #
        def encode(self, value: bytes) -> bytes:
            value_length = len(value)
            if value_length != len(self):
                raise ValueError(f'Invalid value length: {value_length}')
            
            return value

        #
        #
        #
        def decode(self, payload: bytes):
            return payload

        #
        #
        #
        def __len__(self):
            return self.length
        
    #
    #
    #
    DefaultSecurityLevel = 1

    #
    #
    #
    @staticmethod    
    def _generateKey(seed: int, poly: int, mask: int) -> int:
        if seed < 0 or seed > 0xFFFFFFFF:
            raise ValueError(f'Invalid UINT32 seed: {seed}')
        
        key = seed
        if key != 0:
            for _ in range (0, 35):
                msb = key & 0x80000000
                key = (key << 1) & 0xFFFFFFFF
                if msb != 0:
                    key ^= poly

        return key & mask
    
    #
    #
    #
    @staticmethod
    def _securityAlgo(level: int, seed: bytes, params: SecurityParameters) -> bytes:
        if level != Ecu.DefaultSecurityLevel:
            raise ValueError(f'Security level {level} is not supported')

        key = Ecu._generateKey(int.from_bytes(seed, 'big'), params.poly, params.mask)
        return bytes(key.to_bytes(4, 'big'))
    
    #
    #
    #
    @classmethod
    def _getDataIdentifiers(cls, settings: Settings) -> dict[int, udsoncan.DidCodec]:
        dids = {
            udsoncan.DataIdentifier.VIN: udsoncan.AsciiCodec(17)
        }

        vehicle_config = settings.vehicle_config
        if vehicle_config is not None:
            if vehicle_config.length <= 0:
                raise ValueError(f'Invalid config length: {vehicle_config.length}')

            dids[vehicle_config.did] = Ecu.RawCodec(vehicle_config.length);

        return dids
    
    #
    #
    #
    @classmethod 
    def _getConfig(cls, settings: Settings):
        config = Configs.default_client_config.copy()

        #
        # Default 50 ms is too short for non-realtime PC even with J2534 adapter
        #
        config['use_server_timing'] = False  
        config['p2_timeout'] = 2.0
        config['p2_star_timeout'] = 5.0

        #
        # ReadDataByIdentifier/WriteDataByIdentifier (0x22/0x27)
        #
        config['data_identifiers'] = cls._getDataIdentifiers(settings)

        #
        # SecurityAccess (0x27)
        #
        security = settings.security
        if security is not None:
            config['security_algo'] = Ecu._securityAlgo
            config['security_algo_params'] = security

        return config
    
    #
    #
    #
    def _getVehicleConfigDid(self) -> int:
        vehicle_config = self.settings.vehicle_config
        if vehicle_config is None:
            raise ValueError('Vehicle config is not supported')
        
        return vehicle_config.did

    #
    #
    #
    def __init__(self, mode: Mode, name: str, make_conn: Callable[[int, int], BaseConnection], settings: Settings) -> None:
        super().__init__()
        conn = make_conn(settings.tx_id, settings.rx_id)
        config = type(self)._getConfig(settings)

        self.mode = mode
        self.name = name
        self.settings = settings
        self.client = Client(conn, config)

    #
    #
    #
    def __enter__(self):
        self.client.__enter__()
        return self
    
    #
    #
    #
    def __exit__(self, exc_type, exc_value, traceback):
        self.client.__exit__(exc_type, exc_value, traceback)

    #
    #
    #
    T = TypeVar('T')
    def callSafe(self, handler: Callable[..., T], *args, **kwargs) -> T | None:
        try:
            return handler(*args, **kwargs)
        except Exceptions.TimeoutException as exc:
            print(f'{self.name} request timeout')
        except Exceptions.NegativeResponseException as exc:
            print(f'{self.name} refused request with code {exc.response.code_name} (0x{exc.response.code:X})')
        except (Exceptions.InvalidResponseException, Exceptions.UnexpectedResponseException) as exc:
            print(f'{self.name} sent an invalid payload: {exc.response.original_payload}')

    #
    #
    #
    def resetHard(self):
        self.client.ecu_reset(Services.ECUReset.ResetType.hardReset)

    #
    #
    #
    def getVehicleConfig(self) -> bytes:
        did = self._getVehicleConfigDid()
        return self.client.read_data_by_identifier_first(did)
    
    #
    #
    #
    def getVehicleConfigStr(self) -> str:
        raw_config = self.getVehicleConfig()
        return raw_config.hex().upper()

    #
    #
    #
    def setVehicleConfig(self, config: bytes) -> None:
        did = self._getVehicleConfigDid()
        self.client.change_session(Services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
        self.client.unlock_security_access(Ecu.DefaultSecurityLevel)
        self.client.write_data_by_identifier(did, config)

    #
    #
    #
    def setVehicleConfigStr(self, config: str) -> None:
        raw_config = bytes.fromhex(config)
        self.setVehicleConfig(raw_config)

#
# Harman GWMv2
#
class HarmanHut(Ecu):
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
        
    @classmethod
    def _getDataIdentifiers(cls, settings: Ecu.Settings) -> dict[int, udsoncan.DidCodec]:
        dids = super()._getDataIdentifiers(settings)
        dids[HarmanHut.DataIdentifier.PowerPolicy] = HarmanHut.PowerPolicyCodec()
        return dids

    #
    #
    #
    def __init__(self, mode: Mode, make_conn: Callable[[int, int], BaseConnection]) -> None:
        super().__init__(
                mode,
                'HUT',
                make_conn,
                Ecu.Settings(
                    tx_id = 0x773,
                    rx_id = 0x7B3,
                    vehicle_config = VehicleConfigParameters(
                        did = Ecu.DataIdentifier.VehicleConfig,
                        length = 66
                    ),
                    security = SecurityParameters(
                        poly = 0x48205554  # 'H UT'
                    )
                )
            )

    #
    #
    #
    def setBootTarget(self, target: str) -> None:
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
            
        self.client.change_session(Services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
        self.client.unlock_security_access(Ecu.DefaultSecurityLevel)
        self.client.write_data_by_identifier(HarmanHut.DataIdentifier.PowerPolicy, bytes([0x4]) + value.to_bytes(1, 'big'))

#
# CYM IP (Cluster)
#
class CymIp(Ecu):
    #
    #
    #
    def __init__(self, mode: Mode, make_conn: Callable[[int, int], BaseConnection]) -> None:
        super().__init__(
                mode,
                'IP',
                make_conn,
                Ecu.Settings(
                    tx_id = 0x766,
                    rx_id = 0x7A6,
                    vehicle_config = VehicleConfigParameters(
                        did = Ecu.DataIdentifier.VehicleConfig,
                        length = 66
                    ),
                    security = SecurityParameters(
                        poly = 0x20204950  # '  IP'
                    )
                )
            )

#
# HUD
#
class Hud(Ecu):
    #
    #
    #
    def __init__(self, mode: Mode, make_conn: Callable[[int, int], BaseConnection]) -> None:
        super().__init__(
            mode,
            'HUD',
            make_conn,
            Ecu.Settings(
                tx_id = 0x777,
                rx_id = 0x7B7,
                vehicle_config = VehicleConfigParameters(
                    did = Ecu.DataIdentifier.VehicleConfig,
                    length = 31
                ),
                security = SecurityParameters(
                    poly = 0x28904238  # '(.B8', but seed is always 0x4272696C ('Bril')
                )
            )
        )

#
# TPMS
#
class Tpms(Ecu):
    #
    #
    #
    class DataIdentifier(Ecu.DataIdentifier):
        VehicleConfig = 0xB000

    #
    #
    #
    def __init__(self, mode: Mode, make_conn: Callable[[int, int], BaseConnection]) -> None:
        super().__init__(
            mode,
            'HUD',
            make_conn,
            Ecu.Settings(
                tx_id = 0x76C,
                rx_id = 0x7AC,
                vehicle_config = VehicleConfigParameters(
                    did = 0xB000,
                    length = 31
                ),
                security = SecurityParameters(
                    poly = 0x54504D53,  # 'TPMS'
                    mask = 0xFFFFFF     # 24 bits
                )
            )
        ) 
