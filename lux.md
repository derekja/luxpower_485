# GSL-H-12KLV-US / LuxPower Modbus Register Documentation

This document covers the RS-485 Modbus register mappings for the GSL-H-12KLV-US inverter (a rebadged LuxPower 12KLV).

## Protocol Documentation Sources

- **Primary**: https://github.com/OwlBawl/Luxpower-Modbus-RTU
  - PDF: https://github.com/OwlBawl/Luxpower-Modbus-RTU/raw/refs/heads/main/ModBus_protocol_updated_on_2025.06.14.pdf
- **EG4 (another LuxPower rebrand)**: https://github.com/poldim/EG4-Inverter-Modbus
- **ESPHome implementation**: https://github.com/jostd/ESPHome-Luxpower-8k-10k

## Connection Settings

- Port: `/dev/ttySC1`
- Baud: 19200
- Parity: N
- Slave ID: 1 (slave 0 also responds with same data, slave 2 does not respond)

## Input Registers (Function Code 0x04)

### Confirmed Registers

| Register | Description | Unit | Notes |
|----------|-------------|------|-------|
| 1 | PV1 Voltage (Vpv1) | 0.1V | e.g., 3500 = 350.0V |
| 2 | PV2 Voltage (Vpv2) | 0.1V | |
| 3 | PV3 Voltage (Vpv3) | 0.1V | |
| 4 | Battery Voltage (Vbat) | 0.1V | e.g., 523 = 52.3V |
| 5 | **SOC / SOH combined** | % | See decoding trick below |
| 6 | Internal Fault/Status code | - | Changes when PV activates |
| 7 | PV1 Power (Ppv1) | W | |
| 8 | PV2 Power (Ppv2) | W | |
| 9 | Total PV Power | W | PV1 + PV2 + PV3 |
| 10 | Battery Charge Power (Pcharge) | W | Power into battery |
| 11 | Battery Discharge Power (Pdischarge) | W | Power out of battery |
| 64 | Internal Temperature (T_inner) | °C | Inverter internal |
| 65 | Radiator 1 Temperature (T_rad1) | °C | |
| 66 | Radiator 2 Temperature (T_rad2) | °C | |
| 67 | Battery Temperature (T_bat) | °C | **Not working** - always reads 4, likely unused |
| 101 | Max Cell Voltage | 0.001V | From BMS, e.g., 3350 = 3.350V |
| 102 | Min Cell Voltage | 0.001V | From BMS |
| 103 | Max Cell Temperature | 0.1°C | From BMS, e.g., 140 = 14.0°C |
| 104 | Min Cell Temperature | 0.1°C | From BMS, e.g., 104 = 10.4°C |

### SOC/SOH Decoding Trick

**Register 5 contains both SOC and SOH packed into a single 16-bit value:**

- **Low byte (bits 0-7)**: SOC (State of Charge) as percentage
- **High byte (bits 8-15)**: SOH (State of Health) as percentage

```python
def decode_soc_soh(register_5_value):
    soc = register_5_value & 0xFF        # or: register_5_value % 256
    soh = register_5_value >> 8          # or: register_5_value // 256
    return soc, soh

# Example: register 5 = 24105
# SOC = 24105 & 0xFF = 41%
# SOH = 24105 >> 8 = 94%
```

## Holding Registers (Function Code 0x03)

Holding registers are primarily **configuration/settings**, not live data. Notable values:

| Register | Description | Notes |
|----------|-------------|-------|
| 19 | Low SOC threshold? | Shows 44 (likely a setting) |
| 54 | Low SOC threshold? | Shows 44 (likely a setting) |
| 188 | Low SOC threshold? | Shows 44 (likely a setting) |

These values remained constant across all readings, confirming they are configuration parameters.

## Additional Register Notes

### Registers 6, 7, 8, 9 - Fault Code and PV Power (Confirmed)

| Register | Description | Unit |
|----------|-------------|------|
| 6 | Internal Fault/Status code | - |
| 7 | Ppv1 (PV string 1 power) | W |
| 8 | Ppv2 (PV string 2 power) | W |
| 9 | Total PV power (PV1+PV2+PV3) | W |

