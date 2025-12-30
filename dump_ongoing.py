#!/usr/bin/env python3
"""
dump_ongoing.py

Periodically read key Modbus registers from GSL/LuxPower inverter
and save to CSV for later analysis.

Usage:
    python3 dump_ongoing.py --port /dev/ttySC1
    python3 dump_ongoing.py --port /dev/ttySC1 --interval 900 --output data.csv

Default: reads every 15 minutes (900 seconds), saves to inverter_log.csv
"""

import argparse
import csv
import datetime as dt
import os
import signal
import sys
import time
import serial
from serial.rs485 import RS485Settings


# Registers to read - based on confirmed mappings
REGISTERS_TO_READ = [
    # (start_addr, count, description)
    (1, 11),     # 1-11: PV voltages, Vbat, SOC/SOH, fault, PV power, charge/discharge
    (64, 4),     # 64-67: T_inner, T_rad1, T_rad2, T_bat (T_bat doesn't work)
    (101, 8),    # 101-108: Cell voltages, temps, BMS data
]

# Human-readable names for CSV columns
REGISTER_NAMES = {
    1: 'vpv1_raw',           # PV1 voltage (0.1V)
    2: 'vpv2_raw',           # PV2 voltage (0.1V)
    3: 'vpv3_raw',           # PV3 voltage (0.1V)
    4: 'vbat_raw',           # Battery voltage (0.1V)
    5: 'soc_soh_raw',        # SOC (low byte) + SOH (high byte)
    6: 'fault_code',         # Internal fault/status code
    7: 'ppv1_w',             # PV1 power (W)
    8: 'ppv2_w',             # PV2 power (W)
    9: 'ppv_total_w',        # Total PV power (W)
    10: 'p_charge_w',        # Battery charge power (W)
    11: 'p_discharge_w',     # Battery discharge power (W)
    64: 't_inner_c',         # Inverter internal temp
    65: 't_rad1_c',          # Radiator 1 temp
    66: 't_rad2_c',          # Radiator 2 temp
    67: 't_bat_c',           # Battery temp (not working - always 4)
    101: 'max_cell_volt_raw',  # Max cell voltage (0.001V)
    102: 'min_cell_volt_raw',  # Min cell voltage (0.001V)
    103: 'max_cell_temp_raw',  # Max cell temp (0.1C)
    104: 'min_cell_temp_raw',  # Min cell temp (0.1C)
    105: 'bms_status',
    106: 'cycle_count',
    107: 'bat_volt_sample_raw',
    108: 'reg_108',
}

running = True


def signal_handler(sig, frame):
    global running
    print(f"\n{ts()} Caught signal {sig}, finishing up...")
    running = False


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


def read_exact(ser, n: int, timeout: float) -> bytes:
    buf = b""
    t0 = time.time()
    while len(buf) < n and (time.time() - t0) < timeout + 0.2:
        chunk = ser.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def read_registers(ser, slave: int, start: int, qty: int, timeout: float = 1.0):
    """Read input registers, return dict of {addr: value} or None on error."""
    req = build_req(slave, start, qty)
    ser.reset_input_buffer()
    ser.write(req)

    head = read_exact(ser, 3, timeout)
    if len(head) < 3:
        return None

    addr, func, bc = head

    if func & 0x80:
        # Exception response
        read_exact(ser, 2, timeout)
        return None

    rest = read_exact(ser, bc + 2, timeout)
    if len(rest) != bc + 2:
        return None

    frame = head + rest
    crc_rx = frame[-2] | (frame[-1] << 8)
    if crc16_modbus(frame[:-2]) != crc_rx:
        return None

    data = frame[3:-2]
    result = {}
    for i in range(0, len(data), 2):
        reg_addr = start + i // 2
        value = (data[i] << 8) | data[i + 1]
        result[reg_addr] = value

    return result


def decode_values(raw_data: dict) -> dict:
    """Add decoded/calculated values to the data."""
    decoded = dict(raw_data)

    # Decode SOC and SOH from register 5
    if 5 in raw_data:
        decoded['soc_pct'] = raw_data[5] & 0xFF
        decoded['soh_pct'] = raw_data[5] >> 8

    # Decode battery voltage (0.1V resolution)
    if 4 in raw_data:
        decoded['vbat_v'] = raw_data[4] / 10.0

    # Decode PV voltages (0.1V resolution)
    if 1 in raw_data:
        decoded['vpv1_v'] = raw_data[1] / 10.0
    if 2 in raw_data:
        decoded['vpv2_v'] = raw_data[2] / 10.0
    if 3 in raw_data:
        decoded['vpv3_v'] = raw_data[3] / 10.0

    # Decode cell temps (0.1C resolution)
    if 103 in raw_data:
        decoded['max_cell_temp_c'] = raw_data[103] / 10.0
    if 104 in raw_data:
        decoded['min_cell_temp_c'] = raw_data[104] / 10.0

    # Decode cell voltages (0.001V resolution)
    if 101 in raw_data:
        decoded['max_cell_volt_v'] = raw_data[101] / 1000.0
    if 102 in raw_data:
        decoded['min_cell_volt_v'] = raw_data[102] / 1000.0

    return decoded


