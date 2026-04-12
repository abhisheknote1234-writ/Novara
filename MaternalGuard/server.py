"""
MaternalGuard - Maternal Health Physiological Monitoring Backend
================================================================
Flask + Flask-SocketIO server receiving UDP packets from ESP32
(AD8232 ECG + MAX30102 PPG via ADS1115) and streaming processed
physiological metrics to the dashboard in real time.

Configuration:
  All settings live in pipeline_config.py — edit that file to toggle
  pipeline mode, ML models, dashboard panels, and hardware params.

UDP Packet format (JSON):
  {"ecg": float, "ppg": float, "timestamp": ms}

Install:
  pip install flask flask-socketio eventlet numpy scipy

Run:
  python server.py

UDP simulator (for testing without hardware):
  python server.py --simulate
"""

# ── Eventlet monkey-patch MUST come before all other imports ───────
# Selective patch: only os, socket, time. Avoids patching 'thread' which
# deadlocks numpy/scipy C-extensions on Windows.
import eventlet
eventlet.monkey_patch(os=True, socket=True, time=True, thread=False)

import csv
import json
import math
import os
import socket
import threading
import time
import argparse
from collections import deque
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import butter, sosfiltfilt, sosfilt, find_peaks, welch

from flask import Flask, jsonify, render_template, send_from_directory
from flask_socketio import SocketIO, emit

# ── Pipeline Configuration (central control panel) ────────────────
import pipeline_config as CFG

UDP_IP   = CFG.UDP_IP
UDP_PORT = CFG.UDP_PORT
FS       = CFG.SignalParams.SAMPLING_RATE
WEB_PORT = CFG.WEB_PORT
_METRICS = CFG.get_enabled_metrics()

# ── Flask + SocketIO ───────────────────────────────────────────────
app = Flask(__name__, static_folder="static", template_folder=".")
app.config["SECRET_KEY"] = CFG.SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ═══════════════════════════════════════════════════════════════════
#  SIGNAL PROCESSING PIPELINE
# ═══════════════════════════════════════════════════════════════════

