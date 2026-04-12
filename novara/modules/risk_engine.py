"""
risk_engine.py — Rule-Based Risk Detection
=============================================
Evaluates patient data against clinical rule-sets and flags
risk patterns. NO ML — purely rule-based for interpretability.

CRITICAL DISCLAIMER:
    This system identifies RISK PATTERNS, not medical diagnoses.
    All flags must be reviewed by a qualified healthcare provider.
"""
from datetime import datetime
from typing import List, Dict

from novara.config import (
    STRESS_HIGH_THRESHOLD, STRESS_SUSTAINED_DAYS,
    HRV_DROP_THRESHOLD_PCT, HR_HIGH_THRESHOLD, HR_LOW_THRESHOLD,
    PREECLAMPSIA_HR_ELEVATION_PCT, PREECLAMPSIA_HRV_DROP_PCT,
    PREECLAMPSIA_STRESS_THRESHOLD, PREECLAMPSIA_MIN_WEEKS,
)
from novara.models.database import session_scope, get_session
from novara.models.patient import RiskFlag
from novara.modules.baseline_engine import BaselineEngine
from novara.modules.patient_repo import PatientRepository


# Standard disclaimer appended to every risk flag explanation
DISCLAIMER = (
    " ⚠️ This is a risk pattern indicator, not a medical diagnosis. "
    "Consult a healthcare provider for clinical evaluation."
)


