#!/usr/bin/env python
# -*- coding: utf-8 -*-
import can
import time

#
# @brief Turn on the ignition
# @param[in] bus CAN bus instance
# @warning Some commands require the ignition to be turned on first
# @remark Mesages from the real trace contained data = bytes.fromhex('0110010401000000')
# but the devices do'not read the message contents
#
def ignitionOn(bus: can.interface.Bus) -> can.CyclicSendTaskABC:
    print('Turn ignition ON')
    msg = can.Message(
            arbitration_id = 0x501,
            data = bytes(8),
            is_extended_id = False)
    for i in range(0, 4):
        bus.send(msg)
        time.sleep(0.02)
    
    task = bus.send_periodic(msg, 0.5)
    assert isinstance(task, can.CyclicSendTaskABC)
    return task

#
# @brief Turn off the ignition
# @param[in] task Periodic ignition task
#
def ignitionOff(_: can.interface.Bus, task: can.CyclicSendTaskABC) -> None:
    print('Turn ignition OFF')
    task.stop()

#
# @brief Turn off the HUT display
# @param[in] bus CAN bus instance
# @warning The ignition should be on
#
def hutDisplayOn(bus: can.interface.Bus) -> None:
    print('Turn HUT display ON')
    bus.send(can.Message(
            arbitration_id = 0x295,
            data = bytes.fromhex('B1A000C000000006'),
            is_extended_id = False))
    
#
# @brief Turn off the HUT display
# @param[in] bus CAN bus instance
#
def hutDisplayOff(bus: can.interface.Bus, _: None) -> None:
    print('Turn HUT display OFF')
    bus.send(can.Message(
            arbitration_id = 0x295,
            data = bytes.fromhex('B120000000000007'),
            is_extended_id = False))
    
#
# Event loop
# @param[in] bus CAN bus instance
#
def eventLoop(bus: can.interface.Bus) -> None:
    cmds = {
        'ign=on': ignitionOn,
        'ign=off': ignitionOff,
        'hut-disp=on': hutDisplayOn,
        'hut-disp=off': hutDisplayOff
    }

    tasks = {}
    while True:
        try:
            line = input("sc-can> ").strip()
            if line == 'exit':
                break

            cmd = cmds.get(line)
            if cmd is None:
                print(f'Command {line} is not supported')
                continue

            target, turn = line.split('=')
            if turn == 'on':
                if target in tasks:
                    print(f'Skip: {target} is already ON')
                else:
                    tasks[target] = cmd(bus)
            else:
                if not target in tasks:
                    print(f'Skip: {target} is already OFF')
                else:
                    ctx = tasks.pop(target)
                    cmd(bus, ctx)
                    

        except (EOFError, KeyboardInterrupt):
            break


#
# Does processing
#
def main():
    print('SC-CAN emulator')
    with can.interface.Bus() as bus:
        eventLoop(bus)
    print('Exit')


#
# Launches main
#
if __name__ == "__main__":
    main()   