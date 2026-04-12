"""
serial_to_udp.py — Robust Serial-to-UDP bridge for ESP32 → server.py
=====================================================================
Reads ECG,PPG lines from the ESP32 serial port and forwards each
valid sample as a JSON UDP packet to server.py.

Uses the same proven line-buffering strategy as Test.py:
  1. Read all available bytes from serial
  2. Accumulate into a persistent byte buffer
  3. Split on newlines → complete lines + leftover fragment
  4. Parse each complete "ECG,PPG" line
  5. Send each as an individual UDP packet

Serial format from ESP32:
  <ecg_int>,<ppg_int>\n    (e.g. "13710,1452\n")
"""

import serial
import socket
import json
import time
import argparse
import sys

# Configuration
BAUD_RATE = 115200
UDP_IP = "127.0.0.1"
UDP_PORT = 5005


def main():
    parser = argparse.ArgumentParser(
        description="Bridge Serial data from ESP32 to UDP for server.py"
    )
    parser.add_argument("--port", default="COM3", help="Serial port (default: COM3)")
    parser.add_argument("--verbose", action="store_true", help="Print every parsed sample")
    args = parser.parse_args()

    # 1. Setup Serial
    print(f"Opening Serial port {args.port} @ {BAUD_RATE} baud...")
    try:
        # timeout=0 → non-blocking (same as Test.py)
        ser = serial.Serial(args.port, BAUD_RATE, timeout=0)
    except Exception as e:
        print(f"Failed to open {args.port}: {e}")
        return

    # 2. Setup UDP Socket
    print(f"Opening UDP socket to {UDP_IP}:{UDP_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("Bridging data! Press Ctrl+C to stop.\n")

    start_time = time.time()
    raw_buffer = b""         # persistent byte buffer for incomplete lines
    total_sent = 0
    total_errors = 0

    try:
        while True:
            # ── Step 1: Read all available bytes ──────────────────
            waiting = ser.in_waiting
            if waiting > 0:
                raw_buffer += ser.read(waiting)
            else:
                # Nothing available — sleep briefly to avoid busy-spinning
                time.sleep(0.001)
                continue

            # ── Step 2: Split on newlines ─────────────────────────
            # Only process if we have at least one complete line
            if b'\n' not in raw_buffer:
                continue

            lines = raw_buffer.split(b'\n')

            # Last element is either empty (if buffer ended with \n)
            # or an incomplete fragment — keep it for next iteration
            raw_buffer = lines.pop()

            # ── Step 3: Parse and send each complete line ─────────
            for line in lines:
                try:
                    decoded = line.decode('utf-8', errors='ignore').strip()

                    # Skip empty lines or error messages from ESP32
                    if not decoded or ',' not in decoded:
                        continue

                    parts = decoded.split(',')
                    if len(parts) != 2:
                        continue

                    ecg_val = float(parts[0])
                    ppg_val = float(parts[1])

                    payload = {
                        "ecg": ecg_val,
                        "ppg": ppg_val,
                        "timestamp": (time.time() - start_time) * 1000.0,
                    }

                    sock.sendto(
                        json.dumps(payload).encode('utf-8'),
                        (UDP_IP, UDP_PORT),
                    )
                    total_sent += 1

                    if args.verbose:
                        print(f"[{total_sent}] ECG={ecg_val:.0f} PPG={ppg_val:.0f}")

                except ValueError:
                    total_errors += 1
                    if args.verbose:
                        print(f"[SKIP] Could not parse: {decoded!r}")

            # ── Step 4: Periodic status ───────────────────────────
            if total_sent > 0 and total_sent % 1000 == 0:
                elapsed = time.time() - start_time
                rate = total_sent / elapsed if elapsed > 0 else 0
                print(f"[STATS] Sent {total_sent} packets | "
                      f"{rate:.1f} samples/s | "
                      f"{total_errors} parse errors | "
                      f"buffer={len(raw_buffer)} bytes")

            # Safety: if the buffer grows too large, something is wrong
            # (e.g. no newlines arriving). Trim to prevent memory issues.
            if len(raw_buffer) > 4096:
                print(f"[WARN] Buffer overflow ({len(raw_buffer)} bytes), trimming")
                # Keep only the last 256 bytes (likely contains partial line)
                raw_buffer = raw_buffer[-256:]

    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\nStopping bridge.")
        print(f"  Total sent:   {total_sent}")
        print(f"  Total errors: {total_errors}")
        print(f"  Duration:     {elapsed:.1f}s")
        if elapsed > 0:
            print(f"  Avg rate:     {total_sent/elapsed:.1f} samples/s")
    finally:
        ser.close()
        sock.close()


if __name__ == "__main__":
    main()
