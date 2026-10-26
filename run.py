"""
Launcher script for NoSQL E-Commerce Analytics System.
Starts the FastAPI server with Uvicorn and launches the dashboard.
"""

import sys
import webbrowser
import uvicorn
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

def main():
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    
    print("=" * 70)
    print("  🚀 NEXUS // NoSQL E-Commerce Product & Customer Analytics System")
    print("=" * 70)
    print(f"  • Dashboard URL: {url}")
    print(f"  • Interactive API Docs (Swagger): {url}/docs")
    print(f"  • Redoc Documentation: {url}/redoc")
    print(f"  • NoSQL Engine: Dual-Mode (Embedded BSON Aggregation / MongoDB Atlas)")
    print("=" * 70)
    
    # Auto open browser
    try:
        webbrowser.open(url)
    except Exception:
        pass

    uvicorn.run("backend.app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
