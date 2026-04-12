"""
simulator.py — Demo Data Generator
=====================================
Creates realistic simulated patient profiles and daily physiological
data for demonstration and testing. Includes normal patterns and
abnormal scenarios to trigger risk detection.
"""
import random
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict

from novara.models.database import init_db
from novara.modules.patient_repo import PatientRepository
from novara.modules.baseline_engine import BaselineEngine
from novara.modules.risk_engine import RiskEngine


# ─── Simulation Personas ─────────────────────────────────────────

DEMO_PATIENTS = [
    {
        "name": "Priya Sharma",
        "age": 28,
        "pregnancy_stage": "trimester_2",
        "gestational_weeks": 22,
        "blood_type": "B+",
        "medical_notes": "First pregnancy. No known complications. Regular prenatal visits.",
        "consent_given": True,
        "scenario": "normal",
    },
    {
        "name": "Ananya Patel",
        "age": 32,
        "pregnancy_stage": "trimester_3",
        "gestational_weeks": 34,
        "blood_type": "O+",
        "medical_notes": "Second pregnancy. Mild gestational diabetes managed with diet.",
        "consent_given": True,
        "scenario": "high_stress",
    },
    {
        "name": "Meera Reddy",
        "age": 35,
        "pregnancy_stage": "trimester_3",
        "gestational_weeks": 30,
        "blood_type": "A+",
        "medical_notes": "First pregnancy. Family history of hypertension.",
        "consent_given": True,
        "scenario": "preeclampsia_risk",
    },
    {
        "name": "Kavita Singh",
        "age": 26,
        "pregnancy_stage": "trimester_1",
        "gestational_weeks": 10,
        "blood_type": "AB+",
        "medical_notes": "First pregnancy. Active lifestyle. No complications.",
        "consent_given": True,
        "scenario": "recovery_focused",
    },
    {
        "name": "Deepa Nair",
        "age": 30,
        "pregnancy_stage": "trimester_2",
        "gestational_weeks": 18,
        "blood_type": "B-",
        "medical_notes": "Second pregnancy. Previous uncomplicated delivery.",
        "consent_given": False,  # Consent not yet given — tests sharing gate
        "scenario": "unstable",
    },
]


