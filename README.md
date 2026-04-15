# NOVARA

**Physiological Intelligence for Maternal Wellness**

A modular Python dashboard for pregnancy monitoring that stores patient profiles, logs physiological data, builds personalized baselines, detects risk patterns, and generates clinical-grade reports — all with encryption and privacy controls.

> ⚠️ **DISCLAIMER**: Novara identifies *risk patterns*, NOT medical diagnoses. All flags must be reviewed by a qualified healthcare provider. Do not make clinical decisions based solely on this system's output.

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd Novara
pip install -r requirements.txt
```

### 2. Launch Dashboard

```bash
# Basic launch
python run.py

# Or seed demo data first
python run.py --seed

# Or initialize database only
python run.py --init
```

### 3. Open Browser

Navigate to **http://localhost:8501**

---

## ⚡ ARC Real-Time API + Frontend (FastAPI)

New real-time A-R-C stack is available at:

- Backend: `/arc.dashboard/backend/main.py`
- Frontend: `/arc.dashboard/frontend/index.html`

### Run backend

```bash
uvicorn main:app --app-dir arc.dashboard/backend --host 0.0.0.0 --port 8000 --reload
```

### API routes

- `POST /api/ingest-data` → send raw ECG/PPG/EMG batches
- `GET /api/process-data` → latest A/R/C + HRV features
- `WS /ws/stream` → stream ingestion + real-time A/R/C updates

### Frontend integration

- Replace simulated calls with `GET /api/process-data` polling and/or `WS /ws/stream`
- Use `window.pushRawSignals({ sampling_rate, signals: { ecg, ppg, emg } })` in `arc.dashboard/frontend/app.js`

---

## 📁 Project Structure

```
Novara/
├── novara/                          # Main application package
│   ├── app.py                       # Streamlit dashboard (dual-mode)
│   ├── config.py                    # Central configuration
│   ├── models/                      # Database models
│   │   ├── database.py              # SQLite engine + sessions
│   │   └── patient.py               # ORM: Patient, DailyLog, Baseline, RiskFlag
│   ├── modules/                     # Core business logic
│   │   ├── patient_repo.py          # Patient CRUD operations
│   │   ├── data_pipeline.py         # Signal processing (HR, HRV, stress)
│   │   ├── baseline_engine.py       # Personalized baseline computation
│   │   ├── risk_engine.py           # Rule-based risk detection
│   │   ├── report_generator.py      # PDF report generation
│   │   ├── security.py              # Encryption + consent + anonymization
│   │   └── sharing.py               # Report sharing + access tokens
│   └── simulation/                  # Demo data generators
│       └── simulator.py             # 5 patient scenarios
├── data/                            # SQLite database + encryption keys
├── reports/                         # Generated PDF reports
├── requirements.txt
├── run.py                           # Entry point
└── README.md
```

---

## 🏥 Modules

### 1. Patient Repository
- Encrypted patient profiles (Fernet)
- UUID-based patient IDs
- Full CRUD operations
- Daily physiological log management

### 2. Data Pipeline
- Standalone signal processing (no MaternalGuard dependency)
- Simplified Pan-Tompkins R-peak detection
- HRV computation (RMSSD, SDNN)
- Stress score (0-100, autonomic balance estimate)
- Recovery score (0-100, parasympathetic reactivation)

### 3. Baseline Engine
- Computes personalized baselines from first 3-5 days
- Tracks deviation percentages from baseline
- Auto-updates when sufficient data is available

### 4. Risk Detection Engine (Rule-Based)
| Rule | Condition | Severity |
|------|-----------|----------|
| Sustained High Stress | Stress >70 for 3+ consecutive days | Moderate / High |
| HRV Drop | RMSSD >25% below baseline | Moderate / High / Critical |
| Abnormal HR | HR >100 or <55 sustained | Moderate / High |
| Preeclampsia Pattern | Composite (elevated HR + HRV decline + stress + late trimester) | High / Critical |

### 5. Report Generator
- Clinical-grade PDF (ReportLab)
- Embedded trend charts (Matplotlib)
- Patient summary, baseline comparison, risk assessment
- Full clinical disclaimer

### 6. Security & Privacy
- Fernet symmetric encryption for PII
- Consent gating before sharing
- Patient data anonymization
- Time-limited access tokens

### 7. Dashboard (Streamlit)
- **User Mode**: Emotional energy visualization (red=stress, blue=recovery, brown=unstable)
- **Doctor Mode**: Clean clinical interface with tables and metrics
- Interactive trend charts (Plotly)
- Risk alert panel
- PDF report download

---

## 🎨 Dual-Mode Visualization

### User Mode
Big, animated energy fields that show the dominant physiological state at a glance:
- 🔴 **Stress Overload** — Pulsing red with particle effects
- 🔵 **Deep Recovery** — Flowing blue gradient
- 🟤 **Instability** — Flickering brown

### Doctor Mode
Clean clinical interface:
- Tabular metrics with baseline deviation percentages
- Risk flags with severity and confidence scores
- Raw data export
- No emotional colors — purely clinical

---

## 🧬 Demo Scenarios

The simulator creates 5 patients with different scenarios:

| Patient | Scenario | Expected Outcome |
|---------|----------|-----------------|
| Priya Sharma | Normal | No risk flags |
| Ananya Patel | High Stress | Sustained stress flag |
| Meera Reddy | Preeclampsia Risk | Preeclampsia pattern + HRV drop |
| Kavita Singh | Recovery Focused | Good recovery, no flags |
| Deepa Nair | Unstable | Variable patterns |

---

## 🔒 Privacy & Safety

- Patient names and medical notes are **encrypted at rest** (Fernet)
- Sharing requires **explicit consent**
- Anonymization available for research exports
- Access tokens expire after 24 hours
- All risk flags include mandatory clinical disclaimers
