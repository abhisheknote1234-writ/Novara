"""
app.py — Novara Streamlit Dashboard
======================================
Physiological Intelligence for Maternal Wellness.

Dual-mode visualization:
  USER MODE:  Emotional energy system with flowing colors
  DOCTOR MODE: Clean clinical interface with metrics + flags

Run: streamlit run novara/app.py
"""
import os
import sys
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# ─── Setup path so novara package is importable ──────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novara.models.database import init_db
from novara.modules.patient_repo import PatientRepository
from novara.modules.baseline_engine import BaselineEngine
from novara.modules.risk_engine import RiskEngine
from novara.modules.sharing import SharingService
from novara.simulation.simulator import Simulator
from novara.config import APP_NAME, APP_TAGLINE


# ─── Page Config ─────────────────────────────────────────────────
st.set_page_config(
    page_title=f"{APP_NAME} — Maternal Wellness",
    page_icon="🫀",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Initialize services (cached) ───────────────────────────────
@st.cache_resource
def init_services():
    init_db()
    return {
        "repo":     PatientRepository(),
        "baseline": BaselineEngine(),
        "risk":     RiskEngine(),
        "sharing":  SharingService(),
        "sim":      Simulator(),
    }

svc = init_services()


# ═══════════════════════════════════════════════════════════════════
#  CSS INJECTION — Premium Design System
# ═══════════════════════════════════════════════════════════════════

def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

    /* ── Global ─────────────────────────────────────────────── */
    .stApp {
        font-family: 'Inter', -apple-system, sans-serif;
    }

    /* ── Sidebar ────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stRadio label {
        color: #94a3b8 !important;
        font-weight: 500;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        font-size: 11px;
    }

    /* ── Metric Cards ───────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 20px 24px;
        transition: all 0.3s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: rgba(255, 255, 255, 0.15);
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
    }
    div[data-testid="stMetric"] label {
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 1.2px !important;
        text-transform: uppercase;
        opacity: 0.6;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-size: 32px !important;
        font-weight: 800 !important;
    }

    /* ── Expander ───────────────────────────────────────────── */
    .streamlit-expanderHeader {
        font-weight: 600;
        font-size: 14px;
    }

    /* ── Custom Title ───────────────────────────────────────── */
    .novara-hero {
        text-align: center;
        padding: 30px 0 20px;
    }
    .novara-hero h1 {
        font-size: 48px;
        font-weight: 900;
        letter-spacing: 8px;
        margin: 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .novara-hero p {
        font-size: 14px;
        letter-spacing: 3px;
        text-transform: uppercase;
        opacity: 0.5;
        margin-top: 4px;
    }

    /* ── Risk Badge ─────────────────────────────────────────── */
    .risk-badge {
        display: inline-block;
        padding: 6px 16px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 11px;
        letter-spacing: 1px;
        text-transform: uppercase;
    }
    .risk-critical { background: #ff1744; color: white; }
    .risk-high     { background: #ff5252; color: white; }
    .risk-moderate { background: #ff9100; color: white; }
    .risk-low      { background: #69f0ae; color: #1a1a2e; }
    .risk-none     { background: #4caf50; color: white; }

    /* ── Section Divider ────────────────────────────────────── */
    .section-divider {
        width: 100%;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
        margin: 24px 0;
    }

    /* ── Doctor Mode Override ────────────────────────────────── */
    .doctor-mode .stApp {
        background: #ffffff !important;
        color: #1a1a2e !important;
    }
    </style>
    """, unsafe_allow_html=True)

inject_css()


# ═══════════════════════════════════════════════════════════════════
#  ENERGY VISUALIZATION — The Emotional State System
# ═══════════════════════════════════════════════════════════════════

def render_energy_field(state: str, stress_val: float = 50, recovery_val: float = 50):
    """
    Render a full-width animated energy field.
    The dominant state drives the visual:
      🔴 Stress = Intense pulsing red
      🔵 Recovery = Slow flowing blue
      🟤 Unstable = Flickering brown/amber
    """
    # Map state to visual parameters
    configs = {
        "stress": {
            "gradient": "radial-gradient(ellipse at 50% 50%, #ff1744, #d50000, #b71c1c, #1a0000)",
            "animation": "stressPulse",
            "speed": "1.5s",
            "label": "⚡ STRESS OVERLOAD",
            "sublabel": f"Stress Index: {stress_val:.0f}/100",
            "glow_color": "rgba(255, 23, 68, 0.4)",
        },
        "recovery": {
            "gradient": "linear-gradient(270deg, #0d47a1, #1565c0, #1e88e5, #42a5f5, #1565c0, #0d47a1)",
            "animation": "recoveryFlow",
            "speed": "8s",
            "label": "🌊 DEEP RECOVERY",
            "sublabel": f"Recovery Score: {recovery_val:.0f}/100",
            "glow_color": "rgba(33, 150, 243, 0.3)",
        },
        "unstable": {
            "gradient": "radial-gradient(ellipse at 30% 70%, #4e342e, #6d4c41, #795548, #8d6e63, #5d4037)",
            "animation": "unstableFlicker",
            "speed": "2.5s",
            "label": "⚠ INSTABILITY DETECTED",
            "sublabel": "Mixed autonomic signals",
            "glow_color": "rgba(121, 85, 72, 0.35)",
        },
    }

    config = configs.get(state, configs["unstable"])

    html = f"""
    <style>
    @keyframes stressPulse {{
        0%   {{ transform: scale(1);    opacity: 0.85; box-shadow: 0 0 60px {config['glow_color']}; }}
        25%  {{ transform: scale(1.02); opacity: 0.95; box-shadow: 0 0 100px {config['glow_color']}; }}
        50%  {{ transform: scale(1.04); opacity: 1;    box-shadow: 0 0 140px {config['glow_color']}; }}
        75%  {{ transform: scale(1.02); opacity: 0.95; box-shadow: 0 0 100px {config['glow_color']}; }}
        100% {{ transform: scale(1);    opacity: 0.85; box-shadow: 0 0 60px {config['glow_color']}; }}
    }}
    @keyframes recoveryFlow {{
        0%   {{ background-position: 0% 50%;   }}
        50%  {{ background-position: 100% 50%; }}
        100% {{ background-position: 0% 50%;   }}
    }}
    @keyframes unstableFlicker {{
        0%   {{ opacity: 0.6; transform: scale(1);    }}
        15%  {{ opacity: 0.9; transform: scale(1.01); }}
        30%  {{ opacity: 0.5; transform: scale(0.99); }}
        50%  {{ opacity: 1;   transform: scale(1.03); }}
        65%  {{ opacity: 0.7; transform: scale(1);    }}
        80%  {{ opacity: 0.85;transform: scale(1.02); }}
        100% {{ opacity: 0.6; transform: scale(1);    }}
    }}
    @keyframes textGlow {{
        0%   {{ text-shadow: 0 0 10px rgba(255,255,255,0.3); }}
        50%  {{ text-shadow: 0 0 30px rgba(255,255,255,0.6), 0 0 60px {config['glow_color']}; }}
        100% {{ text-shadow: 0 0 10px rgba(255,255,255,0.3); }}
    }}
    @keyframes particleDrift {{
        0%   {{ transform: translateY(0) translateX(0);     opacity: 0;   }}
        20%  {{ opacity: 0.8; }}
        80%  {{ opacity: 0.4; }}
        100% {{ transform: translateY(-120px) translateX(30px); opacity: 0; }}
    }}
    .energy-container {{
        position: relative;
        width: 100%;
        height: 380px;
        border-radius: 24px;
        overflow: hidden;
        margin: 16px 0 24px;
    }}
    .energy-field {{
        width: 100%;
        height: 100%;
        background: {config['gradient']};
        background-size: 400% 400%;
        animation: {config['animation']} {config['speed']} ease infinite;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        position: relative;
    }}
    .energy-label {{
        font-family: 'Inter', sans-serif;
        font-size: 28px;
        font-weight: 900;
        color: white;
        letter-spacing: 6px;
        text-transform: uppercase;
        animation: textGlow 3s ease infinite;
        z-index: 2;
    }}
    .energy-sublabel {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        font-weight: 400;
        color: rgba(255, 255, 255, 0.7);
        letter-spacing: 2px;
        margin-top: 12px;
        z-index: 2;
    }}
    /* Particle overlay */
    .particle {{
        position: absolute;
        width: 4px;
        height: 4px;
        background: rgba(255, 255, 255, 0.5);
        border-radius: 50%;
        animation: particleDrift 4s ease-in-out infinite;
    }}
    .particle:nth-child(1) {{ left: 15%; bottom: 20%; animation-delay: 0s;   animation-duration: 3.5s; }}
    .particle:nth-child(2) {{ left: 35%; bottom: 10%; animation-delay: 0.8s; animation-duration: 4.2s; }}
    .particle:nth-child(3) {{ left: 55%; bottom: 30%; animation-delay: 1.5s; animation-duration: 3.8s; }}
    .particle:nth-child(4) {{ left: 75%; bottom: 15%; animation-delay: 0.3s; animation-duration: 4.5s; }}
    .particle:nth-child(5) {{ left: 90%; bottom: 25%; animation-delay: 2.0s; animation-duration: 3.2s; }}
    .particle:nth-child(6) {{ left: 25%; bottom: 40%; animation-delay: 1.2s; animation-duration: 5.0s; }}
    .particle:nth-child(7) {{ left: 65%; bottom: 5%;  animation-delay: 0.6s; animation-duration: 4.0s; }}
    .particle:nth-child(8) {{ left: 45%; bottom: 50%; animation-delay: 1.8s; animation-duration: 3.6s; }}
    </style>

    <div class="energy-container">
        <div class="energy-field">
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="particle"></div>
            <div class="energy-label">{config['label']}</div>
            <div class="energy-sublabel">{config['sublabel']}</div>
        </div>
    </div>
    """
    st.components.v1.html(html, height=420)


def get_dominant_state(stress: float, recovery: float, hrv_rmssd: float) -> str:
    """Determine the dominant physiological state from metrics."""
    if stress > 70:
        return "stress"
    elif recovery > 60 and hrv_rmssd > 35:
        return "recovery"
    else:
        return "unstable"


# ═══════════════════════════════════════════════════════════════════
#  DOCTOR MODE COMPONENTS
# ═══════════════════════════════════════════════════════════════════

def render_clinical_header(patient: dict):
    """Clean clinical header for doctor mode."""
    st.markdown(f"""
    <div style="background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px;
                padding: 20px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-size: 18px; font-weight: 700; color: #212529;">
                    {patient['name']}
                </span>
                <span style="font-size: 13px; color: #6c757d; margin-left: 12px;">
                    ID: {patient['patient_id'][:8]}
                </span>
            </div>
            <div style="text-align: right;">
                <span style="font-size: 13px; color: #495057;">
                    Age: {patient['age']} │ 
                    {patient['pregnancy_stage'].replace('_',' ').title()} │
                    {patient['gestational_weeks']} weeks │
                    Blood: {patient.get('blood_type', 'N/A')}
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
#  CHART BUILDERS
# ═══════════════════════════════════════════════════════════════════

def build_trend_chart(logs: list, metric_key: str, title: str, color: str, 
                      unit: str = "", baseline_val: float = None) -> go.Figure:
    """Build a Plotly trend chart with baseline reference."""
    sorted_logs = sorted(logs, key=lambda x: x["log_date"])
    dates  = [l["log_date"] for l in sorted_logs]
    values = [l[metric_key] for l in sorted_logs]

    fig = go.Figure()

    # Main trend line
    fig.add_trace(go.Scatter(
        x=dates, y=values, mode="lines+markers",
        name=title,
        line=dict(color=color, width=3),
        marker=dict(size=6, color=color),
        fill="tozeroy",
        fillcolor=f"rgba{tuple(list(px.colors.hex_to_rgb(color)) + [0.08])}",
    ))

    # Baseline reference line
    if baseline_val is not None:
        fig.add_hline(
            y=baseline_val, line_dash="dash", line_color="#888",
            annotation_text=f"Baseline: {baseline_val:.1f}{unit}",
            annotation_position="top right",
            annotation_font_size=10,
            annotation_font_color="#888",
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, family="Inter")),
        xaxis=dict(title="", showgrid=False),
        yaxis=dict(title=unit, showgrid=True, gridcolor="rgba(0,0,0,0.05)"),
        height=280,
        margin=dict(l=40, r=20, t=50, b=30),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter"),
        showlegend=False,
    )
    return fig


# ═══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 20px 0;">
        <div style="font-size: 36px; font-weight: 900; letter-spacing: 6px;
                    background: linear-gradient(135deg, #667eea, #764ba2, #f093fb);
                    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                    background-clip: text;">
            NOVARA
        </div>
        <div style="font-size: 9px; letter-spacing: 3px; opacity: 0.5; margin-top: 4px;
                    text-transform: uppercase;">
            Physiological Intelligence
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Mode toggle
    view_mode = st.radio(
        "DASHBOARD MODE",
        ["👁 User Mode", "🩺 Doctor Mode"],
        index=0,
        help="User Mode: emotional color visualization | Doctor Mode: clinical metrics"
    )
    is_doctor_mode = "Doctor" in view_mode

    st.markdown("---")

    # Seed demo data
    if st.button("🧬 Generate Demo Data", use_container_width=True):
        with st.spinner("Creating 5 demo patients with 14 days of data..."):
            svc["sim"].seed_all(days=14)
        st.success("✓ Demo data generated!")
        st.rerun()

    st.markdown("---")

    # Patient selection
    patients = svc["repo"].list_patients()
    if patients:
        patient_names = {p["patient_id"]: f"{p['name']} ({p['pregnancy_stage'].replace('_',' ').title()})" 
                        for p in patients}
        selected_id = st.selectbox(
            "SELECT PATIENT",
            options=list(patient_names.keys()),
            format_func=lambda x: patient_names[x],
        )
    else:
        selected_id = None
        st.info("No patients yet. Click **Generate Demo Data** to start.")

    st.markdown("---")

    # Actions
    if selected_id:
        st.markdown("##### ACTIONS")

        if st.button("🔍 Run Risk Evaluation", use_container_width=True):
            with st.spinner("Analyzing risk patterns..."):
                flags = svc["risk"].evaluate(selected_id)
            if flags:
                st.warning(f"⚠ {len(flags)} risk pattern(s) detected")
            else:
                st.success("✓ No new risk patterns")

        if st.button("📊 Compute Baseline", use_container_width=True):
            with st.spinner("Computing baseline..."):
                bl = svc["baseline"].compute_baseline(selected_id)
            if bl:
                st.success(f"✓ Baseline computed from {bl['days_used']} days")
            else:
                st.warning("Need at least 3 days of data")

        if st.button("📄 Generate PDF Report", use_container_width=True):
            with st.spinner("Generating clinical report..."):
                result = svc["sharing"].generate_report(selected_id)
            if result["success"]:
                st.success(result["message"])
                with open(result["file_path"], "rb") as f:
                    st.download_button(
                        "⬇ Download Report",
                        data=f.read(),
                        file_name=os.path.basename(result["file_path"]),
                        mime="application/pdf",
                        use_container_width=True,
                    )
            else:
                st.error(result["message"])


# ═══════════════════════════════════════════════════════════════════
#  MAIN CONTENT AREA
# ═══════════════════════════════════════════════════════════════════

if not selected_id:
    # Landing page
    st.markdown("""
    <div class="novara-hero">
        <h1>NOVARA</h1>
        <p>Physiological Intelligence for Maternal Wellness</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 🫀 Monitor")
        st.markdown("Track heart rate, HRV, stress, and recovery in real-time with personalized baselines.")
    with col2:
        st.markdown("### ⚠️ Detect")
        st.markdown("Rule-based risk detection identifies early warning patterns including preeclampsia indicators.")
    with col3:
        st.markdown("### 📄 Report")
        st.markdown("Generate clinical-grade PDF reports for healthcare providers with full privacy controls.")

else:
    # ─── Load patient data ───────────────────────────────────────
    patient   = svc["repo"].get_patient(selected_id)
    logs      = svc["repo"].get_patient_logs(selected_id, days=30)
    baseline  = svc["baseline"].get_baseline(selected_id)
    flags     = svc["repo"].get_risk_flags(selected_id, active_only=False)

    latest = logs[0] if logs else {}

    if not is_doctor_mode:
        # ══════════════════════════════════════════════════════════
        #  USER MODE — Emotional Color Energy System
        # ══════════════════════════════════════════════════════════

        # Hero title
        st.markdown(f"""
        <div style="text-align:center; margin-bottom: 8px;">
            <span style="font-size: 14px; font-weight: 600; letter-spacing: 4px;
                        text-transform: uppercase; opacity: 0.5;">
                Monitoring
            </span>
            <h2 style="font-size: 28px; font-weight: 800; margin: 4px 0;">
                {patient['name']}
            </h2>
            <span style="font-size: 12px; opacity: 0.4;">
                {patient['pregnancy_stage'].replace('_',' ').title()} · 
                Week {patient['gestational_weeks']} · 
                Age {patient['age']}
            </span>
        </div>
        """, unsafe_allow_html=True)

        # ─── Energy Field ────────────────────────────────────────
        stress_val   = latest.get("avg_stress_score", 50)
        recovery_val = latest.get("avg_recovery_score", 50)
        rmssd_val    = latest.get("avg_hrv_rmssd", 30)

        state = get_dominant_state(stress_val, recovery_val, rmssd_val)
        render_energy_field(state, stress_val, recovery_val)

        # ─── Metric Cards ────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            hr = latest.get("avg_heart_rate", 0)
            delta_hr = None
            if baseline:
                delta_hr = f"{hr - baseline['baseline_hr']:+.1f} bpm"
            st.metric("Heart Rate", f"{hr:.0f} bpm", delta=delta_hr,
                      delta_color="inverse")

        with col2:
            rmssd = latest.get("avg_hrv_rmssd", 0)
            delta_rmssd = None
            if baseline:
                delta_rmssd = f"{rmssd - baseline['baseline_hrv_rmssd']:+.1f} ms"
            st.metric("HRV (RMSSD)", f"{rmssd:.1f} ms", delta=delta_rmssd)

        with col3:
            stress = latest.get("avg_stress_score", 0)
            delta_stress = None
            if baseline:
                delta_stress = f"{stress - baseline['baseline_stress']:+.1f}"
            st.metric("Stress Score", f"{stress:.0f}/100", delta=delta_stress,
                      delta_color="inverse")

        with col4:
            recov = latest.get("avg_recovery_score", 0)
            delta_recov = None
            if baseline:
                delta_recov = f"{recov - baseline['baseline_recovery']:+.1f}"
            st.metric("Recovery", f"{recov:.0f}/100", delta=delta_recov)

        st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        # ─── Risk Alerts ─────────────────────────────────────────
        if flags:
            st.markdown("### ⚠️ Risk Alerts")
            for flag in flags:
                sev = flag['severity']
                badge_class = f"risk-{sev}"
                icon = {"critical": "🔴", "high": "🟠", "moderate": "🟡", "low": "🟢"}.get(sev, "⚪")

                with st.expander(
                    f"{icon} {flag['flag_type'].replace('_', ' ').upper()} — {sev.upper()} "
                    f"(Confidence: {flag['confidence_score']:.0%})",
                    expanded=(sev in ["critical", "high"])
                ):
                    st.markdown(flag["explanation"])
                    st.caption(f"Detected: {flag.get('detected_at', 'N/A')}")

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

        # ─── Trend Charts ────────────────────────────────────────
        if logs and len(logs) > 1:
            st.markdown("### 📈 Physiological Trends")

            tab1, tab2, tab3, tab4 = st.tabs(["Heart Rate", "HRV", "Stress", "Recovery"])

            baseline_hr    = baseline["baseline_hr"]        if baseline else None
            baseline_rmssd = baseline["baseline_hrv_rmssd"] if baseline else None
            baseline_str   = baseline["baseline_stress"]    if baseline else None
            baseline_rec   = baseline["baseline_recovery"]  if baseline else None

            with tab1:
                fig = build_trend_chart(logs, "avg_heart_rate", "Heart Rate",
                                       "#e86080", " bpm", baseline_hr)
                st.plotly_chart(fig, use_container_width=True)

            with tab2:
                fig = build_trend_chart(logs, "avg_hrv_rmssd", "HRV (RMSSD)",
                                       "#4facfe", " ms", baseline_rmssd)
                st.plotly_chart(fig, use_container_width=True)

            with tab3:
                fig = build_trend_chart(logs, "avg_stress_score", "Stress Score",
                                       "#ff5252", "", baseline_str)
                st.plotly_chart(fig, use_container_width=True)

            with tab4:
                fig = build_trend_chart(logs, "avg_recovery_score", "Recovery Score",
                                       "#69f0ae", "", baseline_rec)
                st.plotly_chart(fig, use_container_width=True)

        # ─── Baseline comparison ─────────────────────────────────
        if baseline and latest:
            st.markdown("### 📊 Baseline Comparison")
            comparison = svc["baseline"].compare_to_baseline(selected_id, latest)
            if comparison:
                c1, c2, c3 = st.columns(3)
                with c1:
                    val = comparison["hr_deviation_pct"]
                    color = "#ff5252" if abs(val) > 15 else ("#ff9100" if abs(val) > 7 else "#69f0ae")
                    st.markdown(f"""
                    <div style="text-align:center; padding: 16px; border-radius: 12px;
                                border: 1px solid rgba(255,255,255,0.08);">
                        <div style="font-size: 11px; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase;">
                            HR Deviation
                        </div>
                        <div style="font-size: 32px; font-weight: 800; color: {color};">
                            {val:+.1f}%
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with c2:
                    val = comparison["hrv_rmssd_deviation_pct"]
                    color = "#ff5252" if val < -25 else ("#ff9100" if val < -10 else "#69f0ae")
                    st.markdown(f"""
                    <div style="text-align:center; padding: 16px; border-radius: 12px;
                                border: 1px solid rgba(255,255,255,0.08);">
                        <div style="font-size: 11px; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase;">
                            HRV Deviation
                        </div>
                        <div style="font-size: 32px; font-weight: 800; color: {color};">
                            {val:+.1f}%
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with c3:
                    val = comparison["stress_deviation_pct"]
                    color = "#ff5252" if val > 20 else ("#ff9100" if val > 10 else "#69f0ae")
                    st.markdown(f"""
                    <div style="text-align:center; padding: 16px; border-radius: 12px;
                                border: 1px solid rgba(255,255,255,0.08);">
                        <div style="font-size: 11px; opacity: 0.5; letter-spacing: 1px; text-transform: uppercase;">
                            Stress Deviation
                        </div>
                        <div style="font-size: 32px; font-weight: 800; color: {color};">
                            {val:+.1f}%
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    else:
        # ══════════════════════════════════════════════════════════
        #  DOCTOR MODE — Clean Clinical Interface
        # ══════════════════════════════════════════════════════════

        render_clinical_header(patient)

        # ─── Clinical Metrics Table ──────────────────────────────
        st.markdown("#### Current Physiological Status")

        if latest:
            metrics_data = {
                "Metric": ["Heart Rate", "HRV (RMSSD)", "HRV (SDNN)", "Stress Index", "Recovery Index",
                          "HR Range"],
                "Current Value": [
                    f"{latest.get('avg_heart_rate', 0):.1f} bpm",
                    f"{latest.get('avg_hrv_rmssd', 0):.1f} ms",
                    f"{latest.get('avg_hrv_sdnn', 0):.1f} ms",
                    f"{latest.get('avg_stress_score', 0):.1f} / 100",
                    f"{latest.get('avg_recovery_score', 0):.1f} / 100",
                    f"{latest.get('min_heart_rate', 0):.0f} – {latest.get('max_heart_rate', 0):.0f} bpm",
                ],
                "Baseline": [
                    f"{baseline['baseline_hr']:.1f} bpm" if baseline else "—",
                    f"{baseline['baseline_hrv_rmssd']:.1f} ms" if baseline else "—",
                    f"{baseline['baseline_hrv_sdnn']:.1f} ms" if baseline else "—",
                    f"{baseline['baseline_stress']:.1f}" if baseline else "—",
                    f"{baseline['baseline_recovery']:.1f}" if baseline else "—",
                    "—",
                ],
            }

            if baseline and latest:
                comparison = svc["baseline"].compare_to_baseline(selected_id, latest)
                if comparison:
                    metrics_data["Deviation"] = [
                        f"{comparison.get('hr_deviation_pct', 0):+.1f}%",
                        f"{comparison.get('hrv_rmssd_deviation_pct', 0):+.1f}%",
                        f"{comparison.get('hrv_sdnn_deviation_pct', 0):+.1f}%",
                        f"{comparison.get('stress_deviation_pct', 0):+.1f}%",
                        f"{comparison.get('recovery_deviation_pct', 0):+.1f}%",
                        "—",
                    ]

            df = pd.DataFrame(metrics_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No daily log data available for this patient.")

        st.markdown("---")

        # ─── Risk Flags Table (Clinical) ─────────────────────────
        st.markdown("#### Risk Assessment")

        if flags:
            risk_data = {
                "Flag": [f["flag_type"].replace("_", " ").title() for f in flags],
                "Severity": [f["severity"].upper() for f in flags],
                "Confidence": [f"{f['confidence_score']:.0%}" for f in flags],
                "Detected": [f.get("detected_at", "N/A")[:19] for f in flags],
                "Status": ["Active" if not f["acknowledged"] else "Acknowledged" for f in flags],
            }
            df_risk = pd.DataFrame(risk_data)
            st.dataframe(df_risk, use_container_width=True, hide_index=True)

            # Detailed explanations
            for flag in flags:
                with st.expander(f"{flag['flag_type'].replace('_', ' ').title()} — Details"):
                    st.markdown(flag["explanation"])
        else:
            st.success("No risk patterns detected. All parameters within expected ranges.")

        st.markdown("---")

        # ─── Trend Data (Clinical Charts) ────────────────────────
        if logs and len(logs) > 1:
            st.markdown("#### Physiological Trend Data")

            sorted_logs = sorted(logs, key=lambda x: x["log_date"])
            df_logs = pd.DataFrame(sorted_logs)

            tab1, tab2 = st.tabs(["Charts", "Raw Data"])

            with tab1:
                c1, c2 = st.columns(2)
                with c1:
                    fig_hr = build_trend_chart(logs, "avg_heart_rate", "Heart Rate",
                                              "#333333", " bpm",
                                              baseline["baseline_hr"] if baseline else None)
                    fig_hr.update_layout(
                        plot_bgcolor="white", paper_bgcolor="white",
                        font=dict(color="#333"),
                    )
                    st.plotly_chart(fig_hr, use_container_width=True)

                with c2:
                    fig_hrv = build_trend_chart(logs, "avg_hrv_rmssd", "HRV (RMSSD)",
                                               "#555555", " ms",
                                               baseline["baseline_hrv_rmssd"] if baseline else None)
                    fig_hrv.update_layout(
                        plot_bgcolor="white", paper_bgcolor="white",
                        font=dict(color="#333"),
                    )
                    st.plotly_chart(fig_hrv, use_container_width=True)

            with tab2:
                st.dataframe(df_logs, use_container_width=True, hide_index=True)

        # ─── Patient Notes ───────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Clinical Notes")
        st.text_area(
            "Medical Notes",
            value=patient.get("medical_notes", ""),
            disabled=True,
            height=100,
            label_visibility="collapsed",
        )
        st.caption(f"Consent Status: {'✓ Granted' if patient['consent_given'] else '✗ Not Granted'}")


# ─── Footer ──────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity: 0.3; font-size: 11px; padding: 8px;'>"
    "NOVARA v1.0 · Physiological Intelligence for Maternal Wellness · "
    "Not a medical device. Risk patterns only — consult a healthcare provider."
    "</div>",
    unsafe_allow_html=True,
)
