"""
run.py — Novara Entry Point
============================
Quick launcher for the Novara dashboard.

Usage:
    python run.py           → Launch Streamlit dashboard
    python run.py --seed    → Seed demo data then launch
    python run.py --init    → Initialize database only
"""
import os
import sys
import subprocess
import argparse


def main():
    parser = argparse.ArgumentParser(description="Novara — Physiological Intelligence Dashboard")
    parser.add_argument("--seed", action="store_true", help="Seed demo data before launching")
    parser.add_argument("--init", action="store_true", help="Initialize database only (no launch)")
    parser.add_argument("--port", type=int, default=8501, help="Streamlit port (default: 8501)")
    args = parser.parse_args()

    # Add project root to path
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)

    from novara.models.database import init_db

    # Initialize database
    print("🗄  Initializing database...")
    init_db()
    print("✓  Database ready")

    if args.seed:
        print("🧬 Seeding demo data...")
        from novara.simulation.simulator import Simulator
        sim = Simulator()
        ids = sim.seed_all(days=14)
        print(f"✓  Created {len(ids)} demo patients with 14 days of data")

    if args.init:
        print("✓  Initialization complete. Exiting.")
        return

    # Launch Streamlit
    app_path = os.path.join(project_root, "novara", "app.py")
    print(f"\n🚀 Launching Novara Dashboard on port {args.port}...")
    print(f"   Open: http://localhost:{args.port}\n")

    subprocess.run([
        sys.executable, "-m", "streamlit", "run", app_path,
        "--server.port", str(args.port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
        "--theme.primaryColor", "#764ba2",
        "--theme.backgroundColor", "#0e1117",
        "--theme.secondaryBackgroundColor", "#1a1a2e",
        "--theme.textColor", "#e2e8f0",
    ])


if __name__ == "__main__":
    main()
