#!/usr/bin/env python3
import argparse
import datetime as dt
import serial
from serial.rs485 import RS485Settings
import time

def ts():
    return dt.datetime.now().isoformat(timespec="seconds")

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF

def build_req(slave: int, func: int, start: int, qty: int) -> bytes:
    p = bytes([slave & 0xFF, func & 0xFF, (start >> 8) & 0xFF, start & 0xFF, (qty >> 8) & 0xFF, qty & 0xFF])
    c = crc16_modbus(p)
    return p + bytes([c & 0xFF, (c >> 8) & 0xFF])

def read_exact(ser: serial.Serial, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=19200)
    ap.add_argument("--parity", choices=["N", "E", "O"], default="N")
    ap.add_argument("--stopbits", type=int, choices=[1, 2], default=1)
    ap.add_argument("--slave", type=lambda x: int(x, 0), default=1)
    ap.add_argument("--func", type=lambda x: int(x, 0), default=4, help="3=holding, 4=input")
    ap.add_argument("--start", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=0.5)
    ap.add_argument("--retries", type=int, default=1)
    args = ap.parse_args()

    parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}

    ser = serial.Serial(
        args.port, args.baud,
        parity=parity_map[args.parity],
        stopbits=serial.STOPBITS_ONE if args.stopbits == 1 else serial.STOPBITS_TWO,
        bytesize=serial.EIGHTBITS,
        timeout=args.timeout,
    )

    # IMPORTANT: match your working poller
    ser.rs485_mode = RS485Settings(
        rts_level_for_tx=True,
        rts_level_for_rx=False,
        delay_before_tx=0.0,
        delay_before_rx=0.0,
        loopback=False,
    )

    req = build_req(args.slave, args.func, args.start, args.count)

    for attempt in range(args.retries + 1):
        ser.reset_input_buffer()
        ser.write(req)

        # Response formats:
        # Normal:  slave func bytecount data... crc_lo crc_hi
        # Except:  slave (func|0x80) exc_code crc_lo crc_hi
        head = read_exact(ser, 3)
        if len(head) < 3:
            if attempt < args.retries:
                continue
            print(f"{ts()} NO RESPONSE (header)")
            return

        slave, func, b2 = head[0], head[1], head[2]

        if func & 0x80:
            tail = read_exact(ser, 2)
            if len(tail) < 2:
                print(f"{ts()} SHORT EXCEPTION: {(head+tail).hex(' ')}")
                return
            resp = head + tail
            body = resp[:-2]
            crc_rx = resp[-2] | (resp[-1] << 8)
            crc_ok = (crc16_modbus(body) == crc_rx)
            print(f"{ts()} EXCEPTION slave={slave} func=0x{func:02X} code=0x{b2:02X} crc_ok={crc_ok}")
            return

        bytecount = b2
        tail = read_exact(ser, bytecount + 2)
        if len(tail) < bytecount + 2:
            if attempt < args.retries:
                continue
            print(f"{ts()} SHORT RESPONSE: {(head+tail).hex(' ')}")
            return

        resp = head + tail
        body = resp[:-2]
        crc_rx = resp[-2] | (resp[-1] << 8)
        crc_ok = (crc16_modbus(body) == crc_rx)

        data = resp[3:3 + bytecount]
        regs = [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]

        print(f"{ts()} OK crc_ok={crc_ok} slave={slave} func=0x{func:02X} start={args.start} count={args.count}")
        for i, v in enumerate(regs):
            addr = args.start + i
            print(f"  {addr:5d} (0x{addr:04X}) = {v}")
        return

    print(f"{ts()} NO RESPONSE (after retries)")

if __name__ == "__main__":
    main()

