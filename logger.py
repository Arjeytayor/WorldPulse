"""Shared error logger for all AfricanPulse modules."""

import logging
import os

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "errors.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(module)s.%(funcName)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)

logger = logging.getLogger("WorldPulseLogger")