class SignalProcessor:
    """
    Real-time signal processing for maternal ECG + PPG.
    All filters use SOS form for numerical stability.
    """

    def __init__(self, fs: int = 250):
        self.fs = fs

        # ECG filters: bandpass 0.5-40 Hz + 50 Hz notch
        nyq = fs / 2.0
        self.ecg_bp_sos  = butter(4, [0.5/nyq, 40.0/nyq], btype='band', output='sos')
        from scipy.signal import iirnotch, tf2sos
        b_n, a_n = iirnotch(50.0, 30.0, fs)
        self.ecg_notch_sos = tf2sos(b_n, a_n)

        # PPG filters: bandpass 0.5-4 Hz (pulsatile), 0.1-0.5 Hz (breathing)
        self.ppg_bp_sos     = butter(4, [0.5/nyq, 4.0/nyq],   btype='band', output='sos')
        self.ppg_breath_sos = butter(2, [0.1/nyq, 0.5/nyq],   btype='band', output='sos')

        # Rolling buffers (5 s = 1250 samples)
        buf = 1250
        self.ecg_raw   = deque(maxlen=buf)
        self.ppg_raw   = deque(maxlen=buf)
        self.ts_buf    = deque(maxlen=buf)

        # Longer buffers for HRV (60 s)
        self.rr_buffer  = deque(maxlen=200)    # RR intervals (ms)
        self.ppg_peaks  = deque(maxlen=200)
        self.ecg_peaks  = deque(maxlen=200)    # sample indices

        # PTT
        self.ptt_buffer = deque(maxlen=30)

        # Breathing
        self.breath_buffer = deque(maxlen=500)

        # Adaptive state
        self._last_r       = -1
        self._last_ppg_pk  = -1
        self._rr_avg       = float(fs * 0.857)  # 70 bpm prior
        self._amp_avg      = 1.0
        self._sqi          = 0.7

        # Baseline (calibration)
        self.baseline_hr    = 75.0
        self.baseline_rmssd = 35.0
        self.baseline_set   = False
        self._calib_rr      = []
        self._calib_valid_count = 0   # SQI-gated RR count

        # Stress EMA
        self._stress_ema   = 30.0
        self._state_timer  = {}   # for >2-min high stress alert
        self._high_stress_since: Optional[float] = None

        # Session
        self.session_start = time.time()
        self.timeline      = []   # list of (time_s, state, label)
        self._last_state   = None

        # Contraction detection (PPG amplitude rolling min)
        self._ppg_amp_history = deque(maxlen=600)  # 10 min @ 1/s
        self._contraction_count = 0

        # Sample counter
        self._n = 0

        # Stream chunks (emitted to frontend dynamically)
        self._chunk_ecg = []
        self._chunk_ppg = []

        # ── Extension buffers (freq HRV, SpO2, PTT trend) ────────
        self.ppg_red       = deque(maxlen=1250)  # optional Red channel for SpO2
        self._ptt_history  = deque(maxlen=10)    # last 10 PTT values for trend

        # ── CSV Data Logging ─────────────────────────────────────
        self.log_file = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.log_headers_written = False
        self.log_buffer = []    # batch writes every 5s
        self._log_counter = 0

    # ── Filter helpers ─────────────────────────────────────────────

    def _filt(self, sig, sos):
        """Offline zero-phase filter on a numpy array."""
        if len(sig) < 30:
            return sig.copy()
        return sosfiltfilt(sos, sig)

    # ── ECG Pan-Tompkins R-peak detection ─────────────────────────

    def _detect_rpeaks(self, ecg_clean: np.ndarray) -> np.ndarray:
        """
        Simplified Pan-Tompkins on last 5 s of bandpass ECG.
        Returns sample indices of R-peaks within this window.
        """
        diff = np.diff(ecg_clean, prepend=0)
        sq   = diff ** 2
        win  = int(0.15 * self.fs)
        mwi  = np.convolve(sq, np.ones(win)/win, mode='same')
        dist = int(0.30 * self.fs)
        peaks, _ = find_peaks(mwi, distance=dist, height=np.mean(mwi)*0.5)
        return peaks

    # ── PPG systolic peak detection ───────────────────────────────

    def _detect_ppg_peaks(self, ppg_clean: np.ndarray) -> np.ndarray:
        dist = int(0.35 * self.fs)
        prom = max(np.ptp(ppg_clean) * 0.1, 1e-6)
        peaks, _ = find_peaks(ppg_clean, distance=dist, prominence=prom)
        return peaks

    # ── HRV metrics ───────────────────────────────────────────────

    def _hrv_metrics(self):
        rr = np.array(list(self.rr_buffer), dtype=float)
        rr = rr[(rr >= 300) & (rr <= 2000)]
        if len(rr) < 3:
            return None
        succ = np.diff(rr)
        pnn50 = float(100.0 * np.sum(np.abs(succ) > 50.0) / len(succ)) if len(succ) > 0 else 0.0
        return {
            "rmssd":   float(np.sqrt(np.mean(succ**2))),
            "sdnn":    float(np.std(rr, ddof=1)),
            "mean_rr": float(np.mean(rr)),
            "n_beats": len(rr),
            "pnn50":   round(pnn50, 2),
        }

    # ── Frequency-domain HRV (LF/HF) ─────────────────────────────

    def _freq_hrv(self) -> Dict[str, float]:
        """
        Compute LF / HF power and derived ratios from the RR interval buffer.
        """
        _ZERO = {"lf": 0.0, "hf": 0.0, "lf_hf": 0.0, "lf_nu": 0.0, "hf_nu": 0.0}

        rr = np.array(self.rr_buffer, dtype=np.float64)
        if len(rr) < 20:
            return _ZERO

        rr = rr[(rr >= 300) & (rr <= 2000)]
        if len(rr) < 20:
            return _ZERO

        rr_s   = rr / 1000.0
        t_cum  = np.cumsum(rr_s)
        t_cum -= t_cum[0]

        fs_resamp = 4.0
        dt        = 1.0 / fs_resamp
        t_uniform = np.arange(0.0, t_cum[-1], dt)

        if len(t_uniform) < 8:
            return _ZERO

        interp_fn = interp1d(t_cum, rr, kind="linear", bounds_error=False,
                             fill_value=(rr[0], rr[-1]))
        rr_uniform  = interp_fn(t_uniform)
        rr_uniform -= rr_uniform.mean()

        nperseg = min(256, len(rr_uniform))
        freqs, psd = welch(
            rr_uniform, fs=fs_resamp, window="hann",
            nperseg=nperseg, noverlap=nperseg // 2, scaling="density",
        )

        _trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz

        lf_mask = (freqs >= 0.04) & (freqs <= 0.15)
        hf_mask = (freqs >= 0.15) & (freqs <= 0.40)

        lf = float(_trapz(psd[lf_mask], freqs[lf_mask])) if lf_mask.sum() > 1 else 0.0
        hf = float(_trapz(psd[hf_mask], freqs[hf_mask])) if hf_mask.sum() > 1 else 0.0

        total = lf + hf + 1e-9
        lf_hf = lf / (hf + 1e-9)
        lf_nu = (lf / total) * 100.0
        hf_nu = (hf / total) * 100.0

        return {
            "lf":    round(lf, 4),
            "hf":    round(hf, 4),
            "lf_hf": round(lf_hf, 4),
            "lf_nu": round(lf_nu, 2),
            "hf_nu": round(hf_nu, 2),
        }

    # ── PPG Morphology Features ───────────────────────────────────

    def _ppg_morphology(self, ppg_clean: np.ndarray, ppg_peaks: np.ndarray) -> Dict[str, float]:
        """
        Per-beat PPG morphology features; returns median values across all
        peaks detected in the current window.
        """
        _ZERO = {
            "spd_ms": 0.0, "dpd_ms": 0.0, "pwd_ms": 0.0,
            "spd_pwd_ratio": 0.0, "crest_time_ms": 0.0,
            "aug_index": 0.0, "pulse_amplitude": 0.0,
        }

        if ppg_peaks is None or len(ppg_peaks) < 1 or len(ppg_clean) < 4:
            return _ZERO

        n  = len(ppg_clean)
        fs = float(self.fs)

        spds, dpds, pwds, spd_pwd_ratios = [], [], [], []
        ais, pulse_amps = [], []

        for i, pk in enumerate(ppg_peaks):
            pk = int(pk)
            if pk <= 0 or pk >= n - 1:
                continue

            search_start = max(0, pk - int(0.5 * fs))
            foot_idx     = search_start + int(np.argmin(ppg_clean[search_start:pk]))
            foot_val     = ppg_clean[foot_idx]

            if i + 1 < len(ppg_peaks):
                next_peak = int(ppg_peaks[i + 1])
            else:
                next_peak = min(n - 1, pk + int(0.5 * fs))

            next_search_end = min(next_peak, pk + int(0.8 * fs))
            if pk + 1 >= next_search_end:
                continue
            next_foot_idx = pk + int(np.argmin(ppg_clean[pk:next_search_end]))
            next_foot_val = ppg_clean[next_foot_idx]

            if next_foot_idx <= pk:
                continue

            spd_samples = pk - foot_idx
            dpd_samples = next_foot_idx - pk

            if spd_samples <= 0 or dpd_samples <= 0:
                continue

            spd_ms  = spd_samples / fs * 1000.0
            dpd_ms  = dpd_samples / fs * 1000.0
            pwd_ms  = spd_ms + dpd_ms
            ratio   = spd_ms / (pwd_ms + 1e-9)
            p_amp   = float(ppg_clean[pk]) - float(foot_val)

            spds.append(spd_ms)
            dpds.append(dpd_ms)
            pwds.append(pwd_ms)
            spd_pwd_ratios.append(ratio)
            pulse_amps.append(p_amp)

            diastolic_window = ppg_clean[pk:next_foot_idx]
            if len(diastolic_window) > 4:
                local_peaks, _ = find_peaks(diastolic_window, distance=max(1, int(0.05 * fs)))
                if len(local_peaks) > 0:
                    best = local_peaks[np.argmax(diastolic_window[local_peaks])]
                    p2   = float(diastolic_window[best]) - float(foot_val)
                    p1   = max(p_amp, 1e-9)
                    ai   = (p2 - p1) / p1 * 100.0
                    ais.append(ai)
                else:
                    ais.append(0.0)
            else:
                ais.append(0.0)

        if not spds:
            return _ZERO

        return {
            "spd_ms":          round(float(np.median(spds)), 2),
            "dpd_ms":          round(float(np.median(dpds)), 2),
            "pwd_ms":          round(float(np.median(pwds)), 2),
            "spd_pwd_ratio":   round(float(np.median(spd_pwd_ratios)), 4),
            "crest_time_ms":   round(float(np.median(spds)), 2),
            "aug_index":       round(float(np.median(ais)), 2),
            "pulse_amplitude": round(float(np.median(pulse_amps)), 4),
        }

    # ── SpO2 / Perfusion Index ────────────────────────────────────

    def _spo2(self) -> Dict[str, float]:
        """
        Perfusion Index from IR PPG, optionally SpO2 when Red channel present.
        """
        _ZERO = {"pi": 0.0}
        window_samples = int(5 * self.fs)

        ir_raw = np.array(self.ppg_raw, dtype=np.float64)
        if len(ir_raw) < window_samples // 2:
            return _ZERO

        ir_win = ir_raw[-window_samples:]

        try:
            nyq = self.fs / 2.0
            sos = butter(4, [0.5 / nyq, 10.0 / nyq], btype="band", output="sos")
            padlen = 3 * sos.shape[0] * 2
            if len(ir_win) > padlen:
                ir_filtered = sosfiltfilt(sos, ir_win)
            else:
                ir_filtered = ir_win - ir_win.mean()
        except Exception:
            ir_filtered = ir_win - ir_win.mean()

        dc_ir = float(np.mean(np.abs(ir_win))) + 1e-9
        ac_ir = float(np.ptp(ir_filtered))

        pi = (ac_ir / dc_ir) * 100.0
        pi = float(np.clip(pi, 0.0, 100.0))

        result = {"pi": round(pi, 3)}

        red_raw = np.array(self.ppg_red, dtype=np.float64)
        if len(red_raw) >= window_samples // 2:
            red_win = red_raw[-window_samples:]
            try:
                if len(red_win) > padlen:
                    red_filtered = sosfiltfilt(sos, red_win)
                else:
                    red_filtered = red_win - red_win.mean()
            except Exception:
                red_filtered = red_win - red_win.mean()

            dc_red = float(np.mean(np.abs(red_win))) + 1e-9
            ac_red = float(np.ptp(red_filtered))

            if ac_ir > 1e-6 and dc_ir > 1e-6:
                R    = (ac_red / dc_red) / (ac_ir / dc_ir)
                spo2 = 110.0 - 25.0 * R
                spo2 = float(np.clip(spo2, 85.0, 100.0))
                result["spo2"] = round(spo2, 1)

        return result

    # ── PTT → BP Label + Trend ────────────────────────────────────

    def _ptt_bp_label(self, ptt_ms: float) -> Tuple[str, str]:
        """
        Map a PTT value to a clinical BP label and a short trend string.
        """
        if ptt_ms <= 0:
            label = "—"
        elif ptt_ms > 250:
            label = "Normal BP"
        elif ptt_ms > 200:
            label = "Slightly Elevated"
        elif ptt_ms > 150:
            label = "Elevated"
        else:
            label = "High — Check BP"

        if ptt_ms > 0:
            self._ptt_history.append(ptt_ms)

        if len(self._ptt_history) < 2 or ptt_ms <= 0:
            trend = "→ Stable"
        else:
            historical_mean = float(np.mean(list(self._ptt_history)[:-1]))
            delta = ptt_ms - historical_mean
            if delta < -15.0:
                trend = "↑ Rising"
            elif delta > 15.0:
                trend = "↓ Falling"
            else:
                trend = "→ Stable"

        return label, trend

    # ── Breathing rate from PPG low-frequency baseline ────────────

    def _breathing_rate(self):
        if len(self.ppg_raw) < self.fs * 4:
            return 0.0
        sig = np.array(list(self.ppg_raw))[-self.fs*4:]
        breath = self._filt(sig, self.ppg_breath_sos)
        # Peak interval → rate
        pks, _ = find_peaks(breath, distance=int(self.fs * 1.5))
        if len(pks) < 2:
            return 0.0
        ibi_s = np.diff(pks) / self.fs
        rate  = float(60.0 / np.mean(ibi_s))
        return float(np.clip(rate, 6, 30))

    # ── Signal quality index ──────────────────────────────────────

    def _compute_sqi(self, ecg_clean: np.ndarray, r_peaks: np.ndarray) -> float:
        if len(ecg_clean) < 50:
            return 0.5
        peak_p = float(np.percentile(np.abs(ecg_clean), 95))
        noise  = float(np.percentile(np.abs(ecg_clean), 10)) + 1e-9
        snr    = np.clip((peak_p / noise - 1) / 14.0, 0, 1)
        rr_reg = 1.0
        if len(self.rr_buffer) >= 3:
            rr = np.array(list(self.rr_buffer))
            cv = np.std(rr) / (np.mean(rr) + 1e-9)
            rr_reg = max(0, 1 - cv / 0.4)
        return float(0.5*snr + 0.5*rr_reg)

    # ── Stress score ──────────────────────────────────────────────

    def _stress_score(self, hrv: dict) -> float:
        """
        Weighted stress score 0-100 from HRV deviations from personal baseline.
        """
        rmssd = hrv["rmssd"]
        sdnn  = hrv["sdnn"]
        hr    = 60000.0 / max(hrv["mean_rr"], 1)

        if rmssd < 1:
            return self._stress_ema

        # Relative to baseline
        rmssd_dev  = np.clip((1 - rmssd / max(self.baseline_rmssd, 1)) / 0.8, 0, 1)
        hr_dev     = np.clip((hr - self.baseline_hr) / (self.baseline_hr * 0.5), 0, 1)
        sdnn_dev   = np.clip((1 - sdnn / max(self.baseline_rmssd * 1.3, 1)) / 0.8, 0, 1)

        raw = float(0.45 * rmssd_dev + 0.35 * hr_dev + 0.20 * sdnn_dev) * 100
        raw = np.clip(raw, 0, 100)

        # EMA smoothing
        alpha = 0.15
        self._stress_ema = alpha * raw + (1 - alpha) * self._stress_ema
        return float(self._stress_ema)

    # ── Autonomic state ───────────────────────────────────────────

    def _autonomic_state(self, stress: float, rmssd: float) -> str:
        if self._sqi < 0.35:
            return "Poor Signal"
        if stress < 25 and rmssd > self.baseline_rmssd * 0.8:
            return "Calm"
        if stress < 40:
            return "Relaxed"
        if stress < 60:
            return "Mild Stress"
        if stress < 75:
            return "High Stress"
        if rmssd < self.baseline_rmssd * 0.4:
            return "Fatigued"
        return "Recovery"

    # ── Fetal wellbeing (maternal HRV coherence proxy) ───────────

    def _fetal_score(self, hrv: dict) -> float:
        """
        Proxy: maternal HRV coherence normalised 0-100.
        High RMSSD + stable RR + good SQI → better fetal oxygenation proxy.
        """
        rmssd_score = np.clip(hrv["rmssd"] / max(self.baseline_rmssd * 1.5, 1), 0, 1)
        sqi_score   = self._sqi
        return float(np.clip((0.6*rmssd_score + 0.4*sqi_score) * 100, 0, 100))

    # ── Contraction pattern (PPG amplitude periodicity) ───────────

    def _contraction_update(self, ppg_clean: np.ndarray):
        """
        Detect periodic drops in PPG amplitude as uterine contraction proxy.
        Appends to amplitude history; checks for >20% drop lasting >20s.
        """
        if len(ppg_clean) < 10:
            return
        amp = float(np.ptp(ppg_clean[-self.fs:]) if len(ppg_clean) >= self.fs else np.ptp(ppg_clean))
        self._ppg_amp_history.append(amp)

    def _contraction_pattern(self):
        hist = list(self._ppg_amp_history)
        if len(hist) < 30:
            return {"detected": False, "count": 0, "last_duration_s": 0}
        arr = np.array(hist, dtype=float)
        baseline = np.percentile(arr, 75)
        low_mask = arr < baseline * 0.70
        # Count runs of low amplitude (>= 20 consecutive seconds)
        count = 0
        in_run = False
        run_len = 0
        last_dur = 0
        for v in low_mask:
            if v:
                in_run = True; run_len += 1
            else:
                if in_run and run_len >= 20:
                    count += 1; last_dur = run_len
                in_run = False; run_len = 0
        return {"detected": count > 0, "count": count, "last_duration_s": last_dur}

    # ── Preeclampsia Risk Flag ────────────────────────────────────

    def _pe_risk(self, hrv: dict, freq_hrv: dict, ppg_morph: dict, ptt_ms: float) -> dict:
        """
        Rule-based preeclampsia risk scoring using published clinical thresholds.
        Returns risk level, score, color, action text, and individual factor flags.
        """
        if not self.baseline_set or ptt_ms <= 0:
            return {
                "level": "Awaiting baseline",
                "score": 0,
                "color": "#95a5a6",
                "action": "Complete calibration first",
                "factors": [False, False, False, False, False, False],
            }

        score = 0
        factors = [False] * 6  # AI, LF/HF, PTT, RMSSD, HR, SPD

        # Factor 0: Augmentation Index > 15 → +2
        if ppg_morph.get("aug_index", 0) > 15:
            score += 2
            factors[0] = True

        # Factor 1: LF/HF > 2.5 → +2
        if freq_hrv.get("lf_hf", 0) > 2.5:
            score += 2
            factors[1] = True

        # Factor 2: PTT < 180 and PTT > 0 → +2
        if ptt_ms < 180 and ptt_ms > 0:
            score += 2
            factors[2] = True

        # Factor 3: RMSSD < 20 → +1
        if hrv.get("rmssd", 999) < 20:
            score += 1
            factors[3] = True

        # Factor 4: HR > 100 (derived from mean_rr) → +1
        mean_rr = hrv.get("mean_rr", 800)
        if mean_rr > 0:
            hr_derived = 60000.0 / mean_rr
            if hr_derived > 100:
                score += 1
                factors[4] = True

        # Factor 5: SPD/PWD ratio > 0.40 → +1
        if ppg_morph.get("spd_pwd_ratio", 0) > 0.40:
            score += 1
            factors[5] = True

        # Map score to risk level
        if score <= 1:
            level  = "Low"
            color  = "#2ecc71"
            action = "Normal monitoring"
        elif score <= 3:
            level  = "Moderate"
            color  = "#f39c12"
            action = "Increased monitoring recommended"
        elif score <= 5:
            level  = "High"
            color  = "#e74c3c"
            action = "Clinical review advised"
        else:
            level  = "Critical"
            color  = "#8e44ad"
            action = "Immediate clinical intervention"

        return {
            "level":   level,
            "score":   score,
            "color":   color,
            "action":  action,
            "factors": factors,
        }

    # ── CSV Data Logging ──────────────────────────────────────────

    def _log_sample(self, payload: dict):
        """
        Flattens the payload dict and appends to log buffer.
        Every 250 calls (~5s at 50ms updates), writes buffer to CSV.
        """
        flat = {}
        for k, v in payload.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, (list, np.ndarray)):
                        continue  # skip arrays
                    flat[f"{k}_{k2}"] = v2
            elif isinstance(v, (list, np.ndarray)):
                continue  # skip waveform arrays
            else:
                flat[k] = v

        flat["log_timestamp"] = datetime.now().isoformat()
        self.log_buffer.append(flat)
        self._log_counter += 1

        if self._log_counter % 250 == 0 and len(self.log_buffer) > 0:
            self._flush_log()

    def _flush_log(self):
        """Write buffered rows to CSV and clear the buffer."""
        if len(self.log_buffer) == 0:
            return
        try:
            mode = "a" if self.log_headers_written else "w"
            with open(self.log_file, mode, newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.log_buffer[0].keys()),
                                        extrasaction="ignore")
                if not self.log_headers_written:
                    writer.writeheader()
                    self.log_headers_written = True
                writer.writerows(self.log_buffer)
            self.log_buffer.clear()
        except Exception as e:
            print(f"[LOG] CSV write error: {e}")

    # ── Main update (called per incoming sample) ──────────────────

    def add_sample(self, ecg_val: float, ppg_val: float, ts_ms: float, ppg_red_val: float = None):
        self.ecg_raw.append(ecg_val)
        self.ppg_raw.append(ppg_val)
        self.ts_buf.append(ts_ms)
        self._n += 1

        self._chunk_ecg.append(ecg_val)
        self._chunk_ppg.append(ppg_val)

        # Store Red channel if present
        if ppg_red_val is not None:
            self.ppg_red.append(ppg_red_val)

        # Append 1 sample/sec amplitude to contraction history
        if self._n % self.fs == 0:
            ppg_arr = np.array(list(self.ppg_raw))
            ppg_clean = self._filt(ppg_arr, self.ppg_bp_sos)
            self._contraction_update(ppg_clean)

        # Process when minimum chunk size is reached
        if len(self._chunk_ecg) < 10:
            return None

        # ── ECG processing ───────────────────────────────────────
        ecg_arr   = np.array(list(self.ecg_raw))
        ecg_notch = self._filt(ecg_arr, self.ecg_notch_sos)
        ecg_clean = self._filt(ecg_notch, self.ecg_bp_sos)

        r_peaks   = self._detect_rpeaks(ecg_clean)

        # Update RR buffer from new peaks
        for pk in r_peaks:
            abs_pk = self._n - len(ecg_arr) + pk
            if self._last_r >= 0:
                rr = (abs_pk - self._last_r) / self.fs * 1000.0
                if 300 <= rr <= 2000:
                    self.rr_buffer.append(rr)
                    self._rr_avg = 0.9*self._rr_avg + 0.1*(rr * self.fs / 1000)
            self._last_r = abs_pk

        self._sqi = self._compute_sqi(ecg_clean, r_peaks)

        # ── PPG processing ───────────────────────────────────────
        ppg_arr   = np.array(list(self.ppg_raw))
        ppg_clean = self._filt(ppg_arr, self.ppg_bp_sos)
        ppg_peaks = self._detect_ppg_peaks(ppg_clean)

        # PTT: time from ECG R-peak to next PPG peak
        if len(r_peaks) > 0 and len(ppg_peaks) > 0:
            r_abs = r_peaks[-1]
            future_ppg = ppg_peaks[ppg_peaks > r_abs]
            if len(future_ppg) > 0:
                ptt_s = float(future_ppg[0] - r_abs) / self.fs * 1000
                if 80 <= ptt_s <= 400:
                    self.ptt_buffer.append(ptt_s)

        # ── Metrics ──────────────────────────────────────────────
        hrv        = self._hrv_metrics()
        stress     = None
        state      = "Awaiting data"
        fetal      = None
        hr         = 0.0

        if hrv is not None:
            stress     = self._stress_score(hrv)
            state      = self._autonomic_state(stress, hrv["rmssd"])
            fetal      = self._fetal_score(hrv)
            hr         = float(60000.0 / max(hrv["mean_rr"], 1)) if hrv["mean_rr"] > 0 else 0.0

        breath     = self._breathing_rate()
        ptt_median = float(np.median(list(self.ptt_buffer))) if len(self.ptt_buffer) >= 3 else 0.0
        contraction = self._contraction_pattern()

        # ── Extension metrics ────────────────────────────────────
        freq_hrv     = self._freq_hrv()
        ppg_morph    = self._ppg_morphology(ppg_clean, ppg_peaks)
        spo2_data    = self._spo2()
        ptt_label, ptt_trend = self._ptt_bp_label(ptt_median)
        pe_risk      = self._pe_risk(hrv if hrv else {}, freq_hrv, ppg_morph, ptt_median)

        # ── Timeline state transitions ────────────────────────────
        if state != self._last_state and state not in ("Poor Signal", "Awaiting data"):
            elapsed = time.time() - self.session_start
            self.timeline.append({
                "time_s": round(elapsed, 1),
                "state":  state,
                "stress": round(stress, 1),
            })
            self._last_state = state

        # ── High-stress alert tracking ────────────────────────────
        alert = False
        if stress is not None and stress > 70:
            if self._high_stress_since is None:
                self._high_stress_since = time.time()
            elif time.time() - self._high_stress_since > 120:
                alert = True
        else:
            self._high_stress_since = None

        # ── Assemble output payload (filtered by pipeline_config) ─
        data_ready = len(self.ecg_raw) >= 250 and len(self.ppg_raw) >= 250

        payload = {
            "sqi":         round(self._sqi, 2),
            "session_sec": round(time.time() - self.session_start, 0),
            "alert":       alert,
            "baseline_set": self.baseline_set,
            "data_ready":  data_ready,
        }

        # Only include metrics that are enabled in pipeline_config
        if _METRICS.get("ecg_wave") and len(self._chunk_ecg) > 0:
            payload["ecg_wave"] = list(self._chunk_ecg)
            payload["r_peaks"]  = r_peaks.tolist()
        if _METRICS.get("ppg_wave") and len(self._chunk_ppg) > 0:
            payload["ppg_wave"] = list(self._chunk_ppg)

        self._chunk_ecg.clear()
        self._chunk_ppg.clear()

        if hrv is not None:
            if _METRICS.get("heart_rate") or _METRICS.get("hrv_time"):
                payload["hrv"] = {
                    "rmssd":   round(hrv["rmssd"], 1),
                    "sdnn":    round(hrv["sdnn"], 1),
                    "mean_rr": round(hrv["mean_rr"], 1),
                    "hr_bpm":  round(hr, 1),
                    "pnn50":   hrv["pnn50"],
                }
            if _METRICS.get("stress"):
                payload["stress"] = round(stress, 1)
                payload["state"]  = state
            if _METRICS.get("fetal"):
                payload["fetal_score"] = round(fetal, 1)

        if _METRICS.get("hrv_freq") and (freq_hrv["lf"] > 0 or freq_hrv["hf"] > 0):
            payload["freq_hrv"] = freq_hrv
        if _METRICS.get("ppg_morphology") and ppg_morph["spd_ms"] > 0:
            payload["ppg_morphology"] = ppg_morph
        if _METRICS.get("spo2") and spo2_data.get("pi", 0) > 0:
            payload["spo2"] = spo2_data
        if _METRICS.get("ptt") and ptt_median > 0:
            payload["ptt_label"] = ptt_label
            payload["ptt_trend"] = ptt_trend
            payload["ptt_ms"]    = round(ptt_median, 1)
        if _METRICS.get("pe_risk") and hrv is not None:
            payload["pe_risk"] = pe_risk
        if _METRICS.get("breathing") and breath > 0:
            payload["breath_rate"] = round(breath, 1)
        if _METRICS.get("contraction"):
            payload["contraction"] = contraction
        if _METRICS.get("timeline"):
            payload["timeline"] = self.timeline[-20:]

        # ── Log to CSV ────────────────────────────────────────────
        if CFG.ENABLE_CSV_LOGGING:
            self._log_sample(payload)

        return payload

    def start_calibration(self):
        """Begin 60-second baseline capture."""
        self._calib_rr          = []
        self._calib_start       = time.time()
        self._calibrating       = True
        self._calib_valid_count = 0
        self._calib_extended    = False
        self._calib_max_time    = 60  # initial 60s, may extend to 90s
        self.baseline_set       = False

    def feed_calibration(self):
        """
        Call each update during calibration window.
        Only accepts RR intervals where SQI > 0.6.
        If fewer than 10 valid RR intervals after 60s, extends by 30s.
        """
        if not getattr(self, "_calibrating", False):
            return False

        # Count valid RR intervals (SQI > 0.6)
        if self._sqi > 0.6:
            self._calib_valid_count += 1

        elapsed = time.time() - self._calib_start

        # Check if initial 60s passed with insufficient data
        if elapsed >= 60 and not self._calib_extended and self._calib_valid_count < 10:
            self._calib_extended = True
            self._calib_max_time = 90  # extend by 30s
            socketio.emit("calibration_extended", {
                "reason": "Poor signal quality",
                "new_duration": 90,
            })
            return False

        if elapsed >= self._calib_max_time:
            # Only use RR intervals collected during good SQI windows
            rr = np.array(list(self.rr_buffer))
            rr = rr[(rr >= 300) & (rr <= 2000)]
            if len(rr) > 10:
                self.baseline_rmssd = float(np.sqrt(np.mean(np.diff(rr)**2)))
                self.baseline_hr    = float(60000 / np.mean(rr))
            self._calibrating = False
            self.baseline_set = True
            return True   # calibration complete
        return False


