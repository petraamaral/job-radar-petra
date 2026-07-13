"""
Job Radar — entry point
=======================
Set RADAR_MODE=interactive in GitHub Secrets to enable button mode.
Leave unset or set to anything else to run simple mode (no Supabase required).
"""

import os

mode = os.environ.get("RADAR_MODE", "simple").strip().lower()

if mode == "interactive":
    print("[run.py] Mode: interactive (Supabase + Telegram buttons)")
    from bot_interactive import main
else:
    print("[run.py] Mode: simple (Telegram only)")
    from scraper import main

main()
