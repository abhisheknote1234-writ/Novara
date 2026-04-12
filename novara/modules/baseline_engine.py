"""
baseline_engine.py — Personalized Baseline Computation
========================================================
Builds a patient's physiological baseline from the first 3–5 days
of daily log data. Subsequent readings are compared against this
baseline to detect deviations and trends.
"""
from datetime import datetime
from typing import Dict, Optional

from novara.config import BASELINE_DAYS_MIN, BASELINE_DAYS_MAX
from novara.models.database import session_scope, get_session
from novara.models.patient import Baseline, DailyLog


class BaselineEngine:
    """
    Computes and manages personalized baselines for each patient.
    
    Workflow:
      1. Patient logs daily data for 3–5 days
      2. Baseline is computed as the mean of those days
      3. All future readings are compared to this baseline
      4. Deviations (%) are returned for risk evaluation
    """

    def check_baseline_ready(self, patient_id: str) -> Dict[str, any]:
        """
        Check if a patient has enough data to establish a baseline.
        
        Returns:
            dict with keys: ready (bool), days_logged (int), days_needed (int)
        """
        session = get_session()
        try:
            count = (
                session.query(DailyLog)
                .filter_by(patient_id=patient_id)
                .count()
            )
            return {
                "ready":       count >= BASELINE_DAYS_MIN,
                "days_logged": count,
                "days_needed": max(0, BASELINE_DAYS_MIN - count),
            }
        finally:
            session.close()

    def compute_baseline(self, patient_id: str) -> Optional[Dict[str, float]]:
        """
        Compute baseline from the earliest 3–5 days of logs.
        Stores the result in the BASELINES table.
        
        Returns the computed baseline dict, or None if insufficient data.
        """
        session = get_session()
        try:
            logs = (
                session.query(DailyLog)
                .filter_by(patient_id=patient_id)
                .order_by(DailyLog.log_date.asc())
                .limit(BASELINE_DAYS_MAX)
                .all()
            )
        finally:
            session.close()

        if len(logs) < BASELINE_DAYS_MIN:
            return None

        # Compute averages across baseline period
        n = len(logs)
        baseline_hr      = sum(l.avg_heart_rate     for l in logs) / n
        baseline_rmssd   = sum(l.avg_hrv_rmssd      for l in logs) / n
        baseline_sdnn    = sum(l.avg_hrv_sdnn       for l in logs) / n
        baseline_stress  = sum(l.avg_stress_score   for l in logs) / n
        baseline_recover = sum(l.avg_recovery_score for l in logs) / n

        # Store in database
        with session_scope() as session:
            existing = (
                session.query(Baseline)
                .filter_by(patient_id=patient_id)
                .first()
            )

            if existing:
                existing.baseline_hr        = baseline_hr
                existing.baseline_hrv_rmssd = baseline_rmssd
                existing.baseline_hrv_sdnn  = baseline_sdnn
                existing.baseline_stress    = baseline_stress
                existing.baseline_recovery  = baseline_recover
                existing.days_used          = n
                existing.is_established     = True
                existing.computed_at        = datetime.utcnow()
            else:
                bl = Baseline(
                    patient_id=patient_id,
                    baseline_hr=baseline_hr,
                    baseline_hrv_rmssd=baseline_rmssd,
                    baseline_hrv_sdnn=baseline_sdnn,
                    baseline_stress=baseline_stress,
                    baseline_recovery=baseline_recover,
                    days_used=n,
                    is_established=True,
                    computed_at=datetime.utcnow(),
                )
                session.add(bl)

        return {
            "baseline_hr":        round(baseline_hr, 1),
            "baseline_hrv_rmssd": round(baseline_rmssd, 2),
            "baseline_hrv_sdnn":  round(baseline_sdnn, 2),
            "baseline_stress":    round(baseline_stress, 1),
            "baseline_recovery":  round(baseline_recover, 1),
            "days_used":          n,
            "is_established":     True,
        }

    def get_baseline(self, patient_id: str) -> Optional[Dict[str, float]]:
        """Retrieve stored baseline for a patient."""
        session = get_session()
        try:
            bl = (
                session.query(Baseline)
                .filter_by(patient_id=patient_id)
                .first()
            )
            if bl is None or not bl.is_established:
                return None

            return {
                "baseline_hr":        round(bl.baseline_hr, 1),
                "baseline_hrv_rmssd": round(bl.baseline_hrv_rmssd, 2),
                "baseline_hrv_sdnn":  round(bl.baseline_hrv_sdnn, 2),
                "baseline_stress":    round(bl.baseline_stress, 1),
                "baseline_recovery":  round(bl.baseline_recovery, 1),
                "days_used":          bl.days_used,
                "is_established":     bl.is_established,
                "computed_at":        bl.computed_at.isoformat() if bl.computed_at else "",
            }
        finally:
            session.close()

    def compare_to_baseline(
        self, patient_id: str, current_metrics: Dict[str, float]
    ) -> Optional[Dict[str, float]]:
        """
        Compare current day's metrics to the patient's baseline.
        
        Returns:
            Dict with deviation percentages for each metric.
            Positive = above baseline, Negative = below baseline.
            None if baseline not established.
        """
        baseline = self.get_baseline(patient_id)
        if baseline is None:
            return None

        def pct_change(current, baseline_val):
            if baseline_val == 0:
                return 0.0
            return round((current - baseline_val) / baseline_val * 100.0, 1)

        return {
            "hr_deviation_pct":       pct_change(
                current_metrics.get("avg_heart_rate", 0), baseline["baseline_hr"]
            ),
            "hrv_rmssd_deviation_pct": pct_change(
                current_metrics.get("avg_hrv_rmssd", 0), baseline["baseline_hrv_rmssd"]
            ),
            "hrv_sdnn_deviation_pct":  pct_change(
                current_metrics.get("avg_hrv_sdnn", 0), baseline["baseline_hrv_sdnn"]
            ),
            "stress_deviation_pct":    pct_change(
                current_metrics.get("avg_stress_score", 0), baseline["baseline_stress"]
            ),
            "recovery_deviation_pct":  pct_change(
                current_metrics.get("avg_recovery_score", 0), baseline["baseline_recovery"]
            ),
            "baseline": baseline,
        }
