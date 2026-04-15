"""
FastAPI real-time ARC backend.

Receives raw ECG/PPG/EMG batches, processes 30 s sliding windows every 5 s,
and returns smoothed A-R-C outputs + HRV features.
"""

import math
import threading
from collections import deque
from typing import Optional

import neurokit2 as nk
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from scipy.interpolate import interp1d
from scipy.signal import butter, detrend, find_peaks, iirnotch, sosfiltfilt, tf2sos, welch

try:
    import antropy as ant
except Exception:  # pragma: no cover
    ant = None

TRAPZ = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
MIN_RR_MS = 300.0
MAX_RR_MS = 2000.0
MAX_RR_JUMP_MS = 200.0


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return _clip01((value - low) / (high - low))


def _sample_entropy(x: np.ndarray, m: int = 2, r_scale: float = 0.2) -> float:
    if len(x) < m + 3:
        return 0.0
    x = np.asarray(x, dtype=float)
    r = r_scale * np.std(x)
    if r <= 0:
        return 0.0

    def _count(dim: int) -> float:
        n = len(x) - dim + 1
        templates = np.array([x[i : i + dim] for i in range(n)])
        c = 0
        for i in range(n - 1):
            d = np.max(np.abs(templates[i + 1 :] - templates[i]), axis=1)
            c += int(np.sum(d <= r))
        return float(c)

    b = _count(m)
    a = _count(m + 1)
    if b == 0 or a == 0:
        return 0.0
    return float(-np.log(a / b))


class SignalBatch(BaseModel):
    sampling_rate: float = Field(default=250.0, gt=20.0, le=2000.0)
    signals: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Raw physiological channels, e.g. {'ecg': [...], 'ppg': [...], 'emg': [...]}.",
    )
    timestamp: Optional[float] = Field(default=None, description="Optional batch start timestamp (s).")


