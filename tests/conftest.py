"""
Shared fixtures for all test modules.
"""
import sys
from pathlib import Path

# Ensure project root is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
