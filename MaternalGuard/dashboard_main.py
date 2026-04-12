import argparse
import sys
import time
import threading
import math
from threading import Lock
from collections import deque
from typing import Any, Dict, List, Optional

import numpy as np
import serial
import serial.tools.list_ports

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject

import pyqtgraph as pg
import scipy.signal

def detect_r_peaks_fast(ecg_buffer, fs=250):
    diff = np.diff(ecg_buffer)
    squared = diff ** 2

    window_size = int(0.12 * fs)
    kernel = np.ones(window_size) / window_size
    mwi = np.convolve(squared, kernel, mode='same')

    # Kill the edge effects so the dynamic threshold isn't ruined
    mwi[:window_size] = 0
    mwi[-window_size:] = 0

    threshold = np.mean(mwi) + (1.2 * np.std(mwi))
    min_dist = int(0.200 * fs)

    peaks, _ = scipy.signal.find_peaks(mwi, height=threshold, distance=min_dist)

    true_peaks = []
    for p in peaks:
        start = max(0, p - 12)
        end = min(len(ecg_buffer), p + 12)
        if start < end:
            true_peaks.append(start + np.argmax(ecg_buffer[start:end]))

    return true_peaks

try:
    from physio_monitor import PhysioMonitor
except Exception as _imp_err:
    import traceback
    print(f"[WARN] Failed to import PhysioMonitor: {_imp_err}")
    traceback.print_exc()
    PhysioMonitor = None


# ═══════════════════════════════════════════════════════════════════
#  DESIGN TOKENS — Soft Feminine Wellness Theme
# ═══════════════════════════════════════════════════════════════════
P = {
    "bg0"    : "#fff5f7",   # soft blush background
    "bg1"    : "#ffeef2",   # card background
    "bg2"    : "#ffffff",   # white surface
    "bg3"    : "#fbdde5",   # track / muted pink
    "bg4"    : "#f6c8d5",   # deeper pink

    "border" : "#f3c6d1",
    "border2": "#e9a9bc",

    "t0"     : "#4a3a40",   # primary text — warm dark brown
    "t1"     : "#7a5a63",   # secondary text
    "t2"     : "#b08a95",   # muted / label text

    "ecg"    : "#56b88a",   # softer green for ECG waveform
    "ppg"    : "#7ba3d4",   # soft blue for PPG waveform
    "rpeak"  : "#e86080",   # r-peak marker — rose

    "calm"   : "#7ed6a7",   # green — safe / calm
    "mild"   : "#ffd27a",   # warm yellow — mild load
    "high"   : "#ff8a8a",   # soft red — high load

    "recover": "#7ba3d4",   # blue — recovery state
    "poor"   : "#b0a0a5",   # muted — poor signal

    "accent" : "#f48fb1",   # main pink accent
    "violet" : "#cba6f7",   # lavender

    "rec_low": "#c8a2a8",   # muted recovery
    "rec_mid": "#89b4fa",   # soft blue recovery
    "rec_hi" : "#7ed6a7",   # green recovery

    "nav_active"  : "#f48fb1",   # active nav button
    "nav_inactive": "#e9a9bc",   # inactive nav button
}

STATE_COLORS = {
    "Calm"       : P["calm"],
    "Relaxed"    : P["calm"],
    "Mild Stress": P["mild"],
    "High Stress": P["high"],
    "Fatigued"   : P["high"],
    "Recovery"   : P["recover"],
    "Poor Signal": P["poor"],
}

DISPLAY_SAMPLES  = 500
MIN_BEATS        = 5
SERIAL_PORT      = "COM3"
BAUD_RATE        = 115200

HISTORY_SECONDS  = 8
FS               = 250
HISTORY_SAMPLES  = HISTORY_SECONDS * FS
METRICS_INTERVAL = 300


# ═══════════════════════════════════════════════════════════════════
#  RECOVERY SCORE ENGINE
# ═══════════════════════════════════════════════════════════════════

def compute_recovery(hrv_window, baseline, sqi, ptt=None, prev_state=None):
    """
    Computes a real-time, personalized Recovery Score (0-100) specifically designed
    for maternal physiology.

    Scientific Foundation:
    1. RMSSD: Primary indicator of parasympathetic activity (vagal tone).
    2. HR vs Baseline: Lower HR implies lower cardiovascular load.
    3. HRV Stability (SDNN + RR): Consistency indicates systemic stability.
    4. PPG Vascular Behavior (PTT): Steady PTT implies vascular stability;
       erratic PTT indicates sympathetic arousal / stress.
    
    Args:
        hrv_window (dict): {'rmssd': float, 'sdnn': float, 'rr': float, 'hr': float, 'valid_beats': int}
        baseline (dict): {'rmssd': float, 'hr': float}
        sqi (float): Signal Quality Index (0.0 to 1.0)
        ptt (float | None): Median Pulse Transit Time (proxy for vascular stability)
        prev_state (dict): Previous output state for temporal smoothing and trend.

    Returns:
        dict: {'recovery_score': float, 'confidence': float, 'trend': str, 'state': dict}
    """
    MIN_BEATS = 5

    if prev_state is None:
        prev_state = {
            "recovery_score": 50.0,
            "confidence": 0.0,
            "history": [50.0] * 5,
            "last_ptt": None,
        }

    # SQI Gating: If signal is very poor, smoothly decay confidence and hold state
    if hrv_window.get('valid_beats', 0) < MIN_BEATS or sqi < 0.2:
        return {
            "recovery_score": prev_state['recovery_score'],
            "confidence": max(0.0, prev_state['confidence'] - 0.1),
            "trend": "stable",
            "state": prev_state
        }

    # 1. Baseline Normalization
    rmssd_ratio = hrv_window['rmssd'] / max(baseline['rmssd'], 1e-5)
    hr_ratio    = baseline['hr'] / max(hrv_window['hr'], 30.0)

    rmssd_ratio = np.clip(rmssd_ratio, 0.1, 4.0)
    hr_ratio    = np.clip(hr_ratio, 0.4, 2.5)

    # 2. HRV Stability Score (using SDNN and Mean RR)
    # SDNN / Mean RR represents Coefficient of Variation of RR (CVRR)
    # A moderate, stable CVRR is good; excessive variability is noise, too little is stress.
    cvrr = hrv_window['sdnn'] / max(hrv_window['rr'], 300.0)
    
    cv_stability = 1.0
    if cvrr < 0.02:
        cv_stability = 0.85  # Rigid rhythm (stress)
    elif 0.04 <= cvrr <= 0.12:
        cv_stability = 1.10  # Healthy resting variability
    elif cvrr > 0.20:
        cv_stability = 0.90  # Too chaotic

    # 3. PPG / Vascular Stability Component
    # We look at PTT (Pulse Transit Time). A sudden drop in PTT correlates with 
    # blood pressure spikes and sympathetic arousal. Steady PTT is good.
    ptt_stability = 1.0
    last_ptt = prev_state.get('last_ptt')
    if ptt is not None and last_ptt is not None:
        ptt_change = abs(ptt - last_ptt) / max(last_ptt, 1.0)
        # If PTT changes by more than 10% suddenly, penalize recovery
        if ptt_change > 0.10:
            ptt_stability = max(0.7, 1.0 - (ptt_change * 2))
        else:
            ptt_stability = 1.05  # Bonus for very stable vascular tone

    # Update state's last ptt safely
    new_last_ptt = ptt if ptt is not None else last_ptt

    # 4. Composite Recovery Formula
    w_rmssd = 0.65
    w_hr    = 0.35
    
    recovery_raw = ((w_rmssd * rmssd_ratio) + (w_hr * hr_ratio)) * cv_stability * ptt_stability

    # Sigmoid scaling to 0-100 to keep it bounded and realistic
    k_steepness = 3.5
    x0_midpoint = 1.0
    instant_score = 100.0 / (1.0 + math.exp(-k_steepness * (recovery_raw - x0_midpoint)))

    # 5. Temporal Smoothing (EMA) gated by SQI
    base_alpha = 0.05
    dynamic_alpha = base_alpha * sqi  # Lower SQI = slower adaptation
    smoothed_score = (dynamic_alpha * instant_score) + ((1.0 - dynamic_alpha) * prev_state['recovery_score'])

    # Confidence scoring
    beat_factor = min(1.0, hrv_window['valid_beats'] / 15.0)
    instant_confidence = (sqi * 0.7) + (beat_factor * 0.3)
    smoothed_confidence = (0.05 * instant_confidence) + (0.95 * prev_state['confidence'])

    # Trend analysis
    history = prev_state['history'][-4:] + [smoothed_score]
    slope = history[-1] - history[0]

    if slope > 1.5:
        trend = "increasing"
    elif slope < -1.5:
        trend = "decreasing"
    else:
        trend = "stable"

    new_state = {
        "recovery_score": round(smoothed_score, 2),
        "confidence": round(smoothed_confidence, 2),
        "history": history,
        "last_ptt": new_last_ptt,
    }

    return {
        "recovery_score": new_state["recovery_score"],
        "confidence": new_state["confidence"],
        "trend": trend,
        "state": new_state
    }


