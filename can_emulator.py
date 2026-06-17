#!/usr/bin/env python
# -*- coding: utf-8 -*-
import can
import isotp
from udsoncan.connections import PythonIsoTpConnection
from abc import ABC, abstractmethod
import argparse
import logging
import time
import threading
import uds
from dataclasses import dataclass, fields
from typing import Callable, TypeVar

#
# Program state
#
class Emulator:
    #
    #
    #
    def __init__(self, bus: can.interface.Bus, args) -> None:
        super().__init__()
        self.bus = bus
        self.uds_mode = uds.getModeValue(args.uds_mode)
    
#
# Task with the ability to start and stop
#
class TaskBase(ABC): 
    #
    #
    #
    def _raiseActionSkip(self, state: str):
        raise ValueError(f'Skip: {self.name} is already {state}')

    #
    #
    # 
    @abstractmethod
    def _create(self):
        pass

    #
    #
    #
    @abstractmethod
    def _destroy(self, task):
        pass

    #
    #
    #
    def __init__(self, name: str, bus: can.interface.Bus) -> None:
        self.name = name
        self.bus = bus
        self.task = None

    #
    #
    #
    def start(self) -> None:
        if not self.task is None:
            self._raiseActionSkip('ON')

        print(f'Turn {self.name} ON')
        self.task = self._create()

    #
    #
    #
    def stop(self) -> None:
        if self.task is None:
            self._raiseActionSkip('OFF')

        print(f'Turn {self.name} OFF')
        self._destroy(self.task)
        self.task = None

#
# @brief Ignition periodic task
#
class IgnitionTask(TaskBase):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__('ignition', bus)

    #
    #
    #
    def _create(self):
        msg = can.Message(
            arbitration_id = 0x501,
            data = bytes(8),
            is_extended_id = False)
        for i in range(0, 4):
            self.bus.send(msg)
            time.sleep(0.02)
        
        task = self.bus.send_periodic(msg, 0.5)
        assert isinstance(task, can.CyclicSendTaskABC)
        return task

    #
    #
    #
    def _destroy(self, task):
        task.stop()

#
# HUT standby periodic task
#
class HutStandbyTask(TaskBase):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus) -> None:
        super().__init__('HUT display', bus)

    #
    #
    #
    def _create(self):
        msg = can.Message(
                arbitration_id = 0x295,
                data = bytes.fromhex('B1A000C000000006'),
                is_extended_id = False)
        task = self.bus.send_periodic(msg, 1)
        assert isinstance(task, can.CyclicSendTaskABC)
        return task

    #
    #
    #
    def _destroy(self, task):
        task.stop()
        self.bus.send(can.Message(
            arbitration_id = 0x295,
            data = bytes.fromhex('B120000000000007'),
            is_extended_id = False))
        
#
#
#
@dataclass
class BodyState:
    left_turn_signal: bool = False
    right_turn_signal: bool = False

#
# @brief KBCM periodic task
#
class BodyTask(TaskBase):
    #
    #
    #
    kDefaultState = 0xC00000
    
    #
    #
    #
    @staticmethod
    def convert(state: BodyState) -> int:
        raw_state = BodyTask.kDefaultState

        if state.left_turn_signal:
            raw_state |= 0x800

        if state.right_turn_signal:
            raw_state |= 0x1000

        return raw_state
    
    #
    #
    #
    @staticmethod
    def calcCrc(data: bytes) -> int:
        crc = 0x38
        for byte in data:          # data = bytes[1:8] (7 байт)
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) & 0xFF) ^ 0x1D
                else:
                    crc = (crc << 1) & 0xFF
        return crc
    
    #
    #
    #
    @staticmethod
    def _makeData(state: int, counter: int | None) -> bytearray:
        data = bytearray(8)
        data[7] = 0 if counter is None else (counter + 1) % 15  # 0x0...0xE
        data[1:7] = state.to_bytes(6, 'little')
        data[0] = BodyTask.calcCrc(data[1:])
        return data
    
    #
    #
    #
    def _getState(self) -> int:
        with self.lock as _:
            return self.state
        
    #
    #
    #
    def _setState(self, state: int) -> None:
        with self.lock as _:
            self.state = state

    #
    #
    #
    def _mutate(self, old_data: bytes | None) -> bytearray:
        state = self._getState() & 0x0000FFFFFFFFFFFF
        return BodyTask._makeData(state, None if old_data is None else old_data[7])
    
    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__('body', bus)
        self.lock = threading.Lock()
        self.state = self.kDefaultState

    #
    #
    #
    def _create(self):
        msg = can.Message(
            arbitration_id = 0x165,
            data = self._mutate(None),
            is_extended_id = False)
        mutator = lambda msg: setattr(msg, 'data', self._mutate(msg.data))
        task = self.bus.send_periodic(msg, 0.2, modifier_callback = mutator)
        assert isinstance(task, can.CyclicSendTaskABC)
        return task

    #
    #
    #
    def _destroy(self, task):
        task.stop()

    #
    #
    #
    def update(self, state: BodyState) -> None:
        old_state = self._getState()
        new_state = BodyTask.convert(state)
        if old_state == new_state:
            raise ValueError('Body state is not changed')

        self._setState(new_state)
        print(f'Body state change: 0x{old_state:X} -> 0x{new_state:X}')

        old_data_hex = BodyTask._makeData(old_state, None).hex().upper()
        new_data_hex = BodyTask._makeData(new_state, None).hex().upper()
        print(f'Body data: {old_data_hex} -> {new_data_hex}')

