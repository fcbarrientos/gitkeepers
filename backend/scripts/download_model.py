from huggingface_hub import hf_hub_download
from core.config import MODELS_DIR, ensure_dirs

ensure_dirs()
path = hf_hub_download("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", local_dir=MODELS_DIR)
print(path)