class RiskEngine:
    """
    Rule-based risk detection engine.
    
    Rules:
      1. Sustained High Stress (stress > 70 for 3+ consecutive days)
      2. HRV Drop (RMSSD drops >25% below baseline)
      3. Abnormal Heart Rate (HR >100 or <55 sustained)
      4. Preeclampsia Risk Pattern (composite of elevated HR, HRV decline,
         high stress, late trimester)
    """

    def __init__(self):
        self.baseline_engine = BaselineEngine()
        self.patient_repo    = PatientRepository()

    def evaluate(self, patient_id: str) -> List[Dict]:
        """
        Run all risk rules against a patient's data.
        Stores new flags in the database.
        Returns list of newly detected flag dicts.
        """
        patient = self.patient_repo.get_patient(patient_id)
        if patient is None:
            return []

        logs = self.patient_repo.get_patient_logs(patient_id, days=14)
        if not logs:
            return []

        baseline = self.baseline_engine.get_baseline(patient_id)

        new_flags = []

        # Rule 1: Sustained High Stress
        flag = self._check_sustained_stress(patient_id, logs)
        if flag:
            new_flags.append(flag)

        # Rule 2: HRV Drop
        if baseline:
            flag = self._check_hrv_drop(patient_id, logs, baseline)
            if flag:
                new_flags.append(flag)

        # Rule 3: Abnormal Heart Rate
        flag = self._check_abnormal_hr(patient_id, logs)
        if flag:
            new_flags.append(flag)

        # Rule 4: Preeclampsia Risk Pattern
        if baseline:
            flag = self._check_preeclampsia_pattern(patient_id, patient, logs, baseline)
            if flag:
                new_flags.append(flag)

        # Store all new flags
        self._store_flags(new_flags)

        return new_flags

    # ─── Rule 1: Sustained High Stress ───────────────────────────

    def _check_sustained_stress(self, patient_id: str, logs: List[Dict]) -> Dict:
        """Flag if stress score > threshold for N consecutive days."""
        # Sort by date ascending
        sorted_logs = sorted(logs, key=lambda x: x["log_date"])

        consecutive = 0
        for log in sorted_logs:
            if log["avg_stress_score"] > STRESS_HIGH_THRESHOLD:
                consecutive += 1
            else:
                consecutive = 0

        if consecutive >= STRESS_SUSTAINED_DAYS:
            severity = "high" if consecutive >= 5 else "moderate"
            confidence = min(1.0, consecutive / 7.0)
            return {
                "patient_id": patient_id,
                "flag_type": "sustained_high_stress",
                "severity": severity,
                "confidence_score": round(confidence, 2),
                "explanation": (
                    f"Elevated stress pattern detected: stress score has remained above "
                    f"{STRESS_HIGH_THRESHOLD} for {consecutive} consecutive days. "
                    f"This sustained autonomic imbalance may indicate chronic sympathetic "
                    f"over-activation, which warrants clinical attention during pregnancy."
                    + DISCLAIMER
                ),
            }
        return None

    # ─── Rule 2: HRV Drop ───────────────────────────────────────

    def _check_hrv_drop(self, patient_id: str, logs: List[Dict], baseline: Dict) -> Dict:
        """Flag if recent HRV (RMSSD) is significantly below baseline."""
        if not logs:
            return None

        # Use the most recent 3 days
        recent = sorted(logs, key=lambda x: x["log_date"], reverse=True)[:3]
        avg_recent_rmssd = sum(l["avg_hrv_rmssd"] for l in recent) / len(recent)

        baseline_rmssd = baseline.get("baseline_hrv_rmssd", 0)
        if baseline_rmssd <= 0:
            return None

        drop_pct = (baseline_rmssd - avg_recent_rmssd) / baseline_rmssd * 100.0

        if drop_pct > HRV_DROP_THRESHOLD_PCT:
            severity = "critical" if drop_pct > 40 else ("high" if drop_pct > 30 else "moderate")
            confidence = min(1.0, drop_pct / 50.0)
            return {
                "patient_id": patient_id,
                "flag_type": "hrv_drop",
                "severity": severity,
                "confidence_score": round(confidence, 2),
                "explanation": (
                    f"Heart rate variability (RMSSD) has decreased by {drop_pct:.1f}% "
                    f"relative to the established baseline ({baseline_rmssd:.1f}ms → "
                    f"{avg_recent_rmssd:.1f}ms). A sustained decline in HRV indicates "
                    f"reduced parasympathetic (vagal) tone, which is associated with "
                    f"cardiovascular stress and may require monitoring."
                    + DISCLAIMER
                ),
            }
        return None

    # ─── Rule 3: Abnormal Heart Rate ────────────────────────────

    def _check_abnormal_hr(self, patient_id: str, logs: List[Dict]) -> Dict:
        """Flag if recent average HR is consistently above 100 or below 55."""
        recent = sorted(logs, key=lambda x: x["log_date"], reverse=True)[:3]
        if not recent:
            return None

        avg_hr = sum(l["avg_heart_rate"] for l in recent) / len(recent)

        if avg_hr > HR_HIGH_THRESHOLD:
            return {
                "patient_id": patient_id,
                "flag_type": "abnormal_hr",
                "severity": "high" if avg_hr > 110 else "moderate",
                "confidence_score": round(min(1.0, (avg_hr - HR_HIGH_THRESHOLD) / 20.0), 2),
                "explanation": (
                    f"Sustained elevated heart rate detected: average HR of {avg_hr:.0f} bpm "
                    f"over the past {len(recent)} days exceeds the upper threshold of "
                    f"{HR_HIGH_THRESHOLD:.0f} bpm. Persistent tachycardia during pregnancy "
                    f"may indicate dehydration, anxiety, anemia, or cardiac stress."
                    + DISCLAIMER
                ),
            }
        elif avg_hr < HR_LOW_THRESHOLD and avg_hr > 0:
            return {
                "patient_id": patient_id,
                "flag_type": "abnormal_hr",
                "severity": "moderate",
                "confidence_score": round(min(1.0, (HR_LOW_THRESHOLD - avg_hr) / 15.0), 2),
                "explanation": (
                    f"Unusually low heart rate detected: average HR of {avg_hr:.0f} bpm "
                    f"over the past {len(recent)} days is below the lower threshold of "
                    f"{HR_LOW_THRESHOLD:.0f} bpm. While athletic individuals may have lower "
                    f"resting HR, sustained bradycardia during pregnancy should be evaluated."
                    + DISCLAIMER
                ),
            }
        return None

    # ─── Rule 4: Preeclampsia Risk Pattern ──────────────────────

    def _check_preeclampsia_pattern(
        self, patient_id: str, patient: Dict, logs: List[Dict], baseline: Dict
    ) -> Dict:
        """
        Composite risk pattern for preeclampsia indicators.
        
        Factors (all must be checked, score accumulates):
          - Sustained elevated HR (>15% above baseline)
          - Progressive HRV decline (>20% below baseline)
          - High stress score (>65)
          - Late trimester (≥28 weeks gestation)
        
        NOT A DIAGNOSIS — a pattern that warrants clinical follow-up.
        """
        weeks = patient.get("gestational_weeks", 0)
        recent = sorted(logs, key=lambda x: x["log_date"], reverse=True)[:5]
        if not recent:
            return None

        score = 0.0
        reasons = []

        # Factor 1: Elevated HR
        avg_hr = sum(l["avg_heart_rate"] for l in recent) / len(recent)
        baseline_hr = baseline.get("baseline_hr", avg_hr)
        if baseline_hr > 0:
            hr_elevation_pct = (avg_hr - baseline_hr) / baseline_hr * 100.0
            if hr_elevation_pct > PREECLAMPSIA_HR_ELEVATION_PCT:
                score += 0.25
                reasons.append(f"HR elevated {hr_elevation_pct:.1f}% above baseline")

        # Factor 2: HRV decline
        avg_rmssd = sum(l["avg_hrv_rmssd"] for l in recent) / len(recent)
        baseline_rmssd = baseline.get("baseline_hrv_rmssd", avg_rmssd)
        if baseline_rmssd > 0:
            hrv_drop_pct = (baseline_rmssd - avg_rmssd) / baseline_rmssd * 100.0
            if hrv_drop_pct > PREECLAMPSIA_HRV_DROP_PCT:
                score += 0.25
                reasons.append(f"HRV decreased {hrv_drop_pct:.1f}% below baseline")

        # Factor 3: High stress
        avg_stress = sum(l["avg_stress_score"] for l in recent) / len(recent)
        if avg_stress > PREECLAMPSIA_STRESS_THRESHOLD:
            score += 0.25
            reasons.append(f"Sustained stress score of {avg_stress:.0f}")

        # Factor 4: Late trimester
        if weeks >= PREECLAMPSIA_MIN_WEEKS:
            score += 0.25
            reasons.append(f"Gestational age {weeks} weeks (high-risk period)")

        # Only flag if composite score exceeds 50% (at least 2 factors)
        if score >= 0.50:
            severity = "critical" if score >= 0.75 else "high"
            return {
                "patient_id": patient_id,
                "flag_type": "preeclampsia_pattern",
                "severity": severity,
                "confidence_score": round(score, 2),
                "explanation": (
                    "Possible preeclampsia risk pattern detected — a combination of "
                    "cardiovascular indicators suggest elevated risk:\n"
                    + "\n".join(f"  • {r}" for r in reasons)
                    + "\n\nPreeclampsia is a serious pregnancy complication characterized by "
                    "high blood pressure and organ damage. Early detection enables "
                    "preventive interventions."
                    + DISCLAIMER
                ),
            }
        return None

    # ─── Storage ─────────────────────────────────────────────────

    def _store_flags(self, flags: List[Dict]) -> None:
        """Persist new risk flags to the database."""
        if not flags:
            return

        with session_scope() as session:
            for f in flags:
                # Avoid duplicate flags of the same type within the last 24 hours
                existing = (
                    session.query(RiskFlag)
                    .filter_by(patient_id=f["patient_id"], flag_type=f["flag_type"])
                    .order_by(RiskFlag.detected_at.desc())
                    .first()
                )
                if existing:
                    # Skip if same flag was raised in the last day
                    age = (datetime.utcnow() - existing.detected_at).total_seconds()
                    if age < 86400:  # 24 hours
                        continue

                flag = RiskFlag(
                    patient_id=f["patient_id"],
                    flag_type=f["flag_type"],
                    severity=f["severity"],
                    explanation=f["explanation"],
                    confidence_score=f["confidence_score"],
                    detected_at=datetime.utcnow(),
                )
                session.add(flag)