#
#
#
@dataclass
class WheelButtonState:
    volume_up: bool = False
    volume_down: bool = False
    back: bool = False
    ok: bool = False
    arrow_up: bool = False
    arrow_down: bool = False

#
# @brief KBCM periodic task
#
class WheelButtonTask(TaskBase):
    #
    #
    #
    kDefaultState = 0xFCF00F0F000F
    
    #
    #
    #
    @staticmethod
    def convert(state: WheelButtonState) -> int:
        raw_state = WheelButtonTask.kDefaultState

        if state.volume_up:
            raw_state |= 0x4000

        if state.volume_down:
            raw_state |= 0x1000

        if state.back:
            raw_state |= 0x10000000000

        if state.ok:
            raw_state |= 0x400000

        if state.arrow_up:
            raw_state |= 0x40

        if state.arrow_down:
            raw_state |= 0x10

        return raw_state
    
    #
    #
    #
    @staticmethod
    def calcCrc(data: bytes) -> int:
        crc = 0xD7
        for byte in data:          # data = bytes[1:8] (7 байт)
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) & 0xFF) ^ 0x1D
                else:
                    crc = (crc << 1) & 0xFF
        return crc
    
    #
    #
    #
    @staticmethod
    def _makeData(state: int, counter: int | None) -> bytearray:
        data = bytearray(8)
        data[7] = 0 if counter is None else (counter + 1) % 15  # 0x0...0xE
        data[1:7] = state.to_bytes(6, 'little')
        data[0] = BodyTask.calcCrc(data[1:])
        return data
    
    #
    #
    #
    def _getState(self) -> int:
        with self.lock as _:
            return self.state
        
    #
    #
    #
    def _setState(self, state: int) -> None:
        with self.lock as _:
            self.state = state

    #
    #
    #
    def _mutate(self, old_data: bytes | None) -> bytearray:
        state = self._getState() & 0x0000FFFFFFFFFFFF
        return BodyTask._makeData(state, None if old_data is None else old_data[7])
    
    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__('wheel', bus)
        self.lock = threading.Lock()
        self.state = self.kDefaultState

    #
    #
    #
    def _create(self):
        msg = can.Message(
            arbitration_id = 0x244,
            data = self._mutate(None),
            is_extended_id = False)
        mutator = lambda msg: setattr(msg, 'data', self._mutate(msg.data))
        task = self.bus.send_periodic(msg, 0.2, modifier_callback = mutator)
        assert isinstance(task, can.CyclicSendTaskABC)
        return task

    #
    #
    #
    def _destroy(self, task):
        task.stop()

    #
    #
    #
    def update(self, state: WheelButtonState) -> None:
        old_state = self._getState()
        new_state = WheelButtonTask.convert(state)
        if old_state == new_state:
            raise ValueError('WheelButton state is not changed')

        self._setState(new_state)
        print(f'WheelButton state change: 0x{old_state:X} -> 0x{new_state:X}')

        old_data_hex = WheelButtonTask._makeData(old_state, None).hex().upper()
        new_data_hex = WheelButtonTask._makeData(new_state, None).hex().upper()
        print(f'WheelButton data: {old_data_hex} -> {new_data_hex}')

