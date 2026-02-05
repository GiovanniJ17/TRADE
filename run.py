"""Simple launcher script"""
import subprocess
import sys

if __name__ == "__main__":
    print("🚀 Starting Trading System DSS...")
    print("📌 Press Ctrl+C to stop the dashboard\n")
    
    try:
        # Run Streamlit dashboard
        subprocess.run([sys.executable, "-m", "streamlit", "run", "dss/ui/dashboard.py"])
    except KeyboardInterrupt:
        # Gestione pulita di Ctrl+C
        print("\n✅ Dashboard stopped successfully. Goodbye!")
        sys.exit(0)
