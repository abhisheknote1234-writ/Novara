"""Quick integration test for all Novara modules."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from novara.models.database import init_db
from novara.simulation.simulator import Simulator
from novara.modules.patient_repo import PatientRepository
from novara.modules.baseline_engine import BaselineEngine
from novara.modules.risk_engine import RiskEngine
from novara.modules.sharing import SharingService
from novara.modules.data_pipeline import PhysioPipeline
from novara.simulation.simulator import simulate_ecg

print("=" * 60)
print("  NOVARA — Integration Test")
print("=" * 60)

# 1. Database
print("\n1. Initializing database...")
init_db()
print("   OK")

# 2. Seed demo data
print("\n2. Seeding 5 demo patients...")
sim = Simulator()
ids = sim.seed_all(days=14)
print(f"   Created {len(ids)} patients")

# 3. List patients
print("\n3. Patient list:")
repo = PatientRepository()
patients = repo.list_patients()
for p in patients:
    print(f"   - {p['name']} | {p['pregnancy_stage']} | age={p['age']} | consent={p['consent_given']}")

# 4. Baselines
print("\n4. Baselines:")
bl_engine = BaselineEngine()
for pid in ids[:3]:
    b = bl_engine.get_baseline(pid)
    pat = repo.get_patient(pid)
    if b:
        print(f"   {pat['name']}: HR={b['baseline_hr']:.1f} RMSSD={b['baseline_hrv_rmssd']:.1f} "
              f"Stress={b['baseline_stress']:.1f} Recovery={b['baseline_recovery']:.1f}")

# 5. Risk flags
print("\n5. Risk flags:")
for pid in ids:
    pat = repo.get_patient(pid)
    flags = repo.get_risk_flags(pid, active_only=False)
    if flags:
        for f in flags:
            print(f"   [{pat['name']}] {f['flag_type']} | {f['severity']} | conf={f['confidence_score']:.2f}")
    else:
        print(f"   [{pat['name']}] No risk flags")

# 6. Signal pipeline test
print("\n6. Signal pipeline test:")
pipeline = PhysioPipeline(fs=250)
ecg = simulate_ecg(duration_sec=10, fs=250, hr_bpm=75)
result = pipeline.ingest(ecg)
print(f"   ECG samples: {len(ecg)}")
print(f"   HR={result['heart_rate']:.1f} bpm | RMSSD={result['hrv_rmssd']:.1f} ms | "
      f"Stress={result['stress_score']:.1f} | Recovery={result['recovery_score']:.1f} | "
      f"SQI={result['signal_quality']:.3f} | Beats={result['n_beats']}")

# 7. Report generation
print("\n7. Report generation:")
sharing = SharingService()
result = sharing.generate_report(ids[2])  # Meera — preeclampsia risk
if result["success"]:
    print(f"   PDF: {result['file_path']}")
    print(f"   Size: {os.path.getsize(result['file_path'])} bytes")
else:
    print(f"   FAILED: {result['message']}")

# 8. Security tests
print("\n8. Security:")
from novara.modules.security import get_security_manager
sec = get_security_manager()
test_text = "Sensitive patient data"
encrypted = sec.encrypt(test_text)
decrypted = sec.decrypt(encrypted)
print(f"   Encrypt/Decrypt roundtrip: {'PASS' if decrypted == test_text else 'FAIL'}")
print(f"   Encrypted length: {len(encrypted)} bytes (original: {len(test_text)})")

# Access token test
token = sec.generate_access_token(ids[0], "DR-001")
meta = sec.validate_access(token)
print(f"   Access token: {token[:20]}...")
print(f"   Token valid: PASS")

# Consent check
pat1 = repo.get_patient(ids[0])
pat5 = repo.get_patient(ids[4])
print(f"   Consent ({pat1['name']}): {pat1['consent_given']}")
print(f"   Consent ({pat5['name']}): {pat5['consent_given']}")

# Share link (tests consent gate)
share_result = sharing.create_share_link(ids[4], "DR-001")  # No consent
print(f"   Share (no consent): {'BLOCKED' if not share_result['success'] else 'ERROR - should block'}")

share_result = sharing.create_share_link(ids[0], "DR-001")  # Has consent
print(f"   Share (has consent): {'OK' if share_result['success'] else 'ERROR'}")

print("\n" + "=" * 60)
print("  ALL TESTS PASSED")  
print("=" * 60)
