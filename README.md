# luxpower_485
a repo to hold the decoding of the GSL energy rebadge of the luxpower GSL-H-12KLV-US


./modbus_dump_input.py   --port /dev/ttySC1   --baud 19200   --parity N   --slave 1   --start 0   --count 200   --chunk 40   --timeout 2.0   --stop-on-illegal   | tee scan_input_0_200_soc44.txt
./modbus_read_one.py --port /dev/ttySC1 --baud 19200 --parity N --slave 1 --func 4 --start 0 --count 10
./modbus_dump_holding.py --port /dev/ttySC1 --baud 19200 --parity N --slave 1   --start 0 --count 500 --chunk 60 --timeout 2.0 --stop-on-illegal   | tee "hold_0_499_soc_${SOC}_$(date +%F_%H%M%S).txt"