class AdvancedProcessorWrapper(SignalProcessor):
    def __init__(self, monitor):
        super().__init__(FS)
        self.monitor = monitor
        
    def add_sample(self, ecg_val: float, ppg_val: float, ts_ms: float, ppg_red_val: float = None):
        # 1. Let the core SignalProcessor buffer the incoming data point and generate the base payload
        payload = super().add_sample(ecg_val, ppg_val, ts_ms, ppg_red_val)
        
        # 2. Every 50ms, when a payload is successfully generated, run the Advanced AI pipeline
        if payload is not None:
            ecg_arr = np.array(list(self.ecg_raw))
            ppg_arr = np.array(list(self.ppg_raw))
            
            # Feed the rolling windows into the AI monitor
            try:
                adv_res = self.monitor.update(
                    ecg_segment=ecg_arr,
                    ppg_ir_segment=ppg_arr,
                    timestamp_ms=ts_ms
                )
                
                # 3. Overwrite the simple rule-based metrics with the high-fidelity AI metrics
                if adv_res.stress is not None:
                    payload["stress"] = round(adv_res.stress.stress_score, 1)
                    payload["state"] = adv_res.stress.state
                
                payload["sqi"] = round(adv_res.quality_score, 2)
            except Exception as e:
                import traceback
                print(f"[Advanced AI Error] {e}")
                
        return payload