class Simulator:
    """
    Generates demo patients and simulated physiological data.
    Each patient follows a predefined scenario to test different
    risk detection pathways.
    """

    def __init__(self):
        self.repo     = PatientRepository()
        self.baseline = BaselineEngine()
        self.risk     = RiskEngine()

    def seed_all(self, days: int = 14) -> List[str]:
        """
        Create all demo patients, generate daily data, compute baselines,
        and run risk evaluation.
        
        Returns list of patient IDs created.
        """
        init_db()
        patient_ids = []

        for persona in DEMO_PATIENTS:
            pid = self._create_patient(persona)
            patient_ids.append(pid)

            scenario = persona["scenario"]
            self._generate_daily_data(pid, days=days, scenario=scenario)

            # Compute baseline from first 3–5 days
            self.baseline.compute_baseline(pid)

            # Run risk evaluation
            self.risk.evaluate(pid)

        return patient_ids

    def _create_patient(self, persona: Dict) -> str:
        """Create a single patient from a persona template."""
        return self.repo.create_patient(
            name=persona["name"],
            age=persona["age"],
            pregnancy_stage=persona["pregnancy_stage"],
            gestational_weeks=persona["gestational_weeks"],
            blood_type=persona["blood_type"],
            medical_notes=persona["medical_notes"],
            consent_given=persona["consent_given"],
        )

    def _generate_daily_data(self, patient_id: str, days: int, scenario: str):
        """
        Generate daily physiological data following a scenario.
        
        Scenarios:
          - normal:            Healthy baseline with mild variation
          - high_stress:       Progressively increasing stress
          - preeclampsia_risk: Elevated HR + declining HRV + high stress
          - recovery_focused:  Low stress, high HRV, good recovery  
          - unstable:          Erratic fluctuations in all metrics
        """
        rng = np.random.RandomState(hash(patient_id) % (2**31))
        start_date = datetime.now() - timedelta(days=days)

        for day in range(days):
            date_str = (start_date + timedelta(days=day)).strftime("%Y-%m-%d")
            progress = day / max(days - 1, 1)  # 0.0 → 1.0

            metrics = self._scenario_metrics(scenario, progress, rng)

            self.repo.add_daily_log(patient_id, date_str, metrics)

    def _scenario_metrics(
        self, scenario: str, progress: float, rng: np.random.RandomState
    ) -> Dict[str, float]:
        """Generate metrics for a specific scenario at a given progress point."""
        noise = lambda scale=1.0: rng.normal(0, scale)

        if scenario == "normal":
            hr       = 72 + noise(3)
            rmssd    = 42 + noise(5)
            sdnn     = 48 + noise(4)
            stress   = 30 + noise(5)
            recovery = 70 + noise(5)

        elif scenario == "high_stress":
            # Stress ramps up over time
            hr       = 72 + progress * 20 + noise(3)
            rmssd    = 42 - progress * 15 + noise(4)
            sdnn     = 48 - progress * 10 + noise(4)
            stress   = 35 + progress * 45 + noise(5)
            recovery = 65 - progress * 30 + noise(5)

        elif scenario == "preeclampsia_risk":
            # Progressive deterioration pattern
            hr       = 75 + progress * 25 + noise(3)    # HR climbs to ~100
            rmssd    = 40 - progress * 18 + noise(3)    # RMSSD drops significantly
            sdnn     = 45 - progress * 15 + noise(3)
            stress   = 40 + progress * 35 + noise(4)    # Stress rises above 65
            recovery = 60 - progress * 35 + noise(4)

        elif scenario == "recovery_focused":
            hr       = 65 + noise(2)
            rmssd    = 55 + progress * 8 + noise(4)     # Good HRV
            sdnn     = 58 + progress * 5 + noise(3)
            stress   = 20 + noise(4)
            recovery = 78 + progress * 10 + noise(3)    # Strong recovery

        elif scenario == "unstable":
            # Chaotic, unpredictable swings
            hr       = 75 + rng.uniform(-15, 20)
            rmssd    = 35 + rng.uniform(-15, 15)
            sdnn     = 40 + rng.uniform(-12, 12)
            stress   = 50 + rng.uniform(-25, 30)
            recovery = 50 + rng.uniform(-25, 25)

        else:
            # Fallback to normal
            hr       = 72 + noise(3)
            rmssd    = 42 + noise(5)
            sdnn     = 48 + noise(4)
            stress   = 30 + noise(5)
            recovery = 70 + noise(5)

        # Clamp all values to physiological ranges
        hr       = max(50, min(130, hr))
        rmssd    = max(8, min(120, rmssd))
        sdnn     = max(10, min(100, sdnn))
        stress   = max(0, min(100, stress))
        recovery = max(0, min(100, recovery))

        return {
            "avg_heart_rate":     round(hr, 1),
            "avg_hrv_rmssd":      round(rmssd, 2),
            "avg_hrv_sdnn":       round(sdnn, 2),
            "avg_stress_score":   round(stress, 1),
            "avg_recovery_score": round(recovery, 1),
            "min_heart_rate":     round(hr - rng.uniform(5, 15), 1),
            "max_heart_rate":     round(hr + rng.uniform(5, 20), 1),
            "total_samples":      rng.randint(50000, 120000),
        }


def simulate_ecg(duration_sec: float = 10, fs: int = 250, hr_bpm: float = 72) -> np.ndarray:
    """
    Generate a synthetic ECG signal for testing the data pipeline.
    Produces a simplified PQRST waveform.
    
    Args:
        duration_sec: Signal duration in seconds
        fs:          Sampling rate
        hr_bpm:      Desired heart rate in BPM
    
    Returns:
        1-D numpy array of ECG samples
    """
    n_samples = int(duration_sec * fs)
    t = np.arange(n_samples) / fs
    
    rr_sec  = 60.0 / hr_bpm
    ecg     = np.zeros(n_samples)
    
    beat_idx = 0
    beat_pos = 0.0
    
    while beat_pos < duration_sec:
        center = int(beat_pos * fs)
        if center >= n_samples:
            break
        
        # Simplified PQRST morphology
        for i in range(max(0, center - int(0.2*fs)), min(n_samples, center + int(0.2*fs))):
            dt = (i - center) / fs
            
            # P wave
            ecg[i] += 0.15 * np.exp(-((dt + 0.08)**2) / (2 * 0.01**2))
            
            # QRS complex
            ecg[i] -= 0.10 * np.exp(-((dt + 0.01)**2) / (2 * 0.004**2))  # Q
            ecg[i] += 1.00 * np.exp(-((dt)**2) / (2 * 0.005**2))          # R
            ecg[i] -= 0.15 * np.exp(-((dt - 0.015)**2) / (2 * 0.005**2))  # S
            
            # T wave
            ecg[i] += 0.25 * np.exp(-((dt - 0.10)**2) / (2 * 0.02**2))
        
        # Add slight RR variability
        rr_var = rr_sec + np.random.normal(0, 0.02)
        beat_pos += max(0.4, rr_var)
        beat_idx += 1
    
    # Add realistic noise
    ecg += np.random.normal(0, 0.02, n_samples)       # White noise
    ecg += 0.01 * np.sin(2 * np.pi * 0.3 * t)         # Baseline wander
    
    return ecg
