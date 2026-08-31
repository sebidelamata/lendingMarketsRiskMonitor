"""Central logging configuration. Import `log` from here everywhere else
instead of calling logging.getLogger() again, so all modules share one
configured logger.
"""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

log = logging.getLogger("aave-monitor")