# ═══════════════════════════════════════════════════════════════════
#  LIVE PROCESSOR (Backend — untouched logic)
# ═══════════════════════════════════════════════════════════════════

class LiveProcessor:
    STRESS_EMA_ALPHA = 0.20
    MIN_RR_FOR_HRV   = 5

    def __init__(self, fs: int = FS):
        self.fs = fs

        if PhysioMonitor is not None:
            self.monitor = PhysioMonitor(
                fs=self.fs,
                enable_ecg=True,
                enable_ppg=True,
                stress_window_sec=60.0,
                verbose=False,
            )
            self.monitor.baseline._is_set = True
            print("[LiveProcessor] PhysioMonitor ready")
        else:
            self.monitor = None
            print("[LiveProcessor] WARNING PhysioMonitor not available.")

        self._ecg_history: deque = deque(maxlen=HISTORY_SAMPLES)
        self._ppg_history: deque = deque(maxlen=HISTORY_SAMPLES)

        self._result_lock    : Lock              = Lock()
        self._update_in_prog : bool              = False
        self._new_result_rdy : bool              = False
        self._update_thread  : Optional[threading.Thread] = None

        self._last_update_ms : float = 0.0
        self._total_samples  : int   = 0

        self.last_result                       = None
        self._smoothed_stress : Optional[float] = None
        self._last_r_peaks    : List[int]       = []
        self._absolute_r_peaks: set             = set()

        self._update_calls = 0
        self._result_count = 0

        # Recovery score state
        self._recovery_state: Optional[dict] = None
        self._last_recovery: Optional[dict]  = None

        # History for pregnancy insights page (keep last 30 readings)
        self._stress_history: deque  = deque(maxlen=30)
        self._recovery_history: deque = deque(maxlen=30)

    def add_sample(self, ecg: float, ppg: float) -> None:
        self._ecg_history.append(ecg)
        self._ppg_history.append(ppg)
        self._total_samples += 1

    def tick(self) -> Optional[object]:
        if self.monitor is None:
            return None

        with self._result_lock:
            if self._new_result_rdy:
                self._new_result_rdy = False
                return self.last_result

        now_ms = time.monotonic() * 1000.0
        if (now_ms - self._last_update_ms) < METRICS_INTERVAL:
            return None
        if self._update_in_prog:
            return None

        n = len(self._ecg_history)
        if n < self.fs:
            return None

        ecg_arr = np.array(self._ecg_history, dtype=np.float64)
        ppg_arr = np.array(self._ppg_history, dtype=np.float64)
        snap_n  = len(ecg_arr)
        
        snap_total = self._total_samples

        self._last_update_ms = now_ms
        self._update_in_prog = True
        self._update_calls  += 1

        def _bg_update():
            try:
                result = self.monitor.update(
                    ecg_segment    = ecg_arr,
                    ppg_ir_segment = ppg_arr,
                )
            except Exception as exc:
                print(f"[LiveProcessor] exception: {exc}")
                self._update_in_prog = False
                return

            if result is None:
                self._update_in_prog = False
                return

            if result.stress and result.stress.stress_score is not None:
                raw = result.stress.stress_score * 100.0
                with self._result_lock:
                    if self._smoothed_stress is None:
                        self._smoothed_stress = raw
                    else:
                        self._smoothed_stress = (
                            self.STRESS_EMA_ALPHA * raw
                            + (1.0 - self.STRESS_EMA_ALPHA)
                            * self._smoothed_stress
                        )

            # Convert background segment indices to absolute lifetime indices
            absolute_peaks = [
                snap_total - snap_n + b.sample_idx 
                for b in result.beats
                if b.beat_class == 1 and 0 <= b.sample_idx < snap_n
            ]

            with self._result_lock:
                self.last_result    = result
                
                # Add new verified peaks to our lifetime set
                self._absolute_r_peaks.update(absolute_peaks)
                
                # Clean up old peaks so the set doesn't cause a memory leak
                cutoff = snap_total - (DISPLAY_SAMPLES * 2)
                self._absolute_r_peaks = {p for p in self._absolute_r_peaks if p >= cutoff}

                self._result_count += 1
                self._new_result_rdy = True

            self._update_in_prog = False

        t = threading.Thread(target=_bg_update, daemon=True)
        t.start()
        self._update_thread = t
        return None

    @property
    def smoothed_stress(self) -> Optional[float]:
        return self._smoothed_stress

    @property
    def recovery(self) -> Optional[dict]:
        return self._last_recovery

    @property
    def r_peaks_in_display(self) -> List[int]:
        """Maps absolute lifetime peaks perfectly to the rolling 0-499 screen array."""
        current_total = self._total_samples
        out = []
        with self._result_lock:
            for abs_p in self._absolute_r_peaks:
                samples_ago = current_total - abs_p
                # The newest sample is exactly at the right edge (DISPLAY_SAMPLES - 1)
                screen_x = (DISPLAY_SAMPLES - 1) - samples_ago
                
                # Only return the peak if it is currently visible on the screen
                if 0 <= screen_x < DISPLAY_SAMPLES:
                    out.append(screen_x)
        return out


# ═══════════════════════════════════════════════════════════════════
#  UI WIDGETS — Feminine Wellness Theme
# ═══════════════════════════════════════════════════════════════════

