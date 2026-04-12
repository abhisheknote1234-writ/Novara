# MaternalGuard — PyQt5 Dashboard  (`dashboard_main.py`)

## What this file does
Connects to your existing **server.py** via Socket.IO and renders all
metrics produced by **PhysioMonitor** in a real-time desktop window.

### Data flow (nothing changed upstream)
```
ESP32
  └─► serial_to_udp.py   (reads COM port, sends UDP)
        └─► server.py     (Flask-SocketIO, runs SignalProcessor / PhysioMonitor)
              └─► "update" Socket.IO event
                    └─► dashboard_main.py   ← THIS FILE
```

---

## Install
```bash
pip install PyQt5 pyqtgraph "python-socketio[client]" numpy scipy
```

---

## Run

**Step 1 — start your backend** (with real hardware or the built-in simulator):
```bash
python server.py --simulate        # simulator (no ESP32 needed)
# or
python server.py                   # real hardware via serial_to_udp.py
```

**Step 2 — launch the dashboard**:
```bash
python dashboard_main.py
# optional: point at a remote server
python dashboard_main.py --server http://192.168.1.10:8080
```

---

## Payload fields consumed (from server.py)

| Field            | Source in server.py               | Used for                    |
|------------------|-----------------------------------|-----------------------------|
| `ecg_wave`       | `ecg_clean[-100:]`                | ECG waveform plot           |
| `ppg_wave`       | `ppg_clean[-100:]`                | PPG waveform plot           |
| `r_peaks`        | Pan-Tompkins peak indices         | R-peak markers on ECG       |
| `hrv.hr_bpm`     | `60000 / mean_rr`                 | Heart Rate tile             |
| `hrv.rmssd`      | `sqrt(mean(diff(rr)^2))`          | RMSSD tile                  |
| `hrv.sdnn`       | `std(rr)`                         | SDNN tile                   |
| `hrv.mean_rr`    | `mean(rr_buffer)`                 | Mean RR tile                |
| `stress`         | EMA-smoothed weighted score       | Stress gauge + progress bar |
| `state`          | `_autonomic_state()`              | State badge + colour        |
| `fetal_score`    | `_fetal_score()`                  | Fetal wellbeing panel       |
| `ptt_ms`         | median of `ptt_buffer`            | PTT panel + tile            |
| `breath_rate`    | `_breathing_rate()`               | Breathing tile + badge      |
| `sqi`            | `_compute_sqi()`                  | SQI bar                     |
| `timeline`       | `self.timeline[-20:]`             | Timeline list               |
| `alert`          | sustained stress > 70 for 2 min   | Alert banner                |
| `baseline_set`   | calibration flag                  | Baseline label              |
| `device_connected` | UDP timeout detection           | Connection status           |

---

## Socket.IO events

| Event               | Direction        | Handler                        |
|---------------------|------------------|--------------------------------|
| `update`            | server → client  | `_on_update()` — main data     |
| `status`            | server → client  | `_on_status()` — on connect    |
| `calibration_done`  | server → client  | `_on_calib_done()` — baseline  |
| `calibration_started` | server → client | toolbar label update          |
| `start_calibration` | client → server  | "Calibrate" button             |

---

## UI structure

```
┌─ Toolbar ──────────────────────────────────────────────────────────┐
│  ♡ MaternalGuard  [status]  [baseline]  [timer]  [Calibrate] [Clear]│
├─ Left column (57%) ────────────────┬─ Right column (43%) ──────────┤
│  ECG waveform (pyqtgraph)          │  Stress gauge (QPainter arc)  │
│  SQI bar                           │  State badge                  │
│  PPG waveform (pyqtgraph)          │  Fetal + PTT panels           │
│  6 × MetricTile widgets            │  Alert banner                 │
│    HR · RMSSD · SDNN               │  Timeline list                │
│    Mean RR · PTT · Breathing       │                               │
└────────────────────────────────────┴───────────────────────────────┘
│  Status bar                                                         │
└─────────────────────────────────────────────────────────────────────┘
```