class ARCProcessor:
    def __init__(self, fs: float = 250.0, window_sec: float = 30.0, step_sec: float = 5.0):
        self.fs = float(fs)
        self.window_sec = float(window_sec)
        self.step_sec = float(step_sec)
        self.window_samples = int(self.window_sec * self.fs)
        self.step_samples = int(self.step_sec * self.fs)
        self.max_buffer = int(120 * self.fs)

        self.buffers = {
            "ecg": deque(maxlen=self.max_buffer),
            "ppg": deque(maxlen=self.max_buffer),
            "emg": deque(maxlen=self.max_buffer),
        }
        self.sample_count = 0
        self.last_processed_at = 0
        self.latest_output: Optional[dict] = None
        self.arc_history = deque(maxlen=6)
        self.feature_history = {"HR": deque(maxlen=72), "RMSSD": deque(maxlen=72)}
        self.rr_var_history = deque(maxlen=72)
        self.raw_state_history = deque(maxlen=10)
        self.active_state = "YELLOW"
        self.prev_arc: Optional[dict[str, float]] = None
        self.lock = threading.Lock()
        self._init_filters()

    def _init_filters(self) -> None:
        nyq = self.fs / 2.0
        self.bp_sos = butter(4, [0.5 / nyq, 40.0 / nyq], btype="band", output="sos")
        b_notch, a_notch = iirnotch(50.0, 30.0, self.fs)
        self.notch_sos = tf2sos(b_notch, a_notch)

    def _preprocess(self, sig: np.ndarray) -> np.ndarray:
        if len(sig) < max(32, int(1.5 * self.fs)):
            return sig.astype(float)
        x = sosfiltfilt(self.bp_sos, sig)
        x = sosfiltfilt(self.notch_sos, x)
        x = detrend(x, type="linear")  # baseline wander removal
        return x

    def _detect_rpeaks(self, ecg_clean: np.ndarray) -> np.ndarray:
        try:
            _, info = nk.ecg_peaks(ecg_clean, sampling_rate=self.fs, method="neurokit")
            peaks = np.asarray(info.get("ECG_R_Peaks", []), dtype=int)
            if len(peaks) > 2:
                return peaks
        except Exception:
            pass

        # Pan-Tompkins-like fallback
        diff = np.diff(ecg_clean, prepend=ecg_clean[0])
        sq = diff**2
        mwi_win = max(1, int(0.15 * self.fs))
        mwi = np.convolve(sq, np.ones(mwi_win) / mwi_win, mode="same")
        distance = max(1, int(0.25 * self.fs))
        threshold = np.mean(mwi) + 0.5 * np.std(mwi)
        peaks, _ = find_peaks(mwi, distance=distance, height=threshold)
        return peaks.astype(int)

    def _rr_from_peaks(self, peaks: np.ndarray) -> np.ndarray:
        if len(peaks) < 3:
            return np.array([], dtype=float)
        rr_ms = np.diff(peaks) * (1000.0 / self.fs)
        return rr_ms[(rr_ms >= MIN_RR_MS) & (rr_ms <= MAX_RR_MS)]

    @staticmethod
    def _clean_rr(rr_ms: np.ndarray) -> np.ndarray:
        rr = np.asarray(rr_ms, dtype=float)
        rr = rr[(rr >= MIN_RR_MS) & (rr <= MAX_RR_MS)]
        if len(rr) < 3:
            return rr
        diff = np.abs(np.diff(rr))
        rr = rr[np.insert(diff < MAX_RR_JUMP_MS, 0, True)]
        return rr

    @staticmethod
    def _interpolate_rr(rr_ms: np.ndarray, fs_interp: float = 4.0) -> Optional[np.ndarray]:
        if len(rr_ms) < 4:
            return None
        rr_s = rr_ms / 1000.0
        time = np.cumsum(rr_s)
        unique_mask = np.insert(np.diff(time) > 1e-9, 0, True)
        time = time[unique_mask]
        rr_vals = rr_ms[unique_mask]
        if len(rr_vals) < 4 or time[-1] <= time[0]:
            return None
        kind = "cubic" if len(rr_vals) >= 4 else "linear"
        f = interp1d(time, rr_vals, kind=kind, bounds_error=False, fill_value="extrapolate")
        new_time = np.arange(time[0], time[-1], 1.0 / fs_interp)
        if len(new_time) < 16:
            return None
        return np.asarray(f(new_time), dtype=float)

    def _hrv_frequency(self, rr_ms: np.ndarray) -> dict[str, float]:
        out = {"LF": 0.0, "HF": 0.0, "LFHF": 0.0}
        if len(rr_ms) < 20:
            return out

        rr_interp = self._interpolate_rr(rr_ms, fs_interp=4.0)
        if rr_interp is None:
            return out

        fs_interp = 4.0
        rr_interp = detrend(rr_interp, type="constant")
        nperseg = min(256, len(rr_interp))
        freqs, psd = welch(rr_interp, fs=fs_interp, nperseg=nperseg, noverlap=nperseg // 2)

        lf_mask = (freqs >= 0.04) & (freqs < 0.15)
        hf_mask = (freqs >= 0.15) & (freqs <= 0.40)
        lf = float(TRAPZ(psd[lf_mask], freqs[lf_mask])) if np.sum(lf_mask) > 1 else 0.0
        hf = float(TRAPZ(psd[hf_mask], freqs[hf_mask])) if np.sum(hf_mask) > 1 else 0.0
        out["LF"] = max(lf, 0.0)
        out["HF"] = max(hf, 0.0)
        out["LFHF"] = float(out["LF"] / (out["HF"] + 1e-9))
        return out

    def _hrv_nonlinear(self, rr_ms: np.ndarray) -> dict[str, float]:
        if len(rr_ms) < 3:
            return {"SD1": 0.0, "SD2": 0.0}
        d = np.diff(rr_ms)
        sd1 = math.sqrt(max(np.var(d, ddof=1) / 2.0, 0.0)) if len(d) > 1 else 0.0
        sdnn = np.std(rr_ms, ddof=1) if len(rr_ms) > 1 else 0.0
        sd2_sq = max(2 * (sdnn**2) - 0.5 * (sd1**2), 0.0)
        sd2 = math.sqrt(sd2_sq)
        return {"SD1": float(sd1), "SD2": float(sd2)}

    def _compute_features(self, rr_ms: np.ndarray) -> dict[str, float]:
        if len(rr_ms) < 3:
            return {k: 0.0 for k in ["HR", "RMSSD", "SDNN", "pNN50", "LF", "HF", "LFHF", "SD1", "SD2"]}

        rr_diff = np.diff(rr_ms)
        rmssd = float(np.sqrt(np.mean(rr_diff**2))) if len(rr_diff) else 0.0
        sdnn = float(np.std(rr_ms, ddof=1)) if len(rr_ms) > 1 else 0.0
        pnn50 = float((np.sum(np.abs(rr_diff) > 50) / max(1, len(rr_diff))) * 100.0)
        mean_rr = float(np.mean(rr_ms))
        hr = float(60000.0 / mean_rr) if mean_rr > 1e-9 else 0.0
        freq = self._hrv_frequency(rr_ms)
        nonlinear = self._hrv_nonlinear(rr_ms)
        return {
            "HR": hr,
            "RMSSD": rmssd,
            "SDNN": sdnn,
            "pNN50": pnn50,
            "LF": float(freq["LF"]),
            "HF": float(freq["HF"]),
            "LFHF": float(freq["LFHF"]),
            "SD1": float(nonlinear["SD1"]),
            "SD2": float(nonlinear["SD2"]),
        }

    def _update_baseline(self, features: dict[str, float]) -> None:
        if features["HR"] > 0:
            self.feature_history["HR"].append(float(features["HR"]))
        if features["RMSSD"] > 0:
            self.feature_history["RMSSD"].append(float(features["RMSSD"]))

    def _get_baseline(self, features: dict[str, float]) -> dict[str, float]:
        hr_hist = list(self.feature_history["HR"])
        rm_hist = list(self.feature_history["RMSSD"])
        hr_base = float(np.mean(hr_hist[-20:])) if hr_hist else max(float(features["HR"]), 70.0)
        rm_base = float(np.mean(rm_hist[-20:])) if rm_hist else max(float(features["RMSSD"]), 35.0)
        return {"HR": max(hr_base, 1.0), "RMSSD": max(rm_base, 1.0)}

    def _arc_scores(self, features: dict[str, float], rr_ms: np.ndarray) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        baseline = self._get_baseline(features)
        hr_rel = (features["HR"] - baseline["HR"]) / baseline["HR"]
        rmssd_rel = (features["RMSSD"] - baseline["RMSSD"]) / baseline["RMSSD"]

        lfhf_n = _normalize(features["LFHF"], 0.5, 4.0)
        lf_n = _normalize(features["LF"], 20.0, 1200.0)
        hf_n = _normalize(features["HF"], 20.0, 1200.0)
        pnn50_n = _normalize(features["pNN50"], 0.0, 45.0)

        symp = 0.60 * hr_rel + 0.25 * (2 * lfhf_n - 1) + 0.15 * (2 * lf_n - 1)
        para = 0.60 * rmssd_rel + 0.25 * (2 * hf_n - 1) + 0.15 * (2 * pnn50_n - 1)
        arousal = 50.0 + 40.0 * symp
        regulation = 50.0 + 40.0 * para

        sd1_sd2 = features["SD1"] / (features["SD2"] + 1e-9)
        ratio_n = _normalize(sd1_sd2, 0.2, 0.8)
        if ant is not None and len(rr_ms) > 5:
            entropy = float(ant.sample_entropy(rr_ms))
        else:
            entropy = _sample_entropy(rr_ms) if len(rr_ms) > 5 else 0.0
        inv_entropy_n = _normalize(1.0 / (entropy + 1e-6), 0.0, 2.0)
        variance_rr = float(np.var(rr_ms)) if len(rr_ms) > 1 else 0.0
        var_ref = float(np.median(self.rr_var_history)) if self.rr_var_history else variance_rr
        variance_stability = _clip01(1.0 - abs(variance_rr - var_ref) / max(var_ref, variance_rr, 1e-9))
        coherence = 100.0 * ((ratio_n + inv_entropy_n + variance_stability) / 3.0)

        scores = {
            "A": float(np.clip(arousal, 0.0, 100.0)),
            "R": float(np.clip(regulation, 0.0, 100.0)),
            "C": float(np.clip(coherence, 0.0, 100.0)),
        }
        components = {
            "sd1_sd2_n": float(ratio_n),
            "inv_entropy_n": float(inv_entropy_n),
            "variance_stability": float(variance_stability),
            "entropy": float(entropy),
        }
        return scores, baseline, components

    @staticmethod
    def _state_from_arc(a: float, r: float, c: float) -> str:
        if a >= 70 and r < 40:
            return "RED"
        if c >= 70 and r >= 60 and a <= 55:
            return "BLUE"
        if c >= 55 and r >= 45:
            return "GREEN"
        return "YELLOW"

    def _smooth_arc(self, arc: dict[str, float]) -> dict[str, float]:
        self.arc_history.append(arc)
        if not self.arc_history:
            return arc
        return {
            "A": float(np.mean([x["A"] for x in self.arc_history])),
            "R": float(np.mean([x["R"] for x in self.arc_history])),
            "C": float(np.mean([x["C"] for x in self.arc_history])),
        }

    def _stable_state(self, new_state: str, min_duration: int = 3) -> str:
        self.raw_state_history.append(new_state)
        if len(self.raw_state_history) >= min_duration and all(
            s == new_state for s in list(self.raw_state_history)[-min_duration:]
        ):
            self.active_state = new_state
        return self.active_state

    def _momentum(self, arc: dict[str, float]) -> dict[str, float]:
        if self.prev_arc is None:
            d = {"dA": 0.0, "dR": 0.0, "dC": 0.0}
        else:
            d = {
                "dA": float(arc["A"] - self.prev_arc["A"]),
                "dR": float(arc["R"] - self.prev_arc["R"]),
                "dC": float(arc["C"] - self.prev_arc["C"]),
            }
        self.prev_arc = {"A": arc["A"], "R": arc["R"], "C": arc["C"]}
        return d

    def _predict_next_state(self, arc: dict[str, float], momentum: dict[str, float], state: str) -> str:
        a, r, c = arc["A"], arc["R"], arc["C"]
        d_a, d_r = momentum["dA"], momentum["dR"]
        if (a >= 70 and r < 40) or (d_a > 8 and d_r < -6):
            return "RED"
        if c >= 70 and r >= 60 and a <= 55 and d_a <= 0:
            return "BLUE"
        if c >= 55 and r >= 45:
            return "GREEN"
        return state

    def _process_window(self) -> Optional[dict]:
        ecg = np.asarray(self.buffers["ecg"], dtype=float)
        ppg = np.asarray(self.buffers["ppg"], dtype=float)

        if len(ecg) >= self.window_samples:
            ecg = ecg[-self.window_samples :]
            ecg_clean = self._preprocess(ecg)
            peaks = self._detect_rpeaks(ecg_clean)
        elif len(ppg) >= self.window_samples:
            # PPG fallback when ECG is insufficient but PPG has a full window.
            ppg = ppg[-self.window_samples :]
            ppg_clean = self._preprocess(ppg)
            peaks, _ = find_peaks(ppg_clean, distance=max(1, int(0.33 * self.fs)))
        else:
            return None

        rr_ms = self._clean_rr(self._rr_from_peaks(np.asarray(peaks, dtype=int)))
        if len(rr_ms) < 3:
            return None

        features = self._compute_features(rr_ms)
        self._update_baseline(features)
        self.rr_var_history.append(float(np.var(rr_ms)) if len(rr_ms) > 1 else 0.0)
        arc_raw, baseline, coherence_components = self._arc_scores(features, rr_ms)
        arc = self._smooth_arc(arc_raw)
        momentum = self._momentum(arc)
        raw_state = self._state_from_arc(arc["A"], arc["R"], arc["C"])
        stable_state = self._stable_state(raw_state, min_duration=3)
        predicted_state = self._predict_next_state(arc, momentum, stable_state)

        payload = {
            "A": round(arc["A"], 3),
            "R": round(arc["R"], 3),
            "C": round(arc["C"], 3),
            "state": stable_state,
            "state_raw": raw_state,
            "prediction": {"next_state": predicted_state},
            "momentum": {k: round(float(v), 4) for k, v in momentum.items()},
            "baseline": {k: round(float(v), 4) for k, v in baseline.items()},
            "coherence_components": {k: round(float(v), 4) for k, v in coherence_components.items()},
            "features": {k: round(float(v), 4) for k, v in features.items()},
        }
        self.latest_output = payload
        return payload

    def ingest(self, batch: SignalBatch) -> Optional[dict]:
        with self.lock:
            if abs(batch.sampling_rate - self.fs) > 1e-6:
                self.fs = float(batch.sampling_rate)
                self.window_samples = int(self.window_sec * self.fs)
                self.step_samples = int(self.step_sec * self.fs)
                self.max_buffer = int(120 * self.fs)
                self.buffers = {k: deque(v, maxlen=self.max_buffer) for k, v in self.buffers.items()}
                self._init_filters()

            max_len = max((len(v) for v in batch.signals.values()), default=0)
            if max_len == 0:
                return self.latest_output

            for ch in ("ecg", "ppg", "emg"):
                sig = batch.signals.get(ch, [])
                if sig:
                    self.buffers[ch].extend(np.asarray(sig, dtype=float).tolist())

            self.sample_count += max_len
            ready = (
                self.sample_count >= self.window_samples
                and (self.sample_count - self.last_processed_at) >= self.step_samples
            )
            if ready:
                self.last_processed_at = self.sample_count
                return self._process_window()
            return self.latest_output


app = FastAPI(title="ARC Real-time Signal API", version="1.0.0")
processor = ARCProcessor()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ingest-data")
def ingest_data(batch: SignalBatch) -> dict:
    output = processor.ingest(batch)
    return {
        "accepted_samples": max((len(v) for v in batch.signals.values()), default=0),
        "processed": output is not None,
        "result": output,
    }


@app.get("/api/process-data")
def get_process_data() -> dict:
    if processor.latest_output is None:
        return {
            "A": 0.0,
            "R": 0.0,
            "C": 0.0,
            "state": "YELLOW",
            "state_raw": "YELLOW",
            "prediction": {"next_state": "YELLOW"},
            "momentum": {"dA": 0.0, "dR": 0.0, "dC": 0.0},
            "baseline": {"HR": 70.0, "RMSSD": 35.0},
            "coherence_components": {"sd1_sd2_n": 0.0, "inv_entropy_n": 0.0, "variance_stability": 0.0, "entropy": 0.0},
            "features": {"HR": 0.0, "RMSSD": 0.0, "SDNN": 0.0, "pNN50": 0.0, "LF": 0.0, "HF": 0.0, "LFHF": 0.0, "SD1": 0.0, "SD2": 0.0},
        }
    return processor.latest_output


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "status", "message": "connected"})
    try:
        while True:
            payload = await websocket.receive_json()
            batch = SignalBatch(**payload)
            result = processor.ingest(batch)
            if result is not None:
                await websocket.send_json({"type": "arc_update", "data": result})
    except WebSocketDisconnect:
        return