class AmbientAuraWidget(QtWidgets.QWidget):
    """Inner Balance — breathing organic visualization."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.stress_intensity = 0.0
        self.calm_intensity   = 1.0
        self._phase = 0.0
        self._painting = False  # recursion guard
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.start(50) 

    def update_intensities(self, stress_score: float, rmssd: float):
        self.stress_intensity = max(0.0, min(1.0, stress_score / 100.0))
        self.calm_intensity = max(0.0, min(1.0, rmssd / 60.0))

    def _animate(self):
        self._phase += 0.05
        self.update() 

    def paintEvent(self, ev):
        if self._painting:
            return
        self._painting = True
        try:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            w, h = self.width(), self.height()

            # Clip to rounded rect
            path = QtGui.QPainterPath()
            path.addRoundedRect(0, 0, w, h, 14, 14)
            p.fillPath(path, QtGui.QColor(P['bg1']))
            p.setClipPath(path)

            # Stress orb — warm rose
            cx1 = w * 0.7 + math.cos(self._phase * 0.8) * 20
            cy1 = h * 0.6 + math.sin(self._phase * 1.1) * 20
            r1  = 80 + (100 * self.stress_intensity)
            a1  = int(40 + (120 * self.stress_intensity))
            grad1 = QtGui.QRadialGradient(cx1, cy1, r1)
            grad1.setColorAt(0, QtGui.QColor(255, 138, 138, a1))
            grad1.setColorAt(1, QtGui.QColor(255, 138, 138, 0))
            p.fillRect(0, 0, w, h, grad1)

            # Calm orb — soft green
            cx2 = w * 0.3 + math.sin(self._phase * 0.7) * 30
            cy2 = h * 0.4 + math.cos(self._phase * 0.9) * 20
            r2  = 100 + (80 * self.calm_intensity)
            a2  = int(30 + (110 * self.calm_intensity))
            grad2 = QtGui.QRadialGradient(cx2, cy2, r2)
            grad2.setColorAt(0, QtGui.QColor(126, 214, 167, a2))
            grad2.setColorAt(1, QtGui.QColor(126, 214, 167, 0))
            p.fillRect(0, 0, w, h, grad2)

            # Lavender orb — serenity
            cx3 = w * 0.5 + math.cos(self._phase * 0.5) * 40
            cy3 = h * 0.7 + math.sin(self._phase * 0.4) * 15
            r3  = 120 + math.sin(self._phase) * 10
            a3  = max(10, 60 - int(30 * self.stress_intensity))
            grad3 = QtGui.QRadialGradient(cx3, cy3, r3)
            grad3.setColorAt(0, QtGui.QColor(203, 166, 247, a3))
            grad3.setColorAt(1, QtGui.QColor(203, 166, 247, 0))
            p.fillRect(0, 0, w, h, grad3)

            # Title
            p.setPen(QtGui.QColor(P['t1']))
            font = QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold)
            font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 3.0)
            p.setFont(font)
            p.drawText(QtCore.QRect(0, 12, w, 28), Qt.AlignHCenter, "INNER BALANCE")
            p.end()
        finally:
            self._painting = False


class MetricTile(QtWidgets.QFrame):
    def __init__(self, label: str, unit: str = "",
                 accent: str = None, parent=None):
        super().__init__(parent)
        self._accent = accent or P["accent"]
        self._unit   = unit
        self.setMinimumSize(110, 84)

        self.setStyleSheet(f"MetricTile {{ background: {P['bg2']}; border: 1px solid {P['border']}; border-radius: 10px; }}")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        stripe = QtWidgets.QFrame()
        stripe.setFixedHeight(3)
        stripe.setStyleSheet(f"background: {self._accent}; border: none; border-radius: 10px 10px 0 0;")
        outer.addWidget(stripe)

        inner = QtWidgets.QVBoxLayout()
        inner.setContentsMargins(13, 8, 13, 10)
        inner.setSpacing(3)

        vrow = QtWidgets.QHBoxLayout()
        vrow.setSpacing(4)
        vrow.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._val_lbl = QtWidgets.QLabel("—")
        self._val_lbl.setStyleSheet(f"color: {P['t0']}; font-size: 24px; font-weight: 700; font-family: 'Segoe UI', sans-serif; background: transparent; border: none; padding: 0;")
        vrow.addWidget(self._val_lbl)

        self._unit_lbl = QtWidgets.QLabel(unit)
        self._unit_lbl.setStyleSheet(f"color: {P['t2']}; font-size: 10px; background: transparent; border: none; padding: 0 0 4px 0;")
        self._unit_lbl.setAlignment(Qt.AlignBottom)
        vrow.addWidget(self._unit_lbl)
        vrow.addStretch()
        inner.addLayout(vrow)

        lbl = QtWidgets.QLabel(label.upper())
        lbl.setStyleSheet(f"color: {P['t2']}; font-size: 8px; letter-spacing: 1.2px; font-family: 'Segoe UI', sans-serif; background: transparent; border: none;")
        inner.addWidget(lbl)
        outer.addLayout(inner)

    def set_value(self, val: Optional[float], fmt: str = "{:.1f}", color: str = None):
        col = color or P["t0"]
        if val is None or val == 0.0:
            self._val_lbl.setText("—")
            self._val_lbl.setStyleSheet(f"color: {P['t2']}; font-size: 24px; font-weight: 700; font-family: 'Segoe UI', sans-serif; background: transparent; border: none; padding: 0;")
        else:
            self._val_lbl.setText(fmt.format(val))
            self._val_lbl.setStyleSheet(f"color: {col}; font-size: 24px; font-weight: 700; font-family: 'Segoe UI', sans-serif; background: transparent; border: none; padding: 0;")


class StressGauge(QtWidgets.QWidget):
    """Emotional Load gauge."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value   = 0.0
        self._has_data= False
        self._painting = False
        self.setMinimumSize(140, 140)
        self.setMaximumSize(160, 160)

    def set_value(self, v: float):
        self._value    = max(0.0, min(100.0, v))
        self._has_data = True
        self.update()

    def clear(self):
        self._has_data = False
        self.update()

    def _state_color(self, v: float) -> str:
        if v < 35:   return P["calm"]
        if v < 65:   return P["mild"]
        return P["high"]

    def paintEvent(self, _ev):
        if self._painting:
            return
        self._painting = True
        try:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)

            w, h   = self.width(), self.height()
            cx, cy = w // 2, h // 2
            r      = min(w, h) // 2 - 14

            pen_tr = QtGui.QPen(QtGui.QColor(P["bg3"]), 10)
            pen_tr.setCapStyle(Qt.RoundCap)
            p.setPen(pen_tr)
            p.drawArc(cx-r, cy-r, 2*r, 2*r, 225*16, -270*16)

            if self._has_data and self._value > 0:
                color = self._state_color(self._value)
                pen_v = QtGui.QPen(QtGui.QColor(color), 10)
                pen_v.setCapStyle(Qt.RoundCap)
                p.setPen(pen_v)
                span = int(-270 * 16 * self._value / 100.0)
                p.drawArc(cx-r, cy-r, 2*r, 2*r, 225*16, span)

            if self._has_data:
                color = self._state_color(self._value)
                p.setPen(QtGui.QColor(color))
                f = QtGui.QFont("Segoe UI", 22, QtGui.QFont.Bold)
                p.setFont(f)
                p.drawText(QtCore.QRect(cx-35, cy-18, 70, 36), Qt.AlignCenter, f"{self._value:.0f}")
            else:
                p.setPen(QtGui.QColor(P["t2"]))
                f = QtGui.QFont("Segoe UI", 22, QtGui.QFont.Bold)
                p.setFont(f)
                p.drawText(QtCore.QRect(cx-20, cy-12, 40, 24), Qt.AlignCenter, "—")

            p.setPen(QtGui.QColor(P["t2"]))
            f2 = QtGui.QFont("Segoe UI", 6)
            f2.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.2)
            p.setFont(f2)
            p.drawText(QtCore.QRect(cx-40, cy+20, 80, 14), Qt.AlignCenter, "EMOTIONAL LOAD")
            p.end()
        finally:
            self._painting = False