#
# Translator for on/off
#
def isTurnOnOff(arg: str) -> bool | None:
    if arg == '1' or arg == 'on':
        return True
    
    if arg == '0' or arg == 'off':
        return False

    return None 

#
# Executable command
#
class CommandBase(ABC):
    #
    #
    #
    def __init__(self) -> None:
        super().__init__()

    #
    #
    #
    @abstractmethod
    def execute(self, arg: str) -> None:
        pass

#
# Command with 'ON' and 'OFF' states
#
class OnOffTaskCommand(CommandBase):
    #
    #
    #
    def __init__(self, task: TaskBase) -> None:
        super().__init__()
        self.task = task

    #
    #
    #
    def execute(self, arg: str) -> None:
        start = isTurnOnOff(arg)
        if start is None:
            raise ValueError(f'Unknown argument {arg} for {self.task.name}')

        if start:
            self.task.start()
        else:
            self.task.stop()
            
#
# Ignition command
# @warning Some commands require the ignition to be turned on first
# @remark Messages from the real trace contains data = bytes.fromhex('0110010401000000')
# but the devices usually ignore message contents
#
class IgnitionCommand(OnOffTaskCommand):
    def __init__(self, bus: can.interface.Bus):
        super().__init__(IgnitionTask(bus))

#
# @brief HUT standby command 
# Controls display and wireless interfaces (WiFi, BT)
# @warning The ignition should be on
#
class HutStandbyCommand(OnOffTaskCommand):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__(HutStandbyTask(bus))

#
# Context-manageable notifier
#
class Notifier(can.Notifier):
    #
    #
    #
    def __init__(self, bus):
        super().__init__(bus, [])

    #
    #
    #
    def __enter__(self):
        return self

    #
    #
    #
    def __exit__(self, exc_type, exc_value, traceback):
        super().stop() 

#
# Various UDS commands
#
class UdsCommandBase(CommandBase):
    #
    #
    #
    @staticmethod
    def _createConnection(bus: can.interface.Bus, notifier: Notifier, txid: int, rxid: int) -> PythonIsoTpConnection:
        params = {
            'stmin': 64,                            # Will request the sender to wait 32ms between consecutive frame. 0-127ms or 100-900ns with values from 0xF1-0xF9
            'blocksize': 8,                         # Request the sender to send 8 consecutives frames before sending a new flow control message
            'wftmax': 0,                            # Number of wait frame allowed before triggering an error
            'tx_data_length': 8,                    # Link layer (CAN layer) works with 8 byte payload (CAN 2.0)
            'tx_data_min_length': None,             # Minimum length of CAN messages. When different from None, messages are padded to meet this length. Works with CAN 2.0 and CAN FD.
            'tx_padding': 0,                        # Will pad all transmitted CAN messages with byte 0x00.
            'rx_flowcontrol_timeout': 1000,         # Triggers a timeout if a flow control is awaited for more than 1000 milliseconds
            'rx_consecutive_frame_timeout': 1000,   # Triggers a timeout if a consecutive frame is awaited for more than 1000 milliseconds
            'override_receiver_stmin': None,        # When sending, respect the stmin requirement of the receiver. Could be set to a float value in seconds.
            'max_frame_size': 4095,                 # Limit the size of receive frame.
            'can_fd': False,                        # Does not set the can_fd flag on the output CAN messages
            'bitrate_switch': False,                # Does not set the bitrate_switch flag on the output CAN messages
            'rate_limit_enable': False,             # Disable the rate limiter
            'rate_limit_max_bitrate': 1000000,      # Ignored when rate_limit_enable=False. Sets the max bitrate when rate_limit_enable=True
            'rate_limit_window_size': 0.2,          # Ignored when rate_limit_enable=False. Sets the averaging window size for bitrate calculation when rate_limit_enable=True
            'listen_mode': False,                   # Does not use the listen_mode which prevent transmission.
        }
        addr = isotp.Address(
            addressing_mode = isotp.AddressingMode.Normal_11bits,
            txid = txid,
            rxid = rxid)
        transport = isotp.NotifierBasedCanStack(
            bus, 
            notifier,
            address = addr,
            params = params)
        return PythonIsoTpConnection(transport)
    
    #
    #
    #
    T = TypeVar('T', bound = uds.Ecu)
    R = TypeVar('R')
    def _executeSafe(self, handler: Callable[[T], R]) -> R:
        with Notifier(self.bus) as notifier:
            make_conn = lambda txid, rxid: UdsCommandBase._createConnection(self.bus, notifier, txid, rxid)
            with self.ecu_cls(self.uds_mode, make_conn) as ecu:
                return ecu.callSafe(handler, ecu)
        
    #
    #
    #
    T = TypeVar('T', bound = uds.Ecu)
    def __init__(self, bus: can.interface.Bus, uds_mode: uds.Mode, ecu_cls: type[T]):
        super().__init__()
        self.bus = bus
        self.uds_mode = uds_mode
        self.ecu_cls = ecu_cls