# Factory: choose simple or advanced pipeline based on config
def _create_processor():
    if CFG.PIPELINE_MODE == "advanced":
        try:
            from physio_monitor import PhysioMonitor
            print("[INIT] Advanced pipeline: PhysioMonitor w/ Adapter")
            monitor = PhysioMonitor(
                fs=FS,
                enable_ecg=CFG.ENABLE_ECG,
                enable_ppg=CFG.ENABLE_PPG,
                verbose=CFG.VERBOSE,
            )
            # Auto-load trained models if available
            if CFG.AUTO_LOAD_MODELS:
                import os
                if os.path.isdir(CFG.MODEL_DIR):
                    try:
                        monitor.load(model_dir=CFG.MODEL_DIR)
                        print(f"[INIT] Loaded models from {CFG.MODEL_DIR}")
                    except Exception as e:
                        print(f"[INIT] Model load skipped: {e}")
            # Wrap the bare monitor so it can accept real-time point-by-point UDP inputs
            return AdvancedProcessorWrapper(monitor)
        except ImportError as e:
            print(f"[INIT] Advanced pipeline unavailable ({e}), falling back to simple")
    # Default: simple pipeline
    print("[INIT] Simple pipeline: SignalProcessor")
    return SignalProcessor(FS)

processor        = _create_processor()
device_connected = False
last_packet_time = 0.0

