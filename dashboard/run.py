#!/usr/bin/env python3
"""
Standalone runner for the Pro4Kings Web Dashboard
Can run independently or alongside the Discord bot
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app import app, get_db_path

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    debug = os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"

    db_path = get_db_path()

    print(
        f"""
╔══════════════════════════════════════════════════════════════╗
║             🎮 Pro4Kings Web Dashboard                       ║
╠══════════════════════════════════════════════════════════════╣
║  🌐 URL: http://{host}:{port}                              
║  📊 Database: {db_path}
║  🔧 Debug: {debug}
╚══════════════════════════════════════════════════════════════╝
"""
    )

    # Use Flask's built-in server (for production, use gunicorn)
    app.run(host=host, port=port, debug=debug, threaded=True)
