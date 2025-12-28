#!/usr/bin/env python3
"""
modbus_dump_input.py

Dump Modbus *Input Registers* (function 0x04) over RS-485 with
chunking, retries, CRC validation, and optional stop-on-illegal.

Designed to match the behavior and robustness of modbus_dump_holding.py.
"""

import argparse
import datetime as dt
import time
import serial
from serial.rs485 import RS485Settings


def ts():
    return dt.datetime.now().isoformat(timespec="seconds")


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def build_req(slave: int, start: int, qty: int) -> bytes:
    # Function 0x04 = Read Input Registers
    p = bytes([
        slave,
        0x04,
        (start >> 8) & 0xFF,
        start & 0xFF,
        (qty >> 8) & 0xFF,
        qty & 0xFF,
    ])
    c = crc16_modbus(p)
    return p + bytes([c & 0xFF, (c >> 8) & 0xFF])


def read_exact(ser, n: int) -> bytes:
    buf = b""
    t0 = time.time()
    while len(buf) < n and (time.time() - t0) < (ser.timeout or 1.0) + 0.2:
        chunk = ser.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def read_block(ser, slave, start, qty):
    req = build_req(slave, start, qty)
    ser.reset_input_buffer()
    ser.write(req)

    # Header: slave, func, bytecount
    head = read_exact(ser, 3)
    if len(head) < 3:
        return ("TIMEOUT_OR_SHORT", f"need 3 got {len(head)}", None)

    addr, func, bc = head

    # Exception response: func | 0x80
    if func & 0x80:
        rest = read_exact(ser, 2)
        if len(rest) != 2:
            return ("EXCEPTION", "short exception frame", None)
        crc_rx = rest[0] | (rest[1] << 8)
        ok = crc16_modbus(head) == crc_rx
        return ("EXCEPTION", f"func=0x{func:02X} code=0x{bc:02X} crc_ok={ok}", None)

    # Normal response
    rest = read_exact(ser, bc + 2)
    if len(rest) != bc + 2:
        return ("TIMEOUT_OR_SHORT", f"need {bc+2} got {len(rest)}", None)

    frame = head + rest
    crc_rx = frame[-2] | (frame[-1] << 8)
    crc_ok = crc16_modbus(frame[:-2]) == crc_rx
    if not crc_ok:
        return ("CRC", "crc mismatch", None)

    data = frame[3:-2]
    regs = [(data[i] << 8) | data[i+1] for i in range(0, len(data), 2)]
    return ("OK", None, regs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=19200)
    ap.add_argument("--parity", choices=["N", "E", "O"], default="N")
    ap.add_argument("--slave", type=lambda x: int(x, 0), default=1)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--chunk", type=int, default=40)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--stop-on-illegal", action="store_true")
    args = ap.parse_args()

    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }

    ser = serial.Serial(
        args.port,
        args.baud,
        parity=parity_map[args.parity],
        bytesize=serial.EIGHTBITS,
        stopbits=serial.STOPBITS_ONE,
        timeout=args.timeout,
    )

    # RS-485 direction control (CRITICAL)
    ser.rs485_mode = RS485Settings(
        rts_level_for_tx=True,
        rts_level_for_rx=False,
        delay_before_tx=0.0,
        delay_before_rx=0.0,
        loopback=False,
    )

    print(
        f"{ts()} dumping input: port={args.port} baud={args.baud} "
        f"parity={args.parity} slave={args.slave} "
        f"start={args.start} count={args.count} chunk={args.chunk}"
    )

    addr = args.start
    remaining = args.count

    while remaining > 0:
        qty = min(args.chunk, remaining)
        status, msg, regs = read_block(ser, args.slave, addr, qty)

        if status == "OK":
            for i, v in enumerate(regs):
                r = addr + i
                print(f"r={r} (0x{r:04X}) = {v}")
            addr += qty
            remaining -= qty
            continue

        # Error handling
        print(f"{ts()} addr={addr} qty={qty} ERROR ({status}, {msg})", flush=True)

        if qty > 1:
            new_qty = max(1, qty // 2)
            print(f"{ts()} -> retry qty={new_qty}")
            args.chunk = new_qty
            continue

        # qty == 1 failed
        if args.stop_on_illegal:
            print(f"{ts()} stopping at addr={addr} due to --stop-on-illegal")
            break

        addr += 1
        remaining -= 1

    ser.close()


if __name__ == "__main__":
    main()