# ═══════════════════════════════════════════════════════════════════
#  UDP LISTENER
# ═══════════════════════════════════════════════════════════════════

def udp_listener():
    global device_connected, last_packet_time
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    # Increase UDP buffer size to prevent packet drops during heavy processing spikes
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    except OSError:
        pass
        
    sock.settimeout(1.0)
    print(f"[UDP] Listening on {UDP_IP}:{UDP_PORT}")

    pkt_count = 0
    emit_count = 0

    while True:
        try:
            data, addr = sock.recvfrom(256)
            pkt = json.loads(data.decode())
            ecg = float(pkt.get("ecg", 0))
            ppg = float(pkt.get("ppg", 0))
            ts  = float(pkt.get("timestamp", time.time() * 1000))
            ppg_red = float(pkt["ppg_red"]) if "ppg_red" in pkt else None

            device_connected  = True
            last_packet_time  = time.time()
            pkt_count += 1

            # Debug: log first few packets and then periodically
            if pkt_count <= 3 or pkt_count % 1000 == 0:
                print(f"[UDP] pkt #{pkt_count}: ECG={ecg:.0f} PPG={ppg:.0f} | emits={emit_count}")

            result = processor.add_sample(ecg, ppg, ts, ppg_red)
            if result:
                result["device_connected"] = True
                if pkt.get("simulated"):
                    result["simulated"] = True
                socketio.emit("update", result)
                emit_count += 1

                # Check calibration completion
                if processor.feed_calibration():
                    socketio.emit("calibration_done", {
                        "baseline_hr":    round(processor.baseline_hr, 1),
                        "baseline_rmssd": round(processor.baseline_rmssd, 1),
                    })

        except socket.timeout:
            if time.time() - last_packet_time > 3.0 and device_connected:
                device_connected = False
                socketio.emit("update", {"device_connected": False})
        except Exception as e:
            import traceback
            traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════
