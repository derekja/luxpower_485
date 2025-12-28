#!/usr/bin/env python3
import argparse
import sys
import time
from datetime import datetime

import serial

try:
    from serial.rs485 import RS485Settings
except Exception:
    RS485Settings = None


def ts():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_read_holding_req(slave: int, start: int, qty: int) -> bytes:
    # Modbus RTU: [slave][func=0x03][start hi][start lo][qty hi][qty lo][crc lo][crc hi]
    pdu = bytes([
        slave & 0xFF,
        0x03,
        (start >> 8) & 0xFF,
        start & 0xFF,
        (qty >> 8) & 0xFF,
        qty & 0xFF,
    ])
    crc = crc16_modbus(pdu)
    return pdu + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def read_exact(ser: serial.Serial, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def read_holding_chunk(ser: serial.Serial, slave: int, start: int, qty: int):
    """
    Returns (regs, err)
      regs: list[int] if OK
      err: None if OK, else a tuple describing error
    """
    # Flush any stale bytes that can cause "SHORT"/desync
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    req = build_read_holding_req(slave, start, qty)
    ser.write(req)
    ser.flush()

    # Read response header
    head = read_exact(ser, 2)
    if len(head) < 2:
        return None, ("TIMEOUT_OR_SHORT", f"need 2 got {len(head)}", head.hex(" "))

    r_slave = head[0]
    r_func = head[1]

    if r_slave != (slave & 0xFF):
        # Try to give some context
        more = ser.read(64)
        return None, ("DESYNC", f"unexpected slave {r_slave:02x} func {r_func:02x}", (head + more).hex(" "))

    # Exception response: func | 0x80, then [code], then CRC
    if r_func & 0x80:
        rest = read_exact(ser, 3)  # code + crc(2)
        if len(rest) < 3:
            return None, ("EXC_SHORT", (head + rest).hex(" "), None)
        code = rest[0]
        frame = head + rest
        crc_rx = rest[1] | (rest[2] << 8)
        crc_calc = crc16_modbus(frame[:-2])
        if crc_rx != crc_calc:
            return None, ("EXC_BADCRC", f"code=0x{code:02x}", frame.hex(" "))
        return None, ("EXCEPTION", f"func=0x{r_func:02x} code=0x{code:02x} crc_ok=True", None)

    # Normal response: [byte_count], then data, then CRC
    bcnt_b = read_exact(ser, 1)
    if len(bcnt_b) < 1:
        return None, ("SHORT", "missing bytecount", head.hex(" "))
    bcnt = bcnt_b[0]
    rest = read_exact(ser, bcnt + 2)  # data + crc
    frame = head + bcnt_b + rest
    if len(rest) < bcnt + 2:
        return None, ("SHORT", frame.hex(" "), None)

    crc_rx = rest[-2] | (rest[-1] << 8)
    crc_calc = crc16_modbus(frame[:-2])
    if crc_rx != crc_calc:
        return None, ("BADCRC", f"crc_rx=0x{crc_rx:04x} crc_calc=0x{crc_calc:04x}", frame.hex(" "))

    if bcnt != qty * 2:
        return None, ("BADCNT", f"bytecount={bcnt} expected={qty*2}", frame.hex(" "))

    data = rest[:-2]
    regs = []
    for i in range(0, len(data), 2):
        regs.append((data[i] << 8) | data[i + 1])
    return regs, None


def dump_range(ser, slave, start, count, chunk, stop_on_illegal, quiet_errors):
    end = start + count
    addr = start

    while addr < end:
        qty = min(chunk, end - addr)

        regs, err = read_holding_chunk(ser, slave, addr, qty)
        if err is None:
            for i, v in enumerate(regs):
                r = addr + i
                print(f"r={r} (0x{r:04X}) = {v}")
            addr += qty
            continue

        etype = err[0]

        # On any failure, bisect qty down until we either succeed or get to qty==1
        if qty > 1:
            new_qty = max(1, qty // 2)
            if not quiet_errors:
                print(f"{ts()} addr={addr} qty={qty} ERROR {err} -> retry qty={new_qty}", file=sys.stderr)
            chunk = max(1, min(chunk, qty))  # keep global chunk sane
            # retry same addr with smaller qty (do not advance addr)
            # but do not permanently force chunk down forever; just retry with smaller qty here:
            qty = new_qty
            # local retry loop: just set chunk temporarily by recursion-ish approach
            # easiest: set chunk = min(chunk, new_qty) for this pass
            # we’ll just set a local variable by temporarily calling ourselves? no—just set chunk to itself and rely on min()
            # Instead, do a one-off read immediately:
            regs2, err2 = read_holding_chunk(ser, slave, addr, new_qty)
            if err2 is None:
                for i, v in enumerate(regs2):
                    r = addr + i
                    print(f"r={r} (0x{r:04X}) = {v}")
                addr += new_qty
            else:
                # If still failing, we’ll continue the while loop, but with smaller chunk for this region
                # Force chunk down for subsequent attempts in this failing zone
                chunk = max(1, new_qty)
            continue

        # qty == 1 and still failing => true illegal (or persistent comms issue at that address)
        if not quiet_errors:
            print(f"{ts()} addr={addr} qty=1 ERROR {err}", file=sys.stderr)

        if stop_on_illegal:
            print(f"{ts()} stopping at addr={addr} due to --stop-on-illegal", file=sys.stderr)
            return

        # Skip one register and keep going
        addr += 1


def main():
    ap = argparse.ArgumentParser(description="Dump Modbus RTU holding registers with adaptive chunking.")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=19200)
    ap.add_argument("--parity", choices=["N", "E", "O"], default="N")
    ap.add_argument("--slave", type=int, required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=1200)
    ap.add_argument("--chunk", type=int, default=60)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--stop-on-illegal", action="store_true", help="Stop when a single address is illegal.")
    ap.add_argument("--quiet-errors", action="store_true", help="Suppress error diagnostics to stderr.")
    args = ap.parse_args()

    parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}

    ser = serial.Serial(
        port=args.port,
        baudrate=args.baud,
        parity=parity_map[args.parity],
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=args.timeout,
    )

    # Enable RS-485 RTS direction control (matches what you already grepped for)
    if RS485Settings is not None:
        try:
            ser.rs485_mode = RS485Settings(rts_level_for_tx=True, rts_level_for_rx=False)
        except Exception:
            pass

    if not args.quiet_errors:
        print(
            f"{ts()} dumping holding: port={args.port} baud={args.baud} parity={args.parity} "
            f"slave={args.slave} start={args.start} count={args.count} chunk={args.chunk} timeout={args.timeout}",
            file=sys.stderr,
        )

    try:
        dump_range(
            ser=ser,
            slave=args.slave,
            start=args.start,
            count=args.count,
            chunk=args.chunk,
            stop_on_illegal=args.stop_on_illegal,
            quiet_errors=args.quiet_errors,
        )
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