class RecoveryGauge(QtWidgets.QWidget):
    """Body Recovery gauge with trend indicator."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value    = 0.0
        self._has_data = False
        self._trend    = "stable"
        self._confidence = 0.0
        self._painting = False
        self.setMinimumSize(140, 140)
        self.setMaximumSize(160, 160)

    def set_value(self, v: float, trend: str = "stable", confidence: float = 0.0):
        self._value      = max(0.0, min(100.0, v))
        self._trend      = trend
        self._confidence = confidence
        self._has_data   = True
        self.update()

    def clear(self):
        self._has_data = False
        self.update()

    def _zone_color(self, v: float) -> str:
        if v < 30:   return P["rec_low"]
        if v < 70:   return P["rec_mid"]
        return P["rec_hi"]

    def _trend_symbol(self) -> str:
        if self._trend == "increasing": return "▲"
        if self._trend == "decreasing": return "▼"
        return "●"

    def paintEvent(self, _ev):
        if self._painting:
            return
        self._painting = True
        try:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)

            w, h   = self.width(), self.height()
            cx, cy = w // 2, h // 2
            r      = min(w, h) // 2 - 14

            pen_tr = QtGui.QPen(QtGui.QColor(P["bg3"]), 10)
            pen_tr.setCapStyle(Qt.RoundCap)
            p.setPen(pen_tr)
            p.drawArc(cx-r, cy-r, 2*r, 2*r, 225*16, -270*16)

            if self._has_data and self._value > 0:
                color = self._zone_color(self._value)
                pen_v = QtGui.QPen(QtGui.QColor(color), 10)
                pen_v.setCapStyle(Qt.RoundCap)
                p.setPen(pen_v)
                span = int(-270 * 16 * self._value / 100.0)
                p.drawArc(cx-r, cy-r, 2*r, 2*r, 225*16, span)

            if self._has_data:
                color = self._zone_color(self._value)
                p.setPen(QtGui.QColor(color))
                f = QtGui.QFont("Segoe UI", 22, QtGui.QFont.Bold)
                p.setFont(f)
                p.drawText(QtCore.QRect(cx-35, cy-18, 70, 36), Qt.AlignCenter, f"{self._value:.0f}")

                p.setPen(QtGui.QColor(color))
                f_trend = QtGui.QFont("Segoe UI", 8)
                p.setFont(f_trend)
                p.drawText(QtCore.QRect(cx+22, cy-16, 20, 16), Qt.AlignCenter, self._trend_symbol())
            else:
                p.setPen(QtGui.QColor(P["t2"]))
                f = QtGui.QFont("Segoe UI", 22, QtGui.QFont.Bold)
                p.setFont(f)
                p.drawText(QtCore.QRect(cx-20, cy-12, 40, 24), Qt.AlignCenter, "—")

            p.setPen(QtGui.QColor(P["t2"]))
            f2 = QtGui.QFont("Segoe UI", 6)
            f2.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.2)
            p.setFont(f2)
            p.drawText(QtCore.QRect(cx-40, cy+20, 80, 14), Qt.AlignCenter, "BODY RECOVERY")
            p.end()
        finally:
            self._painting = False


class SQIBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._painting = False
        self.setFixedHeight(5)

    def set_value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _ev):
        if self._painting:
            return
        self._painting = True
        try:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            w, h = self.width(), self.height()
            p.setBrush(QtGui.QColor(P["bg3"]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(0, 0, w, h, 2, 2)
            fill = int(w * self._value)
            if fill > 0:
                v = self._value
                col = P["calm"] if v > 0.7 else (P["mild"] if v > 0.4 else P["high"])
                p.setBrush(QtGui.QColor(col))
                p.drawRoundedRect(0, 0, fill, h, 2, 2)
            p.end()
        finally:
            self._painting = False


class StateBadge(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__("Awaiting data", parent)
        self._set_style(P["t2"])
        self.setAlignment(Qt.AlignCenter)

    def _set_style(self, color: str):
        r, g, b = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        self.setStyleSheet(f"QLabel {{ color: {color}; background: rgba({r},{g},{b},0.10); border: 1px solid rgba({r},{g},{b},0.40); border-radius: 14px; font-size: 13px; font-weight: 600; font-family: 'Segoe UI', sans-serif; padding: 5px 18px; }}")

    def set_state(self, state: str):
        self.setText(state)
        color = STATE_COLORS.get(state, P["t1"])
        self._set_style(color)


class WaveformPlot(pg.PlotWidget):
    def __init__(self, line_color: str, label: str, show_peaks: bool = False, parent=None):
        super().__init__(parent, background=P["bg2"])
        self._color      = line_color
        self._show_peaks = show_peaks
        self._data       = np.zeros(DISPLAY_SAMPLES, dtype=np.float32)

        self.setMenuEnabled(False)
        self.hideAxis("bottom")
        self.getAxis("left").setStyle(tickLength=3, tickTextOffset=3)
        self.getAxis("left").setTextPen(pg.mkPen(color=P["t2"], width=1))
        self.getAxis("left").setPen(pg.mkPen(color=P["border"], width=1))
        self.showGrid(x=False, y=True, alpha=0.08)
        self.setContentsMargins(0, 0, 0, 0)

        self._label_item = pg.TextItem(text=label, color=P["t2"], anchor=(0, 0))
        font = QtGui.QFont("Segoe UI", 8)
        self._label_item.setFont(font)
        self.addItem(self._label_item)

        self._curve = self.plot(self._data, pen=pg.mkPen(color=line_color, width=1.8))

        if show_peaks:
            self._scatter = pg.ScatterPlotItem(size=10, pen=None, brush=pg.mkBrush(P["rpeak"]))
            self._scatter.setZValue(10)
            self.addItem(self._scatter)
        else:
            self._scatter = None

    def set_raw_peaks(self, absolute_indices: List[int]):
        if self._scatter is None or not absolute_indices:
            if self._scatter is not None:
                self._scatter.setData(x=[], y=[])
            return
        
        valid_x = [x for x in absolute_indices if 0 <= x < DISPLAY_SAMPLES]
        valid_y = [float(self._data[x]) for x in valid_x]
        
        if valid_x:
            self._scatter.setData(x=valid_x, y=valid_y)
        else:
            self._scatter.setData(x=[], y=[])


class TimelineList(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; color: {P['t1']}; font-size: 11px; font-family: 'Segoe UI', sans-serif; }}
            QListWidget::item {{ padding: 5px 6px; border-bottom: 1px solid {P['border']}; }}
            QScrollBar:vertical {{ background: {P['bg2']}; width: 5px; border: none; }}
            QScrollBar::handle:vertical {{ background: {P['bg4']}; border-radius: 2px; }}
        """)
        self._seen_times: set = set()

    def ingest_timeline(self, events: List[dict]):
        for ev in events:
            key = (ev.get("time_s"), ev.get("state"))
            if key in self._seen_times:
                continue
            self._seen_times.add(key)

            t_s   = ev.get("time_s", 0)
            state = ev.get("state", "")
            score = ev.get("stress", 0)
            m     = int(t_s // 60)
            s_    = int(t_s  % 60)
            color = STATE_COLORS.get(state, P["t1"])

            row  = f"  {m:02d}:{s_:02d}   {state:<16}  {score:.0f}"
            item = QtWidgets.QListWidgetItem(row)
            item.setForeground(QtGui.QColor(color))
            self.insertItem(0, item)

        if self.count() > 60:
            for _ in range(self.count() - 60):
                self.takeItem(self.count() - 1)

    def reset(self):
        self.clear()
        self._seen_times.clear()


# ═══════════════════════════════════════════════════════════════════
#  MAIN WINDOW — Multi-Page Pregnancy Wellness Experience
# ═══════════════════════════════════════════════════════════════════

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, port: str = SERIAL_PORT):
        super().__init__()
        self.setWindowTitle("MaternalGuard  ·  Pregnancy Wellness Monitor")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 700)

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {P['bg0']}; color: {P['t0']}; font-family: 'Segoe UI', sans-serif; }}
            QToolBar {{ background: {P['bg2']}; border-bottom: 1px solid {P['border']}; spacing: 4px; padding: 4px 12px; }}
            QStatusBar {{ background: {P['bg2']}; border-top: 1px solid {P['border']}; color: {P['t2']}; font-size: 10px; }}
            QFrame[card='true'] {{ background: {P['bg1']}; border: 1px solid {P['border']}; border-radius: 12px; }}
        """)

        self.processor = LiveProcessor(fs=FS)
        self.port = port
        self.serial_conn = None
        self._connected = False

        self._n_updates   = 0
        self._session_sec = 0
        self._last_state  = ""
        self._high_stress_t: Optional[float] = None

        self.data_ecg = np.zeros(DISPLAY_SAMPLES)
        self.data_ppg = np.zeros(DISPLAY_SAMPLES)
        self.raw_serial_buffer = b""
        self._last_metrics_result = None

        self._build_toolbar()
        self._build_pages()
        self._build_statusbar()
        self._connect_serial()

        self._serial_timer = QTimer(self)
        self._serial_timer.timeout.connect(self._process_serial)
        self._serial_timer.start(16)

        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._poll_metrics)
        self._metrics_timer.start(100)   

        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._tick_session)
        self._session_timer.start(1000)

    # ── Toolbar ────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(16, 16))

        brand = self._lbl("  🌸 MaternalGuard", 14, P["accent"], bold=True)
        tb.addWidget(brand)

        sp1 = QtWidgets.QWidget()
        sp1.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        tb.addWidget(sp1)

        self._conn_lbl = self._lbl("Connecting…", 10, P["t2"])
        tb.addWidget(self._conn_lbl)
        tb.addWidget(self._divider())

        self._session_lbl = self._lbl("00:00:00", 10, P["t2"])
        tb.addWidget(self._session_lbl)
        tb.addWidget(self._divider())

        self._nav_btns = []
        nav_items = [
            ("🏠 Dashboard",         0),
            ("🤰 Pregnancy Insights", 1),
            ("🕊️ Wellness Journey",    2),
            ("⚙️ Calibration",        3),
        ]
        for label, idx in nav_items:
            btn = self._nav_btn(label, idx)
            tb.addWidget(btn)
            self._nav_btns.append(btn)
        self._nav_btns[0].setProperty("active", True)
        self._update_nav_styles()

        tb.addWidget(self._divider())
        self._btn_clear = self._toolbar_btn("Clear Journey", self._on_clear_timeline)
        tb.addWidget(self._btn_clear)
        tb.addWidget(QtWidgets.QWidget())

    def _nav_btn(self, text: str, idx: int) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton(text)
        b.setProperty("active", False)
        b.setCursor(Qt.PointingHandCursor)
        def on_click(_checked, i=idx):
            self.stack.setCurrentIndex(i)
            for nb in self._nav_btns:
                nb.setProperty("active", False)
            b.setProperty("active", True)
            self._update_nav_styles()
        b.clicked.connect(on_click)
        return b

    def _update_nav_styles(self):
        for btn in self._nav_btns:
            if btn.property("active"):
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {P['accent']}; color: white; border: none;
                    border-radius: 6px; padding: 5px 14px; font-size: 11px; font-weight: 600; font-family: 'Segoe UI'; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{ background: {P['bg3']}; color: {P['t1']}; border: 1px solid {P['border']};
                    border-radius: 6px; padding: 5px 14px; font-size: 11px; font-family: 'Segoe UI'; }}
                    QPushButton:hover {{ background: {P['bg4']}; color: {P['t0']}; }}
                """)

    # ── Helpers ────────────────────────────────────────────────
    def _lbl(self, text: str, size: int = 11, color: str = None, bold: bool = False, mono: bool = False) -> QtWidgets.QLabel:
        l = QtWidgets.QLabel(text)
        weight = "700" if bold else "400"
        ff = "'Segoe UI', 'Helvetica Neue', sans-serif"
        l.setStyleSheet(f"color:{color or P['t1']}; font-size:{size}px; font-weight:{weight}; font-family:{ff}; background:transparent; border:none;")
        return l

    def _divider(self) -> QtWidgets.QFrame:
        d = QtWidgets.QFrame()
        d.setFrameShape(QtWidgets.QFrame.VLine)
        d.setStyleSheet(f"color:{P['border']}; margin:4px 4px; background:transparent;")
        return d

    def _toolbar_btn(self, text: str, slot) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton(text)
        b.setStyleSheet(f"""
            QPushButton {{ background: {P['bg3']}; color: {P['t1']}; border: 1px solid {P['border2']};
            border-radius: 6px; padding: 4px 12px; font-size: 10px; font-family: 'Segoe UI'; }}
            QPushButton:hover {{ color: {P['t0']}; border-color: {P['accent']}; background: {P['bg4']}; }}
        """)
        b.clicked.connect(slot)
        return b

    def _card(self) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setProperty("card", True)
        f.setStyleSheet(f"QFrame[card='true'] {{ background: {P['bg1']}; border: 1px solid {P['border']}; border-radius: 12px; }}")
        return f

    def _section_lbl(self, text: str) -> QtWidgets.QLabel:
        l = QtWidgets.QLabel(text)
        l.setStyleSheet(f"color:{P['t2']}; font-size:9px; letter-spacing:1.8px; font-family:'Segoe UI'; font-weight:600; background:transparent; border:none;")
        return l

    # ── Page System ────────────────────────────────────────────
    def _build_pages(self):
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.stack.addWidget(self._build_dashboard_page())
        self.stack.addWidget(self._build_pregnancy_page())
        self.stack.addWidget(self._build_journey_page())
        self.stack.addWidget(self._build_calibration_page())

        self.stack.setCurrentIndex(0)

    # ── Page 1: Dashboard ──────────────────────────────────────
    def _build_dashboard_page(self) -> QtWidgets.QWidget:
        root_w = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(root_w)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # LEFT — waveforms + vitals
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)

        ecg_card = self._card()
        ecg_l = QtWidgets.QVBoxLayout(ecg_card)
        ecg_l.setContentsMargins(10, 8, 10, 8)
        ecg_l.setSpacing(4)

        ecg_hdr = QtWidgets.QHBoxLayout()
        ecg_hdr.addWidget(self._lbl("♡ Heart Rhythm", 12, P["ecg"], bold=True))
        ecg_hdr.addStretch()
        self._ecg_hr_badge = self._lbl(" bpm", 10, P["t2"])
        self._ecg_sqi_text = self._lbl("SQI %", 10, P["t2"])
        ecg_hdr.addWidget(self._ecg_hr_badge)
        ecg_hdr.addWidget(self._lbl("·", 10, P["t2"]))
        ecg_hdr.addWidget(self._ecg_sqi_text)
        ecg_l.addLayout(ecg_hdr)

        self._ecg_plot = WaveformPlot(P["ecg"], "ECG", show_peaks=True)
        self._ecg_plot.setMinimumHeight(155)
        self._ecg_plot.setYRange(5000, 30000)
        ecg_l.addWidget(self._ecg_plot)

        sqirow = QtWidgets.QHBoxLayout()
        sqirow.setSpacing(8)
        sqirow.addWidget(self._lbl("SIGNAL QUALITY", 8, P["t2"]))
        self._sqi_bar = SQIBar()
        sqirow.addWidget(self._sqi_bar, 1)
        ecg_l.addLayout(sqirow)
        left.addWidget(ecg_card, 3)

        ppg_card = self._card()
        ppg_l = QtWidgets.QVBoxLayout(ppg_card)
        ppg_l.setContentsMargins(10, 8, 10, 8)
        ppg_l.setSpacing(4)

        ppg_hdr = QtWidgets.QHBoxLayout()
        ppg_hdr.addWidget(self._lbl("💜 Blood Flow", 12, P["ppg"], bold=True))
        ppg_hdr.addStretch()
        self._ppg_br_badge = self._lbl("", 10, P["t2"])
        ppg_hdr.addWidget(self._ppg_br_badge)
        ppg_l.addLayout(ppg_hdr)

        self._ppg_plot = pg.PlotWidget(background=P["bg2"])
        self._ppg_plot.showGrid(x=False, y=True, alpha=0.08)
        self._ppg_plot._curve = self._ppg_plot.plot(pen=pg.mkPen(P["ppg"], width=1.8))
        self._ppg_plot.setMinimumHeight(155)
        self._ppg_plot.hideAxis("bottom")
        ppg_l.addWidget(self._ppg_plot)
        left.addWidget(ppg_card, 3)

        tiles_row = QtWidgets.QHBoxLayout()
        tiles_row.setSpacing(8)

        self._t_hr    = MetricTile("Heart Rate",        "bpm",    P["ppg"])
        self._t_rmssd = MetricTile("Heart Rhythm",      "ms",     P["calm"])
        self._t_sdnn  = MetricTile("Rhythm Variation",  "ms",     P["violet"])
        self._t_rr    = MetricTile("Beat Interval",     "ms",     P["mild"])
        self._t_ptt   = MetricTile("Vascular Flow",     "ms",     P["accent"])
        self._t_br    = MetricTile("Breath Rate",       "br/min", P["calm"])

        for t in [self._t_hr, self._t_rmssd, self._t_sdnn, self._t_rr, self._t_ptt, self._t_br]:
            tiles_row.addWidget(t)
        left.addLayout(tiles_row)
        root.addLayout(left, 57)

        # RIGHT — gauges, aura, wellness
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)

        stress_card = self._card()
        stress_l = QtWidgets.QVBoxLayout(stress_card)
        stress_l.setContentsMargins(16, 12, 16, 14)
        stress_l.setSpacing(10)
        stress_l.addWidget(self._section_lbl("BODY BALANCE & WELLNESS"))

        gauge_row = QtWidgets.QHBoxLayout()
        gauge_row.setSpacing(12)

        stress_gauge_col = QtWidgets.QVBoxLayout()
        stress_gauge_col.setAlignment(Qt.AlignCenter)
        self._stress_gauge = StressGauge()
        stress_gauge_col.addWidget(self._stress_gauge)
        gauge_row.addLayout(stress_gauge_col)

        recovery_gauge_col = QtWidgets.QVBoxLayout()
        recovery_gauge_col.setAlignment(Qt.AlignCenter)
        self._recovery_gauge = RecoveryGauge()
        recovery_gauge_col.addWidget(self._recovery_gauge)
        gauge_row.addLayout(recovery_gauge_col)

        info_col = QtWidgets.QVBoxLayout()
        info_col.setSpacing(5)
        self._state_badge = StateBadge()
        self._stress_desc = self._lbl("Wear the sensor to begin your wellness journey", 10, P["t2"])
        self._stress_desc.setWordWrap(True)

        self._stress_prog = QtWidgets.QProgressBar()
        self._stress_prog.setRange(0, 100); self._stress_prog.setValue(0)
        self._stress_prog.setTextVisible(False); self._stress_prog.setFixedHeight(4)
        self._stress_prog.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 2px; border: none; }} QProgressBar::chunk {{ background: {P['calm']}; border-radius: 2px; }}")

        self._recovery_prog = QtWidgets.QProgressBar()
        self._recovery_prog.setRange(0, 100); self._recovery_prog.setValue(0)
        self._recovery_prog.setTextVisible(False); self._recovery_prog.setFixedHeight(4)
        self._recovery_prog.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 2px; border: none; }} QProgressBar::chunk {{ background: {P['rec_mid']}; border-radius: 2px; }}")

        self._recovery_trend_lbl = self._lbl("Body recovery: awaiting data", 9, P["t2"])
        self._bl_lbl = self._lbl("Default baseline", 9, P["t2"])

        info_col.addWidget(self._state_badge)
        info_col.addWidget(self._stress_desc)
        info_col.addWidget(self._lbl("EMOTIONAL LOAD", 8, P["t2"]))
        info_col.addWidget(self._stress_prog)
        info_col.addWidget(self._lbl("BODY RECOVERY", 8, P["t2"]))
        info_col.addWidget(self._recovery_prog)
        info_col.addWidget(self._recovery_trend_lbl)
        info_col.addWidget(self._bl_lbl)
        info_col.addStretch()
        gauge_row.addLayout(info_col, 1)
        stress_l.addLayout(gauge_row)
        right.addWidget(stress_card)

        mid_row = QtWidgets.QHBoxLayout()
        mid_row.setSpacing(10)

        aura_card = self._card()
        aura_l = QtWidgets.QVBoxLayout(aura_card)
        aura_l.setContentsMargins(0, 0, 0, 0)
        self._aura_widget = AmbientAuraWidget()
        aura_l.addWidget(self._aura_widget)
        mid_row.addWidget(aura_card, 1)

        ptt_card = self._card()
        ptt_l = QtWidgets.QVBoxLayout(ptt_card)
        ptt_l.setContentsMargins(14, 10, 14, 12)
        ptt_l.setSpacing(4)
        ptt_l.addWidget(self._section_lbl("VASCULAR HEALTH"))
        self._ptt_num = self._lbl("—", 32, P["violet"], bold=True)
        self._ptt_unit = self._lbl("ms", 11, P["t2"])
        pr = QtWidgets.QHBoxLayout()
        pr.addWidget(self._ptt_num); pr.addWidget(self._ptt_unit); pr.addStretch()
        ptt_l.addLayout(pr)
        ptt_l.addWidget(self._lbl("Blood flow timing · 100–300 ms normal", 9, P["t2"]))
        mid_row.addWidget(ptt_card, 1)

        right.addLayout(mid_row)

        self._alert_bar = QtWidgets.QLabel("🌸  Elevated emotional load detected — consider a breathing break")
        self._alert_bar.setAlignment(Qt.AlignCenter)
        self._alert_bar.setStyleSheet(f"QLabel {{ background: rgba(255,138,138,0.12); color: {P['high']}; border: 1px solid rgba(255,138,138,0.35); border-radius: 8px; padding: 8px; font-size: 11px; }}")
        self._alert_bar.hide()
        right.addWidget(self._alert_bar)

        root.addLayout(right, 43)
        return root_w

    # ── Page 2: Pregnancy Insights ─────────────────────────────
    def _build_pregnancy_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = self._lbl("🤰  Pregnancy Wellness Insights", 18, P["t0"], bold=True)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = self._lbl("Real-time analysis of your body's support for you and your baby", 11, P["t2"])
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        # Top row — Maternal Stability + Fetal Support
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(16)

        # Maternal Stability Card
        ms_card = self._card()
        ms_l = QtWidgets.QVBoxLayout(ms_card)
        ms_l.setContentsMargins(20, 16, 20, 16)
        ms_l.setSpacing(8)
        ms_l.addWidget(self._section_lbl("MATERNAL STABILITY"))
        self._preg_ms_score = self._lbl("—", 48, P["calm"], bold=True)
        self._preg_ms_score.setAlignment(Qt.AlignCenter)
        ms_l.addWidget(self._preg_ms_score)
        self._preg_ms_desc = self._lbl("Waiting for enough heart rhythm data…", 11, P["t2"])
        self._preg_ms_desc.setWordWrap(True)
        self._preg_ms_desc.setAlignment(Qt.AlignCenter)
        ms_l.addWidget(self._preg_ms_desc)
        self._preg_ms_bar = QtWidgets.QProgressBar()
        self._preg_ms_bar.setRange(0, 100); self._preg_ms_bar.setValue(0)
        self._preg_ms_bar.setTextVisible(False); self._preg_ms_bar.setFixedHeight(6)
        self._preg_ms_bar.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 3px; border: none; }} QProgressBar::chunk {{ background: {P['calm']}; border-radius: 3px; }}")
        ms_l.addWidget(self._preg_ms_bar)
        top_row.addWidget(ms_card)

        # Fetal Support Card
        fs_card = self._card()
        fs_l = QtWidgets.QVBoxLayout(fs_card)
        fs_l.setContentsMargins(20, 16, 20, 16)
        fs_l.setSpacing(8)
        fs_l.addWidget(self._section_lbl("FETAL SUPPORT"))
        self._preg_fs_score = self._lbl("—", 48, P["rec_mid"], bold=True)
        self._preg_fs_score.setAlignment(Qt.AlignCenter)
        fs_l.addWidget(self._preg_fs_score)
        self._preg_fs_desc = self._lbl("Based on recovery and vascular stability…", 11, P["t2"])
        self._preg_fs_desc.setWordWrap(True)
        self._preg_fs_desc.setAlignment(Qt.AlignCenter)
        fs_l.addWidget(self._preg_fs_desc)
        self._preg_fs_bar = QtWidgets.QProgressBar()
        self._preg_fs_bar.setRange(0, 100); self._preg_fs_bar.setValue(0)
        self._preg_fs_bar.setTextVisible(False); self._preg_fs_bar.setFixedHeight(6)
        self._preg_fs_bar.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 3px; border: none; }} QProgressBar::chunk {{ background: {P['rec_mid']}; border-radius: 3px; }}")
        fs_l.addWidget(self._preg_fs_bar)
        top_row.addWidget(fs_card)

        layout.addLayout(top_row)

        # Insight message card
        insight_card = self._card()
        ins_l = QtWidgets.QVBoxLayout(insight_card)
        ins_l.setContentsMargins(24, 18, 24, 18)
        ins_l.setSpacing(6)
        ins_l.addWidget(self._section_lbl("HOW YOUR BODY FEELS"))
        self._preg_insight_msg = self._lbl("🌸  Wear your sensor and relax. Insights will appear here as your body's rhythms are analyzed.", 13, P["t1"])
        self._preg_insight_msg.setWordWrap(True)
        ins_l.addWidget(self._preg_insight_msg)
        layout.addWidget(insight_card)

        # Trend card
        trend_card = self._card()
        tr_l = QtWidgets.QVBoxLayout(trend_card)
        tr_l.setContentsMargins(20, 14, 20, 14)
        tr_l.setSpacing(6)
        tr_l.addWidget(self._section_lbl("SESSION TRENDS"))
        self._preg_trend_text = self._lbl("Emotional load and recovery trends will update live during your session.", 11, P["t2"])
        self._preg_trend_text.setWordWrap(True)
        tr_l.addWidget(self._preg_trend_text)
        layout.addWidget(trend_card, 1)

        return page

    # ── Page 3: Wellness Journey (Timeline) ────────────────────
    def _build_journey_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = self._lbl("🕊️  Your Wellness Journey", 18, P["t0"], bold=True)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = self._lbl("A timeline of how your body moves through states of calm and load", 11, P["t2"])
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        tl_card = self._card()
        tl_l = QtWidgets.QVBoxLayout(tl_card)
        tl_l.setContentsMargins(16, 14, 16, 14)
        tl_l.setSpacing(6)

        tl_hdr = QtWidgets.QHBoxLayout()
        tl_hdr.addWidget(self._section_lbl("WELLNESS JOURNEY"))
        tl_hdr.addStretch()
        tl_hdr.addWidget(self._lbl("mm:ss    Body State            Score", 9, P["t2"]))
        tl_l.addLayout(tl_hdr)

        self._timeline = TimelineList()
        tl_l.addWidget(self._timeline)
        layout.addWidget(tl_card, 1)

        return page

    # ── Page 4: Calibration ────────────────────────────────────
    def _build_calibration_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = self._lbl("⚙️  Calibration & Baseline", 18, P["t0"], bold=True)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions card
        inst_card = self._card()
        inst_l = QtWidgets.QVBoxLayout(inst_card)
        inst_l.setContentsMargins(24, 20, 24, 20)
        inst_l.setSpacing(12)
        inst_l.addWidget(self._section_lbl("BASELINE SETUP"))

        steps = [
            "1.  Find a quiet, comfortable place to sit or lie down",
            "2.  Attach the sensor and ensure good contact (green SQI bar)",
            "3.  Close your eyes and breathe naturally for 2–3 minutes",
            "4.  The system will automatically learn your personal baseline",
        ]
        for s in steps:
            sl = self._lbl(s, 12, P["t1"])
            sl.setWordWrap(True)
            inst_l.addWidget(sl)

        layout.addWidget(inst_card)

        # Live RMSSD display
        rmssd_card = self._card()
        rmssd_l = QtWidgets.QVBoxLayout(rmssd_card)
        rmssd_l.setContentsMargins(20, 16, 20, 16)
        rmssd_l.setSpacing(8)
        rmssd_l.addWidget(self._section_lbl("LIVE HEART RHYTHM BALANCE"))

        self._calib_rmssd = self._lbl("—", 48, P["calm"], bold=True)
        self._calib_rmssd.setAlignment(Qt.AlignCenter)
        rmssd_l.addWidget(self._calib_rmssd)
        self._calib_rmssd_unit = self._lbl("RMSSD (ms) — higher is more relaxed", 10, P["t2"])
        self._calib_rmssd_unit.setAlignment(Qt.AlignCenter)
        rmssd_l.addWidget(self._calib_rmssd_unit)

        self._calib_status = self._lbl("🌸  Waiting for sensor data…", 12, P["t2"])
        self._calib_status.setAlignment(Qt.AlignCenter)
        self._calib_status.setWordWrap(True)
        rmssd_l.addWidget(self._calib_status)

        layout.addWidget(rmssd_card, 1)

        return page

    # ── Status Bar ─────────────────────────────────────────────
    def _build_statusbar(self):
        sb = self.statusBar()
        self._sb_left  = self._lbl("Connecting…", 10, P["t2"])
        self._sb_right = self._lbl("", 10, P["t2"])
        sb.addWidget(self._sb_left, 1)
        sb.addPermanentWidget(self._sb_right)

    # ── Serial Connection ──────────────────────────────────────
    def _connect_serial(self):
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.serial_conn = serial.Serial(self.port, BAUD_RATE, timeout=0)
            self._connected = True
            self._conn_lbl.setText(f"● Connected {self.port}")
            self._conn_lbl.setStyleSheet(f"color:{P['calm']}; font-size:10px; background:transparent; border:none;")
            self._sb_left.setText(f"Connected {self.port}")
        except Exception as e:
            self._connected = False
            self._conn_lbl.setText(f"○ {self.port} unavailable")
            self._conn_lbl.setStyleSheet(f"color:{P['mild']}; font-size:10px; background:transparent; border:none;")
            self._sb_left.setText(f"Disconnected: {e}")

    # ── Serial Data Processing ─────────────────────────────────
    def _process_serial(self):
        if not self._connected or not self.serial_conn:
            if self._session_sec % 5 == 0:
                self._connect_serial()
            return

        try:
            new_ecg: List[float] = []
            new_ppg: List[float] = []

            if self.serial_conn.in_waiting > 0:
                self.raw_serial_buffer += self.serial_conn.read(self.serial_conn.in_waiting)

            if b'\n' in self.raw_serial_buffer:
                lines = self.raw_serial_buffer.split(b'\n')
                self.raw_serial_buffer = lines.pop()   

                for line in lines:
                    try:
                        decoded = line.decode('utf-8').strip()
                        if ',' in decoded:
                            parts = decoded.split(',')
                            val_e = float(parts[0])
                            val_p = float(parts[1])
                            new_ecg.append(val_e)
                            new_ppg.append(val_p)
                            self.processor.add_sample(val_e, val_p)
                    except (ValueError, IndexError):
                        pass

            if new_ecg:
                n = len(new_ecg)
                if n > DISPLAY_SAMPLES:
                    new_ecg = new_ecg[-DISPLAY_SAMPLES:]
                    new_ppg = new_ppg[-DISPLAY_SAMPLES:]
                    n = DISPLAY_SAMPLES

                if n < DISPLAY_SAMPLES:
                    self.data_ecg[:-n] = self.data_ecg[n:]
                    self.data_ppg[:-n] = self.data_ppg[n:]
                    self.data_ecg[-n:] = new_ecg
                    self.data_ppg[-n:] = new_ppg
                else:
                    self.data_ecg[:] = new_ecg
                    self.data_ppg[:] = new_ppg

                self._ecg_plot._curve.setData(self.data_ecg)
                self._ppg_plot._curve.setData(self.data_ppg)

                instant_peaks = detect_r_peaks_fast(self.data_ecg, fs=FS)
                self._ecg_plot.set_raw_peaks(instant_peaks)

        except serial.SerialException as e:
            self._connected = False
            self._sb_left.setText(f"Serial Error: {e}")
            if hasattr(self, 'serial_conn') and self.serial_conn:
                self.serial_conn.close()
                self.serial_conn = None

    # ── Metrics Polling ────────────────────────────────────────
    def _poll_metrics(self):
        result = self.processor.tick()
        if result is None:
            return   
        self._last_metrics_result = result
        self._update_slow_metrics(result)

    def _update_slow_metrics(self, res):
        self._n_updates += 1

        sqi = res.quality_score
        self._sqi_bar.set_value(sqi)
        self._ecg_sqi_text.setText(f"SQI {sqi*100:.0f}%")

        valid_beats  = [b for b in res.beats if b.beat_class == 1]
        beat_rr_vals = [b.rr_ms for b in valid_beats if 300 <= b.rr_ms <= 2000]
        instant_hr: Optional[float] = None
        instant_rr: Optional[float] = None
        if len(beat_rr_vals) >= 2:
            instant_rr = float(np.mean(beat_rr_vals))
            instant_hr = 60000.0 / instant_rr

        hrv_ready    = (res.stress is not None and res.stress.hrv is not None and res.stress.hrv.n_beats >= MIN_BEATS)
        stress_ready = hrv_ready and sqi >= 0.35

        if hrv_ready:
            hrv   = res.stress.hrv
            self._t_hr.set_value(hrv.mean_hr_bpm, "{:.0f}", P["ppg"])
            self._t_rmssd.set_value(hrv.rmssd_ms,  "{:.1f}", P["calm"])
            self._t_sdnn.set_value(hrv.sdnn_ms,   "{:.1f}", P["violet"])
            self._t_rr.set_value(hrv.mean_rr_ms,  "{:.0f}", P["mild"])
            self._ecg_hr_badge.setText(f"{hrv.mean_hr_bpm:.0f} bpm")
            
            smoothed_stress = self.processor.smoothed_stress
            current_stress = smoothed_stress if smoothed_stress is not None else (res.stress.stress_score * 100)
            self._aura_widget.update_intensities(current_stress, hrv.rmssd_ms)

            # Update calibration page live RMSSD
            self._calib_rmssd.setText(f"{hrv.rmssd_ms:.1f}")
            if hrv.rmssd_ms > 30:
                self._calib_status.setText("🌿  Your body is relaxed — great baseline conditions")
                self._calib_rmssd.setStyleSheet(f"color:{P['calm']}; font-size:48px; font-weight:700; background:transparent; border:none;")
            elif hrv.rmssd_ms > 15:
                self._calib_status.setText("🌸  Moderate relaxation — try deeper breathing")
                self._calib_rmssd.setStyleSheet(f"color:{P['mild']}; font-size:48px; font-weight:700; background:transparent; border:none;")
            else:
                self._calib_status.setText("💗  Try to relax more — your rhythm is still settling")
                self._calib_rmssd.setStyleSheet(f"color:{P['high']}; font-size:48px; font-weight:700; background:transparent; border:none;")

        elif instant_hr is not None:
            self._t_hr.set_value(instant_hr, "{:.0f}", P["ppg"])
            self._t_rr.set_value(instant_rr, "{:.0f}", P["mild"])
            self._t_rmssd.set_value(None)   
            self._t_sdnn.set_value(None)
            n_rr_buf = (len(self.processor.monitor.stress_analyser._rr_buffer) if self.processor.monitor else 0)
            self._ecg_hr_badge.setText(f"{instant_hr:.0f} bpm · {n_rr_buf}/10 beats")
            self._aura_widget.update_intensities(0, 50) 
        else:
            hist_len = len(self.processor._ecg_history)
            for t in [self._t_hr, self._t_rmssd, self._t_sdnn, self._t_rr]:
                t.set_value(None)
            self._ecg_hr_badge.setText(f"gathering data…")
            self._aura_widget.update_intensities(0, 0) 

        _state_map = {
            'relaxed'    : 'Calm',
            'mild_stress': 'Mild Stress',
            'high_stress': 'High Stress',
            'unreliable' : 'Poor Signal',
        }
        
        if stress_ready:
            smoothed       = self.processor.smoothed_stress
            raw_pct        = res.stress.stress_score * 100.0
            display_stress = smoothed if smoothed is not None else raw_pct
            state_raw      = res.stress.state
            state_label    = _state_map.get(state_raw, state_raw.title())

            self._stress_gauge.set_value(display_stress)
            col = (P["calm"] if display_stress < 35 else P["mild"] if display_stress < 65 else P["high"])
            self._stress_prog.setValue(int(display_stress))
            self._stress_prog.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border: none; border-radius: 2px; }} QProgressBar::chunk {{ background: {col}; border-radius: 2px; }}")
            self._state_badge.set_state(state_label)

            # Store stress history for pregnancy page
            self.processor._stress_history.append(display_stress)

            # ── Recovery Score Computation ──
            hrv = res.stress.hrv
            baseline_obj = self.processor.monitor.baseline if self.processor.monitor else None
            if baseline_obj and hrv and hrv.n_beats >= MIN_BEATS:
                hrv_window = {
                    'rmssd': hrv.rmssd_ms,
                    'sdnn':  hrv.sdnn_ms,
                    'rr':    hrv.mean_rr_ms,
                    'hr':    hrv.mean_hr_bpm,
                    'valid_beats': hrv.n_beats,
                }
                bl_dict = {
                    'rmssd': baseline_obj.rmssd_baseline,
                    'hr':    baseline_obj.hr_baseline,
                }
                
                # Extract recent median PTT for vascular stability checks
                ptt_vals_for_rec = [b.ptt_ms for b in res.beats if 80 <= b.ptt_ms <= 400]
                median_ptt = float(np.median(ptt_vals_for_rec)) if ptt_vals_for_rec else None

                rec_result = compute_recovery(
                    hrv_window, bl_dict, sqi,
                    ptt=median_ptt,
                    prev_state=self.processor._recovery_state
                )
                self.processor._recovery_state = rec_result['state']
                self.processor._last_recovery  = rec_result

                rec_score = rec_result['recovery_score']
                rec_trend = rec_result['trend']
                rec_conf  = rec_result['confidence']

                self._recovery_gauge.set_value(rec_score, rec_trend, rec_conf)
                rec_col = (P["rec_low"] if rec_score < 30 else P["rec_mid"] if rec_score < 70 else P["rec_hi"])
                self._recovery_prog.setValue(int(rec_score))
                self._recovery_prog.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border: none; border-radius: 2px; }} QProgressBar::chunk {{ background: {rec_col}; border-radius: 2px; }}")

                trend_sym = {"increasing": "▲ Improving", "decreasing": "▼ Declining", "stable": "● Steady"}.get(rec_trend, "● Steady")
                zone_label = "Needs rest" if rec_score < 30 else ("Moderate" if rec_score < 70 else "Flourishing")
                self._recovery_trend_lbl.setText(f"Body recovery: {zone_label}  {trend_sym}")
                self._recovery_trend_lbl.setStyleSheet(f"color:{rec_col}; font-size:9px; background:transparent; border:none;")

                # Store recovery history for pregnancy page
                self.processor._recovery_history.append(rec_score)

                # ── Update Pregnancy Insights Page ──
                self._update_pregnancy_insights(display_stress, rec_score, rec_trend, hrv)
            else:
                self._recovery_gauge.clear()
                self._recovery_trend_lbl.setText("Body recovery: awaiting heart rhythm data")

        elif sqi < 0.35 and sqi > 0:
            self._stress_gauge.clear()
            self._recovery_gauge.clear()
            self._state_badge.set_state("Poor Signal")

        elif instant_hr is not None:
            n_rr_buf = (len(self.processor.monitor.stress_analyser._rr_buffer) if self.processor.monitor else 0)
            self._stress_gauge.clear()
            self._recovery_gauge.clear()
            self._state_badge.set_state(f"Building rhythm {n_rr_buf}/10")
            state_raw = ""

        else:
            self._stress_gauge.clear()
            self._recovery_gauge.clear()
            self._state_badge.set_state("Awaiting data")
            state_raw = ""

        ptt_vals = [b.ptt_ms for b in res.beats if b.ptt_ms > 0 and 80 <= b.ptt_ms <= 400]
        if ptt_vals:
            ptt = float(np.median(ptt_vals))
            self._t_ptt.set_value(ptt, "{:.0f}", P["accent"])
            self._ptt_num.setText(f"{ptt:.0f}")
        else:
            self._t_ptt.set_value(None)
            self._ptt_num.setText("—")

        self._ppg_br_badge.setText("")
        self._t_br.set_value(None)
        self._bl_lbl.setText("Default baseline active")

        state_raw_log = res.stress.state if res.stress else ""
        state_label_log = {'relaxed': 'Calm', 'mild_stress': 'Mild Stress', 'high_stress': 'High Stress'}.get(state_raw_log, "")
        if (state_label_log and state_label_log != self._last_state and state_raw_log not in ('unreliable', '')):
            self._timeline.ingest_timeline([{"time_s" : self._session_sec, "state"  : state_label_log, "stress" : (res.stress.stress_score * 100 if res.stress else 0)}])
            self._last_state = state_label_log

        n_rr_disp = (len(self.processor.monitor.stress_analyser._rr_buffer) if self.processor.monitor else 0)
        self._sb_right.setText(f"updates {self._n_updates}  ·  beats {res.n_valid_beats}  ·  sqi {sqi:.2f}  ·  samples {len(self.processor._ecg_history)}")

    # ── Pregnancy Insights Update ──────────────────────────────
    def _update_pregnancy_insights(self, stress: float, recovery: float, rec_trend: str, hrv):
        # Maternal Stability: high when stress is low and recovery is high
        # Score = 100 - stress_weight + recovery_weight, sigmoid-mapped
        raw_stability = (0.5 * (100.0 - stress) + 0.5 * recovery) 
        ms_score = max(0, min(100, raw_stability))

        ms_col = P["calm"] if ms_score >= 60 else (P["mild"] if ms_score >= 35 else P["high"])
        self._preg_ms_score.setText(f"{ms_score:.0f}")
        self._preg_ms_score.setStyleSheet(f"color:{ms_col}; font-size:48px; font-weight:700; background:transparent; border:none;")
        self._preg_ms_bar.setValue(int(ms_score))
        self._preg_ms_bar.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 3px; border: none; }} QProgressBar::chunk {{ background: {ms_col}; border-radius: 3px; }}")

        if ms_score >= 70:
            self._preg_ms_desc.setText("Your body is in a stable, calm state — wonderful for your baby 🌿")
        elif ms_score >= 45:
            self._preg_ms_desc.setText("Moderate stability — your body is managing well, stay relaxed 🌸")
        else:
            self._preg_ms_desc.setText("Your body is working hard right now — consider resting 💗")

        # Fetal Support: derived from recovery + RMSSD quality
        rmssd_factor = min(1.0, hrv.rmssd_ms / 40.0) if hrv.rmssd_ms > 0 else 0.0
        fs_raw = (0.6 * recovery + 0.4 * rmssd_factor * 100.0)
        fs_score = max(0, min(100, fs_raw))

        fs_col = P["rec_hi"] if fs_score >= 60 else (P["rec_mid"] if fs_score >= 35 else P["rec_low"])
        self._preg_fs_score.setText(f"{fs_score:.0f}")
        self._preg_fs_score.setStyleSheet(f"color:{fs_col}; font-size:48px; font-weight:700; background:transparent; border:none;")
        self._preg_fs_bar.setValue(int(fs_score))
        self._preg_fs_bar.setStyleSheet(f"QProgressBar {{ background: {P['bg3']}; border-radius: 3px; border: none; }} QProgressBar::chunk {{ background: {fs_col}; border-radius: 3px; }}")

        if fs_score >= 70:
            self._preg_fs_desc.setText("Excellent vagal tone and recovery — your body is nourishing beautifully 🌿")
        elif fs_score >= 45:
            self._preg_fs_desc.setText("Good support — heart rhythm balance is adequate 🌸")
        else:
            self._preg_fs_desc.setText("Recovery is low — gentle breathing or rest may help restore balance 💗")

        # Insight message
        if stress < 30 and recovery > 60:
            self._preg_insight_msg.setText("🌿  Your body is deeply relaxed with strong recovery. This is the ideal state for rest and restoration. Your heart rhythm shows excellent parasympathetic tone.")
        elif stress < 50 and recovery > 40:
            self._preg_insight_msg.setText("🌸  Your body is in a balanced state. Emotional load is manageable and recovery is active. Keep your breathing gentle and steady.")
        elif stress > 65:
            self._preg_insight_msg.setText("💗  Elevated emotional load detected. Your body's stress response is active. Consider a 5-minute breathing break — slow, deep breaths through your nose.")
        else:
            self._preg_insight_msg.setText(f"🌸  Your emotional load is {stress:.0f} and body recovery is {recovery:.0f}. Your body is adjusting — stay present and breathe naturally.")

        # Trend text
        stress_hist = list(self.processor._stress_history)
        rec_hist = list(self.processor._recovery_history)
        trend_parts = []
        if len(stress_hist) >= 3:
            s_slope = stress_hist[-1] - stress_hist[0]
            if s_slope > 5:
                trend_parts.append("Emotional load is rising — your body may need a break")
            elif s_slope < -5:
                trend_parts.append("Emotional load is decreasing — you're settling into calm")
            else:
                trend_parts.append("Emotional load is steady")
        if len(rec_hist) >= 3:
            r_slope = rec_hist[-1] - rec_hist[0]
            if r_slope > 3:
                trend_parts.append("Recovery is improving — your body is healing")
            elif r_slope < -3:
                trend_parts.append("Recovery is declining — consider resting")
            else:
                trend_parts.append("Recovery is holding steady")
        self._preg_trend_text.setText("  ·  ".join(trend_parts) if trend_parts else "Gathering trend data…")

    # ── Event Handlers ─────────────────────────────────────────
    def _on_calib_click(self):
        if not self._connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "No connection to device.")
            return
        QtWidgets.QMessageBox.information(self, "Calibration", "Default baselines are active.")

    def _on_clear_timeline(self):
        self._timeline.reset()

    def _tick_session(self):
        if self._connected:
            self._session_sec += 1
        h   = self._session_sec // 3600
        m   = (self._session_sec % 3600) // 60
        sec = self._session_sec % 60
        self._session_lbl.setText(f"{h:02d}:{m:02d}:{sec:02d}")

    def closeEvent(self, ev):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        ev.accept()