#  UDP SIMULATOR (for development without hardware)
# ═══════════════════════════════════════════════════════════════════

def udp_simulator():
    """Generates synthetic ECG + PPG and sends as UDP packets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t    = 0.0
    dt   = 1.0 / FS
    hr   = 72.0  # bpm

    print("[SIM] UDP simulator running - sending synthetic ECG+PPG")

    while True:
        rr = 60.0 / hr
        # ECG: synthetic QRS
        bt_mod = t % rr
        ecg  = math.exp(-bt_mod**2 / (2*0.01**2)) - 0.3*math.exp(-bt_mod**2/(2*0.02**2))
        ecg += 0.15*math.exp(-(bt_mod-0.08)**2/(2*0.025**2))  # P-wave
        ecg += 0.3 *math.exp(-(bt_mod-0.20)**2/(2*0.05**2))   # T-wave
        ecg += 0.02*math.sin(2*math.pi*50*t)                   # 50 Hz noise
        ecg += 0.01*(2*math.sin(math.pi*t*0.25))               # baseline wander
        ecg += 0.005*(2*(0.5 - (t*1000 % 1)))                  # random noise approx

        # PPG: broad systolic peak, delayed ~180 ms
        ptt = 0.18
        bt_ppg = (t - ptt) % rr
        ppg  = 0.8*math.exp(-bt_ppg**2/(2*0.05**2))
        ppg += 0.2*math.exp(-(bt_ppg-0.25)**2/(2*0.04**2))   # dicrotic notch
        ppg += 0.02*math.sin(2*math.pi*0.25*t)               # breathing
        ppg += 0.005*math.sin(2*math.pi*(t*1000 % 1))        # noise

        pkt = json.dumps({"ecg": round(ecg*1000, 3), "ppg": round(ppg, 5),
                          "timestamp": round(t*1000, 1), "simulated": True}).encode()
        sock.sendto(pkt, ("127.0.0.1", UDP_PORT))

        # Slowly vary HR to make metrics interesting
        hr = 72 + 8*math.sin(2*math.pi*t/120)

        t  += dt
        time.sleep(dt)


# ═══════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/sessions")
def list_sessions():
    """Return JSON list of all session CSV files in current directory."""
    files = sorted(
        [f for f in os.listdir(".") if f.startswith("session_") and f.endswith(".csv")],
        reverse=True,
    )
    return jsonify(files)

@app.route("/download/<filename>")
def download_session(filename):
    """Serve a session CSV file for download."""
    if not filename.startswith("session_") or not filename.endswith(".csv"):
        return "Invalid filename", 400
    if not os.path.isfile(filename):
        return "File not found", 404
    return send_from_directory(".", filename, as_attachment=True)

@socketio.on("connect")
def on_connect(auth=None):
    b_set = getattr(processor, "baseline_set", False)
    emit("status", {"device_connected": device_connected,
                    "baseline_set": b_set})

@socketio.on("start_calibration")
def on_calibration():
    if hasattr(processor, "start_calibration"):
        processor.start_calibration()
    emit("calibration_started", {})

@socketio.on("disconnect")
def on_disconnect():
    pass


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true",
                        help="Run UDP simulator (no hardware needed)")
    parser.add_argument("--advanced", action="store_true",
                        help="Override config: use advanced pipeline")
    parser.add_argument("--simple", action="store_true",
                        help="Override config: use simple pipeline")
    args = parser.parse_args()

    # CLI overrides for pipeline mode
    if args.advanced:
        CFG.PIPELINE_MODE = "advanced"
        processor = _create_processor()
    elif args.simple:
        CFG.PIPELINE_MODE = "simple"
        processor = _create_processor()

    # Print active configuration
    CFG.print_config()

    # Flush any remaining log data on exit
    if CFG.ENABLE_CSV_LOGGING and hasattr(processor, '_flush_log'):
        import atexit
        atexit.register(lambda: processor._flush_log())

    # Start UDP listener as eventlet green thread (not OS thread)
    # socketio.start_background_task() uses eventlet.spawn() when async_mode="eventlet",
    # ensuring the UDP socket and socketio.emit() cooperate with the event loop.
    socketio.start_background_task(target=udp_listener)

    # Optionally start simulator
    if args.simulate:
        time.sleep(0.5)
        socketio.start_background_task(target=udp_simulator)

    print(f"[WEB] Dashboard -> http://localhost:{WEB_PORT}")
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=CFG.DEBUG_SOCKETIO)
