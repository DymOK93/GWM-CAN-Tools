#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import can
import datetime
import time

#
#
#
def parseTimeStamp(ts: str) -> dict:
    ts_value = float(ts.strip("()"))
    return datetime.datetime.fromtimestamp(ts_value)

#
#
#
def parseMessage(msg: str) -> dict:
    id, data = msg.split('#')
    return {
        'id': int(id, 16),
        'data': bytes.fromhex(data)
    }

#
#
#
def readTrace(path: str) -> list:
    with open(path, 'r') as file:
        trace = []
        for line in file:
            ts, _, msg = line.split()
            trace.append({ 
                'timestamp': parseTimeStamp(ts),
                'message': parseMessage(msg)
            })
        return trace
    
#
#
#
def getDuration(trace: list) -> datetime.timedelta:
    if len(trace) == 0:
        return 0
    
    first_ts = trace[0]['timestamp']
    last_ts = trace[-1]['timestamp']
    return last_ts - first_ts

#
#
#
class ReplayInfo:
    def __init__(self, trace, args):
        step = args.step
        if step < 0:
            raise ValueError(f'Invalid step timeout: {step}')
        
        time = args.time
        if time < 0:
            raise ValueError(f'Invalid time: {time}')
        
        first, last = map(int, args.range.split(','))
        if first < 0:
            raise ValueError(f'Invalid first line: {first}')
        
        if last != -1 and first > last:
            raise ValueError(f'Invalid last line: {last}')
        
        max_line = len(trace)
        if last == -1 or last > max_line:
            last = max_line
        
        self.trace = trace
        self.step = step
        self.time = time
        self.range = range(first, last)
    
#
#
#
def replay(info: ReplayInfo) -> None:
    with can.interface.Bus() as bus:
        start_time = time.time()
        prev_ts = 0
        for idx in info.range:
            line = info.trace[idx]
            msg = line['message']
            id = msg['id']
            packet = can.Message(
                arbitration_id = id,
                data = msg['data'],
                is_extended_id = False
            )
            bus.send(packet)

            if info.time > 0 and time.time() - start_time > info.time:
                print(f'Time limit exceeded: {info.time} s')
                break

            if info.step != 0:
                print(f'Sent command #{idx}: ID {hex(id).upper()}')
                time.sleep(info.step)
            else:
                ts = line['timestamp']
                if prev_ts != 0:
                    time.sleep((ts - prev_ts).total_seconds())
                prev_ts = ts

#
# Does processing
#
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('trace', type = str, help = 'CAN trace in linux-candump format')
    parser.add_argument('--time', '-t', type = float, default = 0, help = 'replay time in seconds')
    parser.add_argument('--step', '-s', type = float, default = 0, help = 'step-by-step execution with pause')
    parser.add_argument('--range', '-r', type = str, default = '0,-1', help = 'first,last trace lines')
    args = parser.parse_args()

    trace = readTrace(args.trace)
    dur = getDuration(trace).total_seconds()
    print(f'Replay trace: {len(trace)} lines, duration {dur} s')

    if len(trace) > 0:
        print('Start')
        replay(ReplayInfo(trace, args))
        print('Finish')

#
# Launches main
#
if __name__ == "__main__":
    main()   