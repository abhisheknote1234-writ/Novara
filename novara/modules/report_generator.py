"""
report_generator.py — Clinical PDF Report Generator
======================================================
Generates doctor-readable PDF reports using ReportLab.
Includes patient summary, baseline comparison, trend charts,
risk flags, and clinical disclaimers.
"""
import os
import io
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from novara.config import REPORTS_DIR


class ReportGenerator:
    """
    Generates a clinical-grade PDF report for a patient.
    
    Sections:
      1. Header + Patient Summary
      2. Baseline Metrics
      3. Current vs Baseline Comparison
      4. Trend Charts (HR, HRV, Stress over time)
      5. Risk Assessment
      6. Clinical Disclaimer
    """

    def __init__(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        self._styles = getSampleStyleSheet()
        self._add_custom_styles()

    def _add_custom_styles(self):
        """Add custom paragraph styles for clinical report."""
        self._styles.add(ParagraphStyle(
            name="ReportTitle",
            parent=self._styles["Title"],
            fontSize=22,
            spaceAfter=6,
            textColor=colors.HexColor("#2d2d3f"),
            fontName="Helvetica-Bold",
        ))
        self._styles.add(ParagraphStyle(
            name="SectionHead",
            parent=self._styles["Heading2"],
            fontSize=13,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#3a3a50"),
            fontName="Helvetica-Bold",
        ))
        self._styles.add(ParagraphStyle(
            name="ClinicalBody",
            parent=self._styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#444444"),
        ))
        self._styles.add(ParagraphStyle(
            name="Disclaimer",
            parent=self._styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#888888"),
            fontName="Helvetica-Oblique",
        ))
        self._styles.add(ParagraphStyle(
            name="SubInfo",
            parent=self._styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#666666"),
        ))

    def generate(
        self,
        patient: Dict,
        baseline: Optional[Dict],
        logs: List[Dict],
        risk_flags: List[Dict],
        comparison: Optional[Dict] = None,
    ) -> str:
        """
        Generate the full patient report PDF.
        
        Args:
            patient:     Decrypted patient dict
            baseline:    Baseline metrics dict (or None)
            logs:        List of daily log dicts
            risk_flags:  List of risk flag dicts
            comparison:  Baseline vs current comparison dict (or None)
        
        Returns:
            Absolute path to generated PDF file.
        """
        pid  = patient["patient_id"][:8]
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"novara_report_{pid}_{date}.pdf"
        filepath = os.path.join(REPORTS_DIR, filename)

        doc = SimpleDocTemplate(
            filepath, pagesize=A4,
            rightMargin=20*mm, leftMargin=20*mm,
            topMargin=20*mm, bottomMargin=20*mm,
        )

        story = []

        # 1. Header
        story.extend(self._build_header(patient))

        # 2. Patient Summary
        story.extend(self._build_patient_summary(patient))

        # 3. Baseline Section
        if baseline:
            story.extend(self._build_baseline_section(baseline))

        # 4. Comparison Table
        if comparison:
            story.extend(self._build_comparison_section(comparison))

        # 5. Trend Charts
        if logs:
            story.extend(self._build_trend_charts(logs))

        # 6. Risk Assessment
        story.extend(self._build_risk_section(risk_flags))

        # 7. Disclaimer
        story.extend(self._build_disclaimer())

        # Build PDF
        doc.build(story)
        return filepath

    # ─── Section Builders ────────────────────────────────────────

    def _build_header(self, patient: Dict) -> list:
        """Report header with title and generation info."""
        elements = []
        elements.append(Paragraph("NOVARA", self._styles["ReportTitle"]))
        elements.append(Paragraph(
            "Physiological Intelligence Report — Maternal Wellness Monitoring",
            self._styles["SubInfo"]
        ))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M UTC')}",
            self._styles["SubInfo"]
        ))
        elements.append(HRFlowable(
            width="100%", thickness=1,
            color=colors.HexColor("#e0e0e0"),
            spaceAfter=12, spaceBefore=8,
        ))
        return elements

    def _build_patient_summary(self, patient: Dict) -> list:
        """Patient demographics and pregnancy info."""
        elements = []
        elements.append(Paragraph("Patient Summary", self._styles["SectionHead"]))

        stage_display = patient["pregnancy_stage"].replace("_", " ").title()
        data = [
            ["Field", "Value"],
            ["Patient ID",       patient["patient_id"][:8] + "..."],
            ["Age",              str(patient["age"])],
            ["Pregnancy Stage",  stage_display],
            ["Gestational Age",  f"{patient['gestational_weeks']} weeks"],
            ["Blood Type",       patient.get("blood_type", "Unknown")],
            ["Consent Status",   "✓ Granted" if patient["consent_given"] else "✗ Not Granted"],
        ]

        table = Table(data, colWidths=[150, 300])
        table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#f0f0f8")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.HexColor("#3a3a50")),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        return elements

    def _build_baseline_section(self, baseline: Dict) -> list:
        """Baseline metrics table."""
        elements = []
        elements.append(Paragraph("Established Baseline", self._styles["SectionHead"]))
        elements.append(Paragraph(
            f"Computed from the first {baseline['days_used']} days of monitoring data.",
            self._styles["ClinicalBody"]
        ))

        data = [
            ["Metric", "Baseline Value"],
            ["Heart Rate",      f"{baseline['baseline_hr']:.1f} bpm"],
            ["HRV (RMSSD)",     f"{baseline['baseline_hrv_rmssd']:.1f} ms"],
            ["HRV (SDNN)",      f"{baseline['baseline_hrv_sdnn']:.1f} ms"],
            ["Stress Score",    f"{baseline['baseline_stress']:.1f} / 100"],
            ["Recovery Score",  f"{baseline['baseline_recovery']:.1f} / 100"],
        ]

        table = Table(data, colWidths=[200, 250])
        table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        return elements

    def _build_comparison_section(self, comparison: Dict) -> list:
        """Current vs baseline comparison table."""
        elements = []
        elements.append(Paragraph("Current vs. Baseline Comparison", self._styles["SectionHead"]))

        def dev_format(val):
            if val > 0:
                return f"↑ +{val:.1f}%"
            elif val < 0:
                return f"↓ {val:.1f}%"
            else:
                return "— 0.0%"

        data = [
            ["Metric", "Deviation from Baseline", "Status"],
            ["Heart Rate",
             dev_format(comparison.get("hr_deviation_pct", 0)),
             self._deviation_status(comparison.get("hr_deviation_pct", 0), 15)],
            ["HRV (RMSSD)",
             dev_format(comparison.get("hrv_rmssd_deviation_pct", 0)),
             self._deviation_status(-comparison.get("hrv_rmssd_deviation_pct", 0), 25)],
            ["Stress Score",
             dev_format(comparison.get("stress_deviation_pct", 0)),
             self._deviation_status(comparison.get("stress_deviation_pct", 0), 20)],
            ["Recovery Score",
             dev_format(comparison.get("recovery_deviation_pct", 0)),
             self._deviation_status(-comparison.get("recovery_deviation_pct", 0), 20)],
        ]

        table = Table(data, colWidths=[150, 180, 120])
        table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#fff3e0")),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))
        return elements

    def _build_trend_charts(self, logs: List[Dict]) -> list:
        """Generate trend charts as embedded images."""
        elements = []
        elements.append(Paragraph("Physiological Trends", self._styles["SectionHead"]))

        sorted_logs = sorted(logs, key=lambda x: x["log_date"])
        dates = [l["log_date"] for l in sorted_logs]

        # Chart 1: Heart Rate trend
        hrs = [l["avg_heart_rate"] for l in sorted_logs]
        hr_chart = self._create_line_chart(
            dates, hrs, "Heart Rate (bpm)", "#e86080", "Heart Rate Trend"
        )
        if hr_chart:
            elements.append(Image(hr_chart, width=450, height=180))
            elements.append(Spacer(1, 8))

        # Chart 2: HRV (RMSSD) trend
        rmssd = [l["avg_hrv_rmssd"] for l in sorted_logs]
        hrv_chart = self._create_line_chart(
            dates, rmssd, "HRV RMSSD (ms)", "#4facfe", "HRV Trend"
        )
        if hrv_chart:
            elements.append(Image(hrv_chart, width=450, height=180))
            elements.append(Spacer(1, 8))

        # Chart 3: Stress Score trend
        stress = [l["avg_stress_score"] for l in sorted_logs]
        stress_chart = self._create_line_chart(
            dates, stress, "Stress Score", "#ff8a8a", "Stress Trend"
        )
        if stress_chart:
            elements.append(Image(stress_chart, width=450, height=180))
            elements.append(Spacer(1, 12))

        return elements

    def _build_risk_section(self, risk_flags: List[Dict]) -> list:
        """Risk assessment section."""
        elements = []
        elements.append(Paragraph("Risk Assessment", self._styles["SectionHead"]))

        if not risk_flags:
            elements.append(Paragraph(
                "No risk patterns have been detected based on the current data. "
                "All monitored parameters are within expected ranges.",
                self._styles["ClinicalBody"]
            ))
        else:
            for flag in risk_flags:
                severity_color = {
                    "low": "#4caf50", "moderate": "#ff9800",
                    "high": "#f44336", "critical": "#b71c1c",
                }.get(flag["severity"], "#666")

                elements.append(Paragraph(
                    f'<font color="{severity_color}">■</font> '
                    f'<b>{flag["flag_type"].replace("_", " ").upper()}</b> '
                    f'— Severity: {flag["severity"].upper()} '
                    f'(Confidence: {flag["confidence_score"]:.0%})',
                    self._styles["ClinicalBody"]
                ))
                elements.append(Paragraph(
                    flag["explanation"].replace("\n", "<br/>"),
                    self._styles["ClinicalBody"]
                ))
                elements.append(Spacer(1, 8))

        elements.append(Spacer(1, 12))
        return elements

    def _build_disclaimer(self) -> list:
        """Legal / clinical disclaimer."""
        elements = []
        elements.append(HRFlowable(
            width="100%", thickness=0.5,
            color=colors.HexColor("#cccccc"),
            spaceAfter=8, spaceBefore=12,
        ))
        elements.append(Paragraph(
            "<b>IMPORTANT DISCLAIMER</b>",
            self._styles["Disclaimer"]
        ))
        elements.append(Paragraph(
            "This report is generated by the Novara Physiological Intelligence System "
            "and is intended for informational purposes only. It does NOT constitute a "
            "medical diagnosis, prescription, or treatment recommendation. The risk "
            "patterns identified are derived from statistical analysis of physiological "
            "signals and should be interpreted by a qualified healthcare provider in "
            "conjunction with clinical examination, laboratory results, and the patient's "
            "complete medical history. Do not make clinical decisions based solely on "
            "this report. The Novara system is designed to assist healthcare professionals "
            "with early pattern recognition, not to replace clinical judgment.",
            self._styles["Disclaimer"]
        ))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            f"Report generated by Novara v1.0 — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
            self._styles["Disclaimer"]
        ))
        return elements

    # ─── Chart Helpers ───────────────────────────────────────────

    def _create_line_chart(
        self, dates: list, values: list, ylabel: str, color: str, title: str
    ) -> Optional[io.BytesIO]:
        """Create a trend line chart and return as BytesIO image."""
        if not dates or not values:
            return None

        fig, ax = plt.subplots(figsize=(7, 2.5))
        fig.patch.set_facecolor("#fafafa")
        ax.set_facecolor("#fafafa")

        x = range(len(dates))
        ax.plot(x, values, color=color, linewidth=2, marker="o", markersize=4)
        ax.fill_between(x, values, alpha=0.12, color=color)

        ax.set_ylabel(ylabel, fontsize=9, color="#555")
        ax.set_title(title, fontsize=11, fontweight="bold", color="#333", pad=8)
        ax.set_xticks(list(x))
        ax.set_xticklabels(
            [d[-5:] for d in dates],  # Show MM-DD only
            rotation=45, fontsize=7, color="#777"
        )
        ax.tick_params(axis="y", labelsize=8, colors="#777")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#ddd")
        ax.spines["bottom"].set_color("#ddd")
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    def _deviation_status(self, value: float, threshold: float) -> str:
        """Return a status string based on deviation magnitude."""
        abs_val = abs(value)
        if abs_val < threshold * 0.5:
            return "Normal"
        elif abs_val < threshold:
            return "Elevated"
        else:
            return "Concerning"
