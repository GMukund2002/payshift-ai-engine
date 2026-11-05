import sys
from pathlib import Path

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ENGINE_ROOT))
