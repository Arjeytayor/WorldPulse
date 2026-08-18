"""Force a fresh run — clears vector index, runs pipeline, logs to console."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vector_store import clear_recent_topics
from scheduler import run_pipeline

if __name__ == "__main__":
    print("🔧 Clearing vector index...")
    clear_recent_topics()
    print("✅ Index cleared. Starting fresh pipeline...\n")

    # Run the pipeline — this will take 5-10 minutes
    run_pipeline()

    print("\n=== Done ===")
