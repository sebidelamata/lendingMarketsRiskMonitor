#!/usr/bin/env python3
"""Entry point for the Aave V3 multi-chain monitor.

The implementation lives in the `aave_monitor` package (see
aave_monitor/app.py for main()). This file just wires it up so you can
run:

    python main.py

Update aave-monitor.service to point at this file instead of the old
aave_monitor.py (see README note added during the refactor).
"""

from aave_monitor.app import main

if __name__ == "__main__":
    main()
