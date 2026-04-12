"""
patient_repo.py — Patient Repository (CRUD)
=============================================
Create, read, update, delete patient profiles.
All PII is encrypted via SecurityManager before storage.
"""
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from novara.models.database import session_scope, get_session
from novara.models.patient import Patient, DailyLog, Baseline, RiskFlag
from novara.modules.security import get_security_manager


class PatientRepository:
    """
    CRUD operations for patient profiles and daily logs.
    Encrypts name and medical notes automatically.
    """

    def __init__(self):
        self.sec = get_security_manager()

    # ─── CREATE ──────────────────────────────────────────────────

    def create_patient(
        self,
        name: str,
        age: int,
        pregnancy_stage: str,
        gestational_weeks: int = 0,
        blood_type: str = "Unknown",
        medical_notes: str = "",
        consent_given: bool = False,
    ) -> str:
        """
        Create a new patient profile.
        Returns the generated patient_id (UUID4).
        """
        patient_id = str(uuid.uuid4())

        patient = Patient(
            patient_id=patient_id,
            name_encrypted=self.sec.encrypt(name),
            age=age,
            pregnancy_stage=pregnancy_stage,
            gestational_weeks=gestational_weeks,
            blood_type=blood_type,
            medical_notes_encrypted=self.sec.encrypt(medical_notes),
            consent_given=consent_given,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        with session_scope() as session:
            session.add(patient)

        return patient_id

    # ─── READ ────────────────────────────────────────────────────

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """Get a patient profile with decrypted fields."""
        session = get_session()
        try:
            p = session.query(Patient).filter_by(patient_id=patient_id).first()
            if p is None:
                return None
            return self._to_dict(p)
        finally:
            session.close()

    def list_patients(self) -> List[Dict[str, Any]]:
        """List all patients with decrypted names."""
        session = get_session()
        try:
            patients = session.query(Patient).order_by(Patient.created_at.desc()).all()
            return [self._to_dict(p) for p in patients]
        finally:
            session.close()

    def get_patient_model(self, patient_id: str):
        """Get the raw ORM model (for internal use by other modules)."""
        session = get_session()
        try:
            return session.query(Patient).filter_by(patient_id=patient_id).first()
        finally:
            session.close()

    # ─── UPDATE ──────────────────────────────────────────────────

    def update_patient(self, patient_id: str, **kwargs) -> bool:
        """
        Update patient fields.
        Supported kwargs: name, age, pregnancy_stage, gestational_weeks,
                          blood_type, medical_notes, consent_given
        """
        with session_scope() as session:
            p = session.query(Patient).filter_by(patient_id=patient_id).first()
            if p is None:
                return False

            if "name" in kwargs:
                p.name_encrypted = self.sec.encrypt(kwargs["name"])
            if "age" in kwargs:
                p.age = kwargs["age"]
            if "pregnancy_stage" in kwargs:
                p.pregnancy_stage = kwargs["pregnancy_stage"]
            if "gestational_weeks" in kwargs:
                p.gestational_weeks = kwargs["gestational_weeks"]
            if "blood_type" in kwargs:
                p.blood_type = kwargs["blood_type"]
            if "medical_notes" in kwargs:
                p.medical_notes_encrypted = self.sec.encrypt(kwargs["medical_notes"])
            if "consent_given" in kwargs:
                p.consent_given = kwargs["consent_given"]

            p.updated_at = datetime.utcnow()

        return True

    # ─── DELETE ──────────────────────────────────────────────────

    def delete_patient(self, patient_id: str) -> bool:
        """Delete a patient and all associated data (cascading)."""
        with session_scope() as session:
            p = session.query(Patient).filter_by(patient_id=patient_id).first()
            if p is None:
                return False
            session.delete(p)
        return True

    # ─── DAILY LOGS ──────────────────────────────────────────────

    def add_daily_log(self, patient_id: str, log_date: str, metrics: Dict[str, float]) -> int:
        """
        Add or update a daily log for a patient.
        
        Args:
            patient_id: Patient UUID
            log_date:   Date string (YYYY-MM-DD)
            metrics:    Dict with keys: avg_heart_rate, avg_hrv_rmssd, avg_hrv_sdnn,
                        avg_stress_score, avg_recovery_score, min_heart_rate,
                        max_heart_rate, total_samples
        
        Returns:
            The DailyLog row id.
        """
        with session_scope() as session:
            # Upsert: update if exists, create if not
            existing = (
                session.query(DailyLog)
                .filter_by(patient_id=patient_id, log_date=log_date)
                .first()
            )

            if existing:
                for key, val in metrics.items():
                    if hasattr(existing, key):
                        setattr(existing, key, val)
                return existing.id
            else:
                log = DailyLog(
                    patient_id=patient_id,
                    log_date=log_date,
                    avg_heart_rate=metrics.get("avg_heart_rate", 0.0),
                    avg_hrv_rmssd=metrics.get("avg_hrv_rmssd", 0.0),
                    avg_hrv_sdnn=metrics.get("avg_hrv_sdnn", 0.0),
                    avg_stress_score=metrics.get("avg_stress_score", 0.0),
                    avg_recovery_score=metrics.get("avg_recovery_score", 0.0),
                    min_heart_rate=metrics.get("min_heart_rate", 0.0),
                    max_heart_rate=metrics.get("max_heart_rate", 0.0),
                    total_samples=metrics.get("total_samples", 0),
                )
                session.add(log)
                session.flush()
                return log.id

    def get_patient_logs(self, patient_id: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get recent daily logs for a patient, ordered by date descending."""
        session = get_session()
        try:
            logs = (
                session.query(DailyLog)
                .filter_by(patient_id=patient_id)
                .order_by(DailyLog.log_date.desc())
                .limit(days)
                .all()
            )
            return [
                {
                    "id":                 l.id,
                    "log_date":           l.log_date,
                    "avg_heart_rate":     l.avg_heart_rate,
                    "avg_hrv_rmssd":      l.avg_hrv_rmssd,
                    "avg_hrv_sdnn":       l.avg_hrv_sdnn,
                    "avg_stress_score":   l.avg_stress_score,
                    "avg_recovery_score": l.avg_recovery_score,
                    "min_heart_rate":     l.min_heart_rate,
                    "max_heart_rate":     l.max_heart_rate,
                    "total_samples":      l.total_samples,
                }
                for l in logs
            ]
        finally:
            session.close()

    # ─── RISK FLAGS ──────────────────────────────────────────────

    def get_risk_flags(self, patient_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get risk flags for a patient."""
        session = get_session()
        try:
            q = session.query(RiskFlag).filter_by(patient_id=patient_id)
            if active_only:
                q = q.filter_by(acknowledged=False)
            flags = q.order_by(RiskFlag.detected_at.desc()).all()
            return [
                {
                    "id":               f.id,
                    "flag_type":        f.flag_type,
                    "severity":         f.severity,
                    "explanation":      f.explanation,
                    "confidence_score": f.confidence_score,
                    "detected_at":      f.detected_at.isoformat() if f.detected_at else "",
                    "acknowledged":     f.acknowledged,
                }
                for f in flags
            ]
        finally:
            session.close()

    # ─── INTERNAL HELPERS ────────────────────────────────────────

    def _to_dict(self, p: Patient) -> Dict[str, Any]:
        """Convert Patient ORM model to dict with decrypted fields."""
        return {
            "patient_id":       p.patient_id,
            "name":             self.sec.decrypt(p.name_encrypted),
            "age":              p.age,
            "pregnancy_stage":  p.pregnancy_stage,
            "gestational_weeks": p.gestational_weeks,
            "blood_type":       p.blood_type,
            "medical_notes":    self.sec.decrypt(p.medical_notes_encrypted) if p.medical_notes_encrypted else "",
            "consent_given":    p.consent_given,
            "created_at":       p.created_at.isoformat() if p.created_at else "",
            "updated_at":       p.updated_at.isoformat() if p.updated_at else "",
        }