# ═══════════════════════════════════════════════════════════════════
#  APPLICATION ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="MaternalGuard Pregnancy Wellness Monitor")
    parser.add_argument("--port", default=SERIAL_PORT)
    args = parser.parse_args()

    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    pg.setConfigOptions(antialias=True, foreground=P["t1"], background=P["bg2"], crashWarning=False)

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")

    # Light palette for Fusion — avoids the RecursionError from dark-palette-on-light-colors
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window,          QtGui.QColor(P["bg0"]))
    pal.setColor(QtGui.QPalette.WindowText,      QtGui.QColor(P["t0"]))
    pal.setColor(QtGui.QPalette.Base,            QtGui.QColor(P["bg2"]))
    pal.setColor(QtGui.QPalette.AlternateBase,   QtGui.QColor(P["bg1"]))
    pal.setColor(QtGui.QPalette.Text,            QtGui.QColor(P["t0"]))
    pal.setColor(QtGui.QPalette.Button,          QtGui.QColor(P["bg3"]))
    pal.setColor(QtGui.QPalette.ButtonText,      QtGui.QColor(P["t0"]))
    pal.setColor(QtGui.QPalette.Highlight,       QtGui.QColor(P["accent"]))
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    pal.setColor(QtGui.QPalette.ToolTipBase,     QtGui.QColor(P["bg2"]))
    pal.setColor(QtGui.QPalette.ToolTipText,     QtGui.QColor(P["t0"]))
    # Critical: set Light/Midlight/Dark/Mid/Shadow to prevent Fusion style recursion
    pal.setColor(QtGui.QPalette.Light,           QtGui.QColor("#ffffff"))
    pal.setColor(QtGui.QPalette.Midlight,        QtGui.QColor(P["bg2"]))
    pal.setColor(QtGui.QPalette.Dark,            QtGui.QColor(P["bg4"]))
    pal.setColor(QtGui.QPalette.Mid,             QtGui.QColor(P["bg3"]))
    pal.setColor(QtGui.QPalette.Shadow,          QtGui.QColor(P["border2"]))
    app.setPalette(pal)

    win = MainWindow(args.port)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
