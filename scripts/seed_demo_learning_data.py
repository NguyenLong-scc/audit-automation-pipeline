"""Seed fictional approved data into the local learning gateway."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_agent.demo_learning_data import seed_demo_learning_data


if __name__ == "__main__":
    created, already_present = seed_demo_learning_data()
    print(f"Created {created} fictional examples; {already_present} already present.")
