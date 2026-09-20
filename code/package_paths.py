"""Resolve all packaged inputs from this file, independent of the working directory."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / 'code'
DYNAMIC = CODE / 'experiments/branch_unit/dynamic'
EVALUATION = CODE / 'experiments/branch_unit/paper_a_evaluation'
sys.path[:0] = [str(DYNAMIC), str(EVALUATION)]
