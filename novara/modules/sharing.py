"""
sharing.py — Secure Report Sharing System
===========================================
Generates exportable PDF reports with consent gating.
Simulates a doctor access system with time-limited tokens.
"""
import os
from datetime import datetime
from typing import Dict, Optional

from novara.config import REPORTS_DIR
from novara.modules.security import get_security_manager
from novara.modules.patient_repo import PatientRepository
from novara.modules.baseline_engine import BaselineEngine
from novara.modules.risk_engine import RiskEngine
from novara.modules.report_generator import ReportGenerator


class SharingService:
    """
    Secure report sharing with consent gating.
    
    Features:
      - Generate PDF report for a patient
      - Create secure share links (simulated)
      - Validate doctor access tokens
      - Local file export
      - Consent enforcement
    """

    def __init__(self):
        self.sec             = get_security_manager()
        self.patient_repo    = PatientRepository()
        self.baseline_engine = BaselineEngine()
        self.risk_engine     = RiskEngine()
        self.report_gen      = ReportGenerator()

    def generate_report(self, patient_id: str) -> Dict:
        """
        Generate a complete PDF report for a patient.
        
        Returns:
            Dict with: success, file_path, message
        """
        # Get patient data
        patient = self.patient_repo.get_patient(patient_id)
        if not patient:
            return {"success": False, "file_path": "", "message": "Patient not found."}

        # Get logs, baseline, risk flags
        logs       = self.patient_repo.get_patient_logs(patient_id, days=30)
        baseline   = self.baseline_engine.get_baseline(patient_id)
        risk_flags = self.patient_repo.get_risk_flags(patient_id, active_only=False)

        # Comparison
        comparison = None
        if baseline and logs:
            latest = logs[0] if logs else {}
            comparison = self.baseline_engine.compare_to_baseline(patient_id, latest)

        # Generate PDF
        filepath = self.report_gen.generate(
            patient=patient,
            baseline=baseline,
            logs=logs,
            risk_flags=risk_flags,
            comparison=comparison,
        )

        return {
            "success":   True,
            "file_path": filepath,
            "message":   f"Report generated: {os.path.basename(filepath)}",
        }

    def create_share_link(self, patient_id: str, doctor_id: str) -> Dict:
        """
        Create a secure share link for doctor access.
        Enforces consent before sharing.
        
        Returns:
            Dict with: success, token, link, message
        """
        patient = self.patient_repo.get_patient(patient_id)
        if not patient:
            return {"success": False, "token": "", "link": "", "message": "Patient not found."}

        # Enforce consent
        if not patient["consent_given"]:
            return {
                "success": False,
                "token": "",
                "link": "",
                "message": (
                    "Cannot share: patient has not granted consent for data sharing. "
                    "Obtain explicit consent before generating a share link."
                ),
            }

        # Generate token
        token = self.sec.generate_access_token(patient_id, doctor_id)

        # Simulated share link (would be a real URL in production)
        link = f"https://novara.health/report/view?token={token}"

        return {
            "success": True,
            "token":   token,
            "link":    link,
            "message": f"Share link created for Dr. {doctor_id}. Expires in 24 hours.",
        }

    def validate_access(self, token: str) -> Dict:
        """
        Validate a doctor access token.
        Returns patient_id and doctor_id if valid.
        """
        try:
            meta = self.sec.validate_access(token)
            return {
                "valid":      True,
                "patient_id": meta["patient_id"],
                "doctor_id":  meta["doctor_id"],
                "expires_at": meta["expires_at"].isoformat(),
            }
        except PermissionError as e:
            return {"valid": False, "error": str(e)}

    def export_local(self, patient_id: str) -> Dict:
        """
        Generate and export a report to the local reports directory.
        No consent check needed for local export (patient's own device).
        """
        return self.generate_report(patient_id)

    def get_anonymized_report_data(self, patient_id: str) -> Optional[Dict]:
        """
        Get report data with PII stripped for anonymous sharing.
        Useful for research or aggregated reporting.
        """
        patient = self.patient_repo.get_patient(patient_id)
        if not patient:
            return None

        anon_patient = self.sec.anonymize_patient(patient)
        logs         = self.patient_repo.get_patient_logs(patient_id, days=30)
        baseline     = self.baseline_engine.get_baseline(patient_id)
        risk_flags   = self.patient_repo.get_risk_flags(patient_id, active_only=False)

        return {
            "patient":    anon_patient,
            "logs":       logs,
            "baseline":   baseline,
            "risk_flags": risk_flags,
        }