#
# @brief Various HUT commands
#
class HutCommandBase(UdsCommandBase):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus, uds_mode: uds.Mode):
        super().__init__(bus, uds_mode, uds.HarmanHut)

#
# @brief HUT reboot command 
# Reboots the HUT to the specified boot target via the UDS interface
# @warning The ignition should be on
# @warning Doesn't work in Android recovery and ELK
#
class HutRebootCommand(HutCommandBase):
    #
    #
    #
    def _rebootToBootTarget(self, hut: uds.HarmanHut, target: str) -> None:
        hut.setBootTarget(target)
        hut.resetHard()

    #
    #
    #
    def execute(self, target) -> None:
        if not isinstance(target, str):
            raise ValueError('Target must be provided')

        print(f'Reboot HUT to {target}')
        self._executeSafe(lambda hut: self._rebootToBootTarget(hut, target))
        
#
# @brief Various IP commands
#
class IpCommandBase(UdsCommandBase):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus, uds_mode: uds.Mode):
        super().__init__(bus, uds_mode, uds.CymIp)

#
# @brief IP reboot command 
# Reboots the IP via the UDS interface
#
class IpRebootCommand(IpCommandBase):
    #
    #
    #
    def execute(self, _) -> None:
        print(f'Reboot IP')
        self._executeSafe(lambda ip: ip.resetHard())

#
# @brief IP get config command 
# Reads the IP config via the UDS interface
#
class IpGetConfigCommand(IpCommandBase):
    #
    #
    #
    def execute(self, _: str):
        print(f'Read IP config')
        self._executeSafe(lambda ip: print(f'{ip.getVehicleConfigStr()}'))

#
# @brief IP get config command 
# Reads the IP config via the UDS interface
#
class IpSetConfigCommand(IpCommandBase):
    #
    #
    #
    def execute(self, config: str):
        if not isinstance(config, str):
            raise ValueError('Config must be provided')

        print(f'Write IP config')
        self._executeSafe(lambda ip: ip.setVehicleConfigStr(config))

#
# @brief Body command 
# Controls display and wireless interfaces (WiFi, BT)
# @warning The ignition should be on
#
class BodyCommand(CommandBase):
    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__()
        self.task = BodyTask(bus)
        self.state = BodyState()

    #
    #
    #
    def _apply(self, component: str, action: str) -> None:
        enabled = isTurnOnOff(action)
        if enabled is None:
            raise ValueError(f'Action {action} is not supported')
        
        if component == 'all' or component == 'a':
            self.state = BodyState(**{f.name: enabled for f in fields(BodyState)})
        else:
            field = {
                'lts': 'left_turn_signal', 
                'rts': 'right_turn_signal'
            }.get(component)
            if field is None:
                raise ValueError(f'Component {component} is not supported')
            
            setattr(self.state, field, enabled)

    #
    #
    #
    def execute(self, arg) -> None:
        if arg is None:
            raise ValueError('Argument must be provided')
        
        parts = arg.split('@')
        if len(parts) == 1:
            start = isTurnOnOff(arg)
            if start is None:
                raise ValueError(f'Argument {arg} is not supported')
            if start:
                self.task.start()
            else:
                self.task.stop()
        elif len(parts) == 2:
            self._apply(*parts)
            self.task.update(self.state)
        else:
            raise ValueError(f'Invalid part count: {arg}')
        
