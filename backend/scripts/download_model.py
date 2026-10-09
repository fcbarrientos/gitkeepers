"""python -m scripts.download_model [filename]   (default: Qwen3-4B-Q4_K_M.gguf)
Examples: python -m scripts.download_model Qwen3-4B-Q5_K_M.gguf"""
import sys

from huggingface_hub import hf_hub_download

from core.config import MODELS_DIR, ensure_dirs

filename = sys.argv[1] if len(sys.argv) > 1 else "Qwen3-4B-Q4_K_M.gguf"
ensure_dirs()
print(hf_hub_download("Qwen/Qwen3-4B-GGUF", filename, local_dir=MODELS_DIR))