**Observed behavior from overnight data:**
- Before sunrise: reg_6 = 14592 (0x3900), reg_7/8 = 0
- At sunrise (~07:51): reg_6 changed to 15104 (0x3B00), PV power appeared
- By 10:01: PV1=312W, PV2=336W, total ~648W

The fault code change (14592 → 15104) likely indicates inverter mode change when PV becomes active.

### Register 108

Shows values in the 195-245 range, varying over time. Purpose unknown.

## Data Analysis

### Register 5 (SOC/SOH) Across Readings

| Timestamp | Expected SOC | r=5 Raw | Decoded SOC | Decoded SOH |
|-----------|--------------|---------|-------------|-------------|
| 22:00:57 | 48% | 24111 | 47% | 94% |
| 22:32:42 | 44% | 24108 | 44% | 94% |
| 22:48:21 | 43% | 24107 | 43% | 94% |
| 23:04:08 | 41% | 24105 | 41% | 94% |

The 1% discrepancy at 48% is likely timing between app observation and register read.

### Battery Discharge Power (Register 11) Over Time

| Timestamp | SOC | Discharge Power |
|-----------|-----|-----------------|
| 22:00:57 | 48% | 963 W |
| 22:32:42 | 44% | 1491 W |
| 22:48:21 | 43% | 1250 W |
| 23:04:08 | 41% | 946 W |

### Temperature Readings at 41% SOC

| Sensor | Register | Value | Interpretation |
|--------|----------|-------|----------------|
| Internal | 64 | 22 | 22°C |
| Radiator 1 | 65 | 31 | 31°C |
| Radiator 2 | 66 | 29 | 29°C |
| Battery (external) | 67 | 4 | 4°C |
| Max Cell (BMS) | 103 | 140 | 14.0°C |
| Min Cell (BMS) | 104 | 104 | 10.4°C |

Outside temperature was approximately -1°C. Battery has active heating maintaining cells at 10-14°C.

### Battery Voltage Observations

Register 4 showed ~522-523 (52.2-52.3V) across readings, consistent with a 48V nominal battery at 41-48% SOC.

## WiFi Adapter Note

The LuxPower app uses a WiFi adapter that sends data to LuxPower's cloud servers in China. This is a separate communication path from the local RS-485 Modbus interface documented here. The WiFi adapter protocol has not been reverse-engineered in this project.

## Overnight Data Analysis (Dec 27-28, 2025)

Data collected every 10 minutes from 20:30 to 10:11 (83 readings in `data_dec27b.csv`).

### Full Charge Cycle Observed

| Time | SOC | Vbat | Event |
|------|-----|------|-------|
| 20:30 | 38% | 52.1V | Start of logging, discharging ~1200W |
| 22:10 | 27% | 51.5V | SOC minimum reached |
| 22:20 | 29% | 53.4V | Charging began (grid or scheduled) |
| 02:00 | 99% | 56.3V | Peak SOC reached |
| 02:10 | 99% | 53.3V | Charging stopped, voltage dropped |
| 07:51 | 75% | 53.1V | PV started (reg_6/7/8 changed) |
| 10:11 | 65% | 52.5V | End of logging |

### Cell Temperature Correlation

The BMS cell temperatures tracked the charge/discharge cycle:
- **Cold start:** 10.4-14.2°C (outside temp ~ -1°C, heater active)
- **During charging:** Warmed to 19-23°C (battery self-heating from charge current)
- **After charge complete:** Slowly cooled back to 14-19°C

### Observations

1. **T_bat (register 67)** stayed constant at 4°C across all readings - confirmed non-functional
2. **Inverter internal temp (reg 64)** stable at 20-25°C
3. **Radiator temps (reg 65-66)** varied 27-34°C, tracking inverter load
4. **Cell voltage spread:** Max-min cell voltage difference was typically 10-15mV, indicating good cell balance

## Future Work

- Graph power (charge/discharge) and SOC over time
- Map additional input registers (PV power, grid power, etc.)
- Investigate registers 6, 7, 8 for PV data
- Explore writable holding registers for automation
