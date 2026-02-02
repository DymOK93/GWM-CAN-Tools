#!/usr/bin/env python
# -*- coding: utf-8 -*-
import can
import isotp
from udsoncan.connections import PythonIsoTpConnection
from abc import ABC, abstractmethod
import argparse
import logging
import time
import uds

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
# @brief Ignition peridic task
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
        if arg == 'on':
            self.task.start()
        elif arg == 'off':
            self.task.stop()
        else:
            raise ValueError(f'Unknown argument {arg} for {self.task.name}')
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
# @brief HUT reboot command 
# Reboots the HUT to the specified boot target via the UDS interface
# @warning The ignition should be on
# @warning Doesn't work in Android recovery and ELK
#
class HutRebootCommand(CommandBase):
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
    def __init__(self, bus: can.interface.Bus, uds_mode: uds.Mode):
        super().__init__()
        self.bus = bus
        self.uds_mode = uds_mode

    #
    #
    #
    def execute(self, target: str):
        print(f'Reboot HUT to {target}')
        with Notifier(self.bus) as notifier:
            make_conn = lambda txid, rxid: HutRebootCommand._createConnection(self.bus, notifier, txid, rxid)
            with uds.HarmanHut(self.uds_mode, make_conn) as hut:
                hut.reboot(target)

#
# Event loop
# @param[in] bus CAN bus instance
#
def eventLoop(emu: Emulator) -> None:
    cmds = {
        'ign': IgnitionCommand(emu.bus),
        'hut-stb': HutStandbyCommand(emu.bus),
        'hut-reboot': HutRebootCommand(emu.bus, emu.uds_mode)
    }

    tasks = {}
    while True:
        try:
            line = input("sc-can> ").strip()
            if not line:
                continue

            if line == 'exit' or line == 'quit':
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
        except (EOFError, KeyboardInterrupt):
            break

#
# Does processing
#
def main():
    print('SC-CAN emulator')

    parser = argparse.ArgumentParser()
    parser.add_argument('--uds-mode', type = str, default = 'user', help = 'Work mode (user, developer)')
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