#
# @brief Body command 
# Controls display and wireless interfaces (WiFi, BT)
# @warning The ignition should be on
#
class WheelButtonCommand(CommandBase):
    #
    #
    #
    kShortDuration = 0.3
    kNormalDuration = 1
    kLongDuration = 5

    #
    #
    #
    @staticmethod
    def _getState(button: str) -> WheelButtonState:
        state = WheelButtonState()

        field = {
            'vu': 'volume_up',
            'vd': 'volume_down',
            'bk': 'back',
            'ok': 'ok',
            'au': 'arrow_up',
            'ad': 'arrow_down'
        }.get(button)
        if field is None:
            raise ValueError(f'Invalid field: {field}')
        
        setattr(state, field, True)
        return state
    
    #
    #
    #
    @staticmethod 
    def _getDuration(duration: str) -> float:
        if duration == 'short' or duration == 's':
            return WheelButtonCommand.kShortDuration
        
        if duration == 'normal' or duration == 'n':
            return WheelButtonCommand.kNormalDuration
        
        if duration == 'long' or duration == 'l':
            return WheelButtonCommand.kLongDuration
        
        return float(duration)
    
    #
    # TODO: pass duration to task
    #
    def _pressButton(self, state: WheelButtonState, duration: float):
        self.task.update(state)
        self.task.start()
        time.sleep(duration)
        self.task.update(WheelButtonState())
        time.sleep(WheelButtonCommand.kShortDuration)
        self.task.stop()

    #
    #
    #
    def __init__(self, bus: can.interface.Bus):
        super().__init__()
        self.task = WheelButtonTask(bus)

    #
    #
    #
    def execute(self, arg) -> None:
        if arg is None:
            raise ValueError('Argument must be provided')
        
        parts = arg.split('@')
        if len(parts) != 2:
            raise ValueError(f'Invalid part count: {arg}')
        
        pressed_state = WheelButtonCommand._getState(parts[0])
        duration = WheelButtonCommand._getDuration(parts[1])
        self._pressButton(pressed_state, duration)

#
# @brief UDS listen command
# Passively sniffs the bus and prints raw CAN messages
# @remark Runs until Ctrl+C
#
class RawListenCommand(CommandBase):
    #
    #
    #
    @staticmethod
    def _parseIds(part: str) -> set[int]:
        return {int(token.strip(), 0) for token in part.split(",") if token.strip()}    

    #
    #
    #
    @staticmethod
    def _makeIdFilter(filters: str) -> tuple[set[int], set[int]]:
        if filters is None:
            return (set(), set())

        enabled_part, disabled_part = (filters.split(";", 1) + [""])[:2]
        enabled_ids = RawListenCommand._parseIds(enabled_part)
        disabled_ids = RawListenCommand._parseIds(disabled_part)
        return enabled_ids, disabled_ids

    #
    #
    #
    def __init__(self, bus: can.interface.Bus) -> None:
        super().__init__()
        self.bus = bus

    #
    #
    #
    def execute(self, filters: str) -> None:
        print('Listening for raw traffic (Ctrl+C to stop)')
        enabled_ids, disabled_ids = RawListenCommand._makeIdFilter(filters)

        print(f'Enabled: {enabled_ids}')
        print(f'Disabled: {disabled_ids}')
        while True:
            msg = self.bus.recv(0.5)
            if msg is None:
                continue

            id = msg.arbitration_id
            if (len(enabled_ids) > 0 and id not in enabled_ids) or id in disabled_ids:
                continue

            print(f'  0x{id:03X} {msg.data.hex(" ")}')

