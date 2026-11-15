import sys
from pathlib import Path

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ENGINE_ROOT))

import os

# Tests never spend a real provider's quota on embeddings: llm/client.py loads the
# repo-root .env (which may hold a real OPENAI_API_KEY), and with it set the RAG
# index would otherwise call OpenAI's embedding API from "offline" scripted tests.
os.environ["PAYSHIFT_EMBEDDINGS"] = "local"
