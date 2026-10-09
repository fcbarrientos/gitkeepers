# GitKeepers — Rural Healthcare Workflow System

An offline-first desktop and web application designed for Barangay Health Workers (BHWs), midwives, and rural healthcare volunteers serving isolated communities in the Philippines.

The system assists health workers with daily workflows (household/patient records, structured DOH checkup forms, referral slips, medicine and supply tracking, and municipal reporting) without requiring internet connectivity. It uses an offline, on-device language model (Qwen3-4B) to assist with data entry and summaries, and features a secure, pseudonymized sync protocol for transferring data to the Rural Health Unit (RHU) or hospital database.

---

## Key Features

- **Offline-First Patient & Household Records**: Local SQLite database with full offline search and storage.
- **AI-Assisted Form Entry**: Extracts clinical vitals and 19+ symptom fields from unstructured Taglish/Filipino/English notes directly into structured form suggestions. Empty fields remain empty, and nothing is saved without health worker confirmation.
- **Strict Clinical Boundary**: The local AI only assists with language and form suggestions. Clinical rules and referral flags are strictly rule-based and reviewed by health professionals.
- **On-Device Privacy & Pseudonymization (`core/pseudonymize.py`)**: Patient PII (names, contact numbers, PhilHealth PINs, and barangay/sitio addresses) is detected and tokenized into deterministic pseudonyms (`PSN-PAT-...`).
- **Encrypted RHU Sync Transfer (`core/sync.py`)**: Packages visit data into de-identified sync bundles encrypted with AES-256-GCM. Clinical data in transit is protected even over public Wi-Fi, mesh networks, or USB transfers, and is reversible only with the RHU server key.
- **Epidemiological Reporting**: Enables municipal health offices to ingest de-identified bundles for disease surveillance and DOH reporting without exposing personal patient identities.

---

## Backend Setup

### Requirements
- **Python:** 3.11 or 3.12 (recommended for `llama-cpp-python` compatibility)
- **Target Hardware:** Standard laptop / desktop with ~8 GB RAM (runs on CPU without dedicated GPU)
- **Model:** Qwen3-4B-GGUF (`Q4_K_M` quantization, ~2.5 GB)

### Quick Start
Run from the `backend/` directory:

```bash
python -m venv .venv
# Activate venv:
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
python -m scripts.download_model     # Download Qwen3-4B GGUF weights
python run.py --port 8765
```

Interactive API documentation: `http://127.0.0.1:8765/docs`

**Windows note for llama-cpp-python:** If compilation fails, install the Microsoft C++ Build Tools, or install a prebuilt CPU wheel:
```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

---

## Running Evaluations & Tests

### Run Unit Tests
```bash
python -m unittest discover -s tests -v
```

### Run Clinical Model Evaluation Harness
To benchmark model accuracy, latency, and parse reliability on the Taglish/Filipino clinical dataset:
```bash
python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf
```

---

## Project Layout

```
backend/
  api.py                  FastAPI server endpoints (CORS, token auth, streaming chat)
  run.py                  Launcher for desktop shells (Tauri / Electron)
  requirements.txt        Backend Python dependencies
  core/
    config.py             Paths, environment settings, and data isolation
    storage.py            SQLite connection (WAL mode), migrations, vector setup
    inference.py          LLM interface (LlamaCppLLM and MockLLM)
    extraction.py         Structured clinical extraction engine & schema
    pseudonymize.py       Offline PII detection & deterministic pseudonymization
    sync.py               AES-256-GCM encrypted sync bundles & RHU resolution
    i18n.py               Bilingual localization manager (Filipino & English)
  evals/
    samples.jsonl         25 realistic Taglish/Filipino clinical evaluation cases
    scoring.py            Field-by-field accuracy and exact-match evaluation logic
    run_eval.py           Model benchmark runner and RAM/latency profiler
  i18n/
    en.json               English translations
    fil.json              Filipino / Tagalog translations
  prompts/
    glossary_fil.json     Filipino clinical term glossary
    prenatal_fewshot.json Few-shot clinical extraction exemplars
  migrations/             Numbered SQL migrations
  scripts/
    download_model.py     Model weight downloader
  tests/
    test_extraction.py    Unit tests for extraction, i18n, and prompts
    test_pseudonymize.py  Unit tests for PII masking, AES-GCM sync, and RHU ingestion
```

---

## Configuration (Environment Variables)

| Variable | Default | Purpose |
|---|---|---|
| `APP_DATA_DIR` | OS user-data dir | Override folder where `app.db` and `models/` reside |
| `MODEL_PATH` | `models/Qwen3-4B-Q4_K_M.gguf` | Path to GGUF weights (falls back to `MockLLM` if missing) |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins for desktop shell / web UI |
| `API_TOKEN` | `None` | If set, requests must include `X-API-Token` header |