#
# @brief UDS listen command
# Passively sniffs the bus and prints discovered UDS request/response CAN IDs (11-bit only)
# @remark Decodes only the first ISO-TP frame to detect the service; runs until Ctrl+C
#
class UdsListenCommand(CommandBase):
    #
    # Request SID -> service name (positive response = SID | 0x40, negative = 0x7F)
    #
    kServices = {
        0x10: 'DiagnosticSessionControl', 0x11: 'ECUReset',
        0x14: 'ClearDiagnosticInformation', 0x19: 'ReadDTCInformation',
        0x22: 'ReadDataByIdentifier', 0x23: 'ReadMemoryByAddress',
        0x24: 'ReadScalingDataByIdentifier', 0x27: 'SecurityAccess',
        0x28: 'CommunicationControl', 0x2A: 'ReadDataByPeriodicIdentifier',
        0x2C: 'DynamicallyDefineDataIdentifier', 0x2E: 'WriteDataByIdentifier',
        0x2F: 'InputOutputControlByIdentifier', 0x31: 'RoutineControl',
        0x34: 'RequestDownload', 0x35: 'RequestUpload', 0x36: 'TransferData',
        0x37: 'RequestTransferExit', 0x38: 'RequestFileTransfer',
        0x3D: 'WriteMemoryByAddress', 0x3E: 'TesterPresent',
        0x83: 'AccessTimingParameter', 0x84: 'SecuredDataTransmission',
        0x85: 'ControlDTCSetting', 0x86: 'ResponseOnEvent', 0x87: 'LinkControl',
    }

    #
    # Extract the UDS payload from an ISO-TP frame (SF/FF only)
    #
    @staticmethod
    def _decode(data: bytes) -> bytes | None:
        if not data:
            return None
        pci = data[0] >> 4
        if pci == 0:                                # ISO-TP Single Frame
            return bytes(data[1:1 + (data[0] & 0x0F)])
        if pci == 1:                                # ISO-TP First Frame
            return bytes(data[2:])
        return None                                 # CF / FC are ignored

    #
    # Classify payload -> ('txid'|'rxid', request_sid) or None if not UDS
    #
    @staticmethod
    def _classify(payload: bytes) -> tuple[str, int] | None:
        sid = payload[0]
        if sid == 0x7F and len(payload) >= 2:                       # negative response
            base, role = payload[1], 'rxid'
        elif (sid & 0x40) and (sid & 0xBF) in UdsListenCommand.kServices:  # positive response
            base, role = sid & 0xBF, 'rxid'
        elif sid in UdsListenCommand.kServices:                     # request
            base, role = sid, 'txid'
        else:
            return None
        return role, base

    #
    #
    #
    def __init__(self, bus: can.interface.Bus) -> None:
        super().__init__()
        self.bus = bus

    #
    #
    #
    def execute(self, _: str) -> None:
        print('Listening for UDS traffic (Ctrl+C to stop)')
        seen = set()
        while True:
            msg = self.bus.recv(0.5)
            if msg is None or msg.is_extended_id:   # 11-bit only
                continue

            payload = UdsListenCommand._decode(msg.data)
            if not payload:
                continue

            result = UdsListenCommand._classify(payload)
            if result is None:
                continue
            role, base = result
            name = UdsListenCommand.kServices.get(base, f'SID 0x{base:02X}')

            key = (msg.arbitration_id, role)
            if key not in seen:
                seen.add(key)
                print(f'{role}=0x{msg.arbitration_id:03X}  {name}')
            print(f'  0x{msg.arbitration_id:03X} {role:4} {payload.hex(" ")}')

#
# Event loop
# @param[in] bus CAN bus instance
#
def eventLoop(emu: Emulator) -> None:
    cmds = {
        'ign': IgnitionCommand(emu.bus),
        'hut-stb': HutStandbyCommand(emu.bus),
        'hut-reboot': HutRebootCommand(emu.bus, emu.uds_mode),
        'ip-reboot': IpRebootCommand(emu.bus, emu.uds_mode),
        'ip-getcfg': IpGetConfigCommand(emu.bus, emu.uds_mode),
        'ip-setcfg': IpSetConfigCommand(emu.bus, emu.uds_mode),
        'body': BodyCommand(emu.bus),
        'wheel-btn': WheelButtonCommand(emu.bus),
        'raw-listen': RawListenCommand(emu.bus),
        'uds-listen': UdsListenCommand(emu.bus)
    }

    while True:
        try:
            line = input("can> ").strip()
            if not line:
                continue

            if line == 'exit' or line == 'quit' or line == 'q':
                break

            parts = line.split('=')

            name = parts[0]
            cmd = cmds.get(name)
            if cmd is None:
                print(f'Command {line} is not supported')
                continue

            arg = parts[1] if len(parts) > 1 else None
            cmd.execute(arg)
        except ValueError as exc:
            print(exc)
        except KeyboardInterrupt:
            print('')
        except (EOFError):
            break

#
# Does processing
#
def main():
    print('CAN emulator')

    parser = argparse.ArgumentParser()
    parser.add_argument('--uds-mode', type = str, default = 'user', choices = ['user', 'developer'], help = 'Work mode')
    parser.add_argument('--loglevel', default = 'ERROR', choices = ['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    args = parser.parse_args()

    logging.basicConfig(level = getattr(logging, args.loglevel))
    with can.interface.Bus() as bus:
        eventLoop(Emulator(bus, args))

    print('Exit')

#
# Launches main
#
if __name__ == "__main__":
    main()   