def read_all_registers(ser, slave: int) -> dict:
    """Read all configured register blocks."""
    all_data = {}

    for start, count in REGISTERS_TO_READ:
        result = read_registers(ser, slave, start, count)
        if result:
            all_data.update(result)
        time.sleep(0.1)  # Small delay between reads

    return all_data


def get_csv_columns():
    """Return ordered list of CSV column names."""
    columns = ['timestamp', 'timestamp_unix']

    # Raw register values
    for start, count in REGISTERS_TO_READ:
        for addr in range(start, start + count):
            name = REGISTER_NAMES.get(addr, f'reg_{addr}')
            columns.append(name)

    # Decoded values
    columns.extend([
        'soc_pct', 'soh_pct', 'vbat_v',
        'vpv1_v', 'vpv2_v', 'vpv3_v',
        'max_cell_temp_c', 'min_cell_temp_c',
        'max_cell_volt_v', 'min_cell_volt_v'
    ])

    return columns


def main():
    global running

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ap = argparse.ArgumentParser(description="Ongoing Modbus data logger for LuxPower inverter")
    ap.add_argument("--port", default="/dev/ttySC1", help="Serial port")
    ap.add_argument("--baud", type=int, default=19200, help="Baud rate")
    ap.add_argument("--slave", type=int, default=1, help="Modbus slave ID")
    ap.add_argument("--interval", type=int, default=900, help="Seconds between reads (default: 900 = 15 min)")
    ap.add_argument("--output", default="inverter_log.csv", help="Output CSV file")
    ap.add_argument("--timeout", type=float, default=1.0, help="Read timeout in seconds")
    args = ap.parse_args()

    # Check if file exists to determine if we need to write header
    file_exists = os.path.exists(args.output)

    # Open serial port
    ser = serial.Serial(
        args.port,
        args.baud,
        parity=serial.PARITY_NONE,
        bytesize=serial.EIGHTBITS,
        stopbits=serial.STOPBITS_ONE,
        timeout=args.timeout,
    )

    ser.rs485_mode = RS485Settings(
        rts_level_for_tx=True,
        rts_level_for_rx=False,
        delay_before_tx=0.0,
        delay_before_rx=0.0,
        loopback=False,
    )

    columns = get_csv_columns()

    print(f"{ts()} Starting data logger")
    print(f"  Port: {args.port}")
    print(f"  Slave ID: {args.slave}")
    print(f"  Interval: {args.interval} seconds ({args.interval/60:.1f} minutes)")
    print(f"  Output: {args.output}")
    print(f"  Press Ctrl+C to stop")
    print()

    # Write header if file doesn't exist
    if not file_exists:
        with open(args.output, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()

    read_count = 0
    while running:
        now = dt.datetime.now()

        # Read registers
        raw_data = read_all_registers(ser, args.slave)

        if raw_data:
            read_count += 1
            decoded = decode_values(raw_data)

            # Build row with named columns
            row = {
                'timestamp': now.isoformat(timespec="seconds"),
                'timestamp_unix': int(now.timestamp()),
            }

            # Add raw register values with named columns
            for addr, value in raw_data.items():
                name = REGISTER_NAMES.get(addr, f'reg_{addr}')
                row[name] = value

            # Add decoded values
            for key in ['soc_pct', 'soh_pct', 'vbat_v',
                       'vpv1_v', 'vpv2_v', 'vpv3_v',
                       'max_cell_temp_c', 'min_cell_temp_c',
                       'max_cell_volt_v', 'min_cell_volt_v']:
                if key in decoded:
                    row[key] = decoded[key]

            # Open, write, and close CSV for each measurement
            with open(args.output, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=columns, extrasaction='ignore')
                writer.writerow(row)

            # Print summary
            soc = decoded.get('soc_pct', '?')
            bat_power = raw_data.get(11, 0) - raw_data.get(10, 0)  # discharge - charge
            pv_power = raw_data.get(7, 0) + raw_data.get(8, 0)  # PV1 + PV2
            vbat = decoded.get('vbat_v', '?')
            t_cell_max = decoded.get('max_cell_temp_c', '?')
            t_cell_min = decoded.get('min_cell_temp_c', '?')
            print(f"{ts()} #{read_count}: SOC={soc}%, Vbat={vbat}V, Bat={bat_power:+d}W, PV={pv_power}W, Cells={t_cell_min}-{t_cell_max}C")
        else:
            print(f"{ts()} ERROR: Failed to read registers")

        # Wait for next interval
        if running:
            next_read = now + dt.timedelta(seconds=args.interval)
            print(f"  Next read at {next_read.strftime('%H:%M:%S')}")

            # Sleep in small increments so we can respond to signals
            sleep_until = time.time() + args.interval
            while running and time.time() < sleep_until:
                time.sleep(1)

    ser.close()
    print(f"{ts()} Logger stopped. {read_count} readings saved to {args.output}")


if __name__ == "__main__":
    main()
