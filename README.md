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

### Frontend API

The backend is usable without a frontend. Its versioned HTTP contract is published at
`http://127.0.0.1:8765/docs` and `/openapi.json`; frontend clients can generate typed
bindings from that OpenAPI schema. New feature endpoints live under `/api/v1`, including
the versioned chat and conversation endpoints. The original unversioned chat and
conversation paths remain available for existing clients.

Authentication and accounts (accounts live on the device, so login works offline):

| Method | Endpoint | Who | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/auth/signup` | anyone | Create an account. The first account on a device becomes an active admin; later ones are pending volunteers until an admin approves them |
| `POST` | `/api/v1/auth/login` | anyone | `{ "login": "<username or email>", "password": "..." }` → `{ token, expires_at, user }` |
| `POST` | `/api/v1/auth/logout` | signed in | Revoke the current session |
| `GET` | `/api/v1/auth/me` | signed in | The current user |
| `PATCH` | `/api/v1/me` | signed in | Update own `full_name` / `email` |
| `POST` | `/api/v1/me/password` | signed in | `{ current_password, new_password }`; signs out other sessions |
| `GET` | `/api/v1/users?status=&role=&q=&limit=&offset=` | admin | List accounts, pending first |
| `GET` | `/api/v1/users/{user_id}` | admin | Get one account |
| `PATCH` | `/api/v1/users/{user_id}` | admin | `{ "status": "active" \| "disabled", "role": "admin" \| "volunteer" }` (approve = `active`) |
| `POST` | `/api/v1/users/{user_id}/password` | admin | Offline password reset; signs the user out everywhere |

Every other `/api/v1` endpoint requires `Authorization: Bearer <token>` from login.
Sessions last 7 days and are extended while in use. Five wrong passwords lock an account
for 5 minutes. Errors use `{ "detail": "<message>" }`, which is safe to show to users.

Household and patient records:

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/households` | Register a household, optionally with its first members in one transaction |
| `GET` | `/api/v1/households?q=&limit=25&offset=0` | Search and page through households |
| `GET` | `/api/v1/households/{household_id}` | Get a household and its members |
| `POST` | `/api/v1/households/{household_id}/members` | Register another household member |
| `GET` | `/api/v1/patients?q=&household_id=&limit=25&offset=0` | Search and page through patients |
| `GET` | `/api/v1/patients/{patient_id}` | Get a patient and household location |

To register a household and its first member in one request:

```json
{
  "barangay": "Barangay name",
  "sitio": "Sitio name",
  "members": [
    {
      "full_name": "Member name",
      "birth_date": "1990-01-31",
      "sex": "female",
      "is_household_head": true
    }
  ]
}
```

List responses use `{ "items": [], "total": 0, "limit": 25, "offset": 0 }`.
Search matches household location and member names, or patient names and contact
numbers using token-prefix full-text search. Limits are capped at 100. Every endpoint
other than `/health` uses the configured `X-API-Token` check when `API_TOKEN` is set.

Checkup forms, AI-assisted entry, visits and follow-ups:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/forms` / `/api/v1/forms/{form_type}` | Form definitions (`prenatal`, `child_growth`, `bp_followup`): fields, types, ranges, en/fil labels, required and AI flags. Drafts pending DOH review, defined in `backend/forms/*.json` |
| `GET` | `/api/v1/ai/status` | `{ available, model }`: whether the local model file is present |
| `POST` | `/api/v1/patients/{id}/suggestions` | `{ form_type, note }` → `{ suggestion_id, values, missing, problems }`. The note is pseudonymized before it reaches the model. `503` means fill the form manually |
| `POST` | `/api/v1/patients/{id}/visits` | Record a visit: `{ form_type, visit_date, values, note, status: draft\|final, suggestion_id, ai_accepted_fields, follow_up: { due_date, reason }, completes_follow_up_id }` |
| `GET` | `/api/v1/patients/{id}/visits?form_type=` | Visit timeline, newest first |
| `GET` / `PATCH` | `/api/v1/visits/{id}` | Get a visit; edit or finalize a draft (final visits are read-only) |
| `GET` | `/api/v1/follow-ups?state=overdue\|due\|upcoming\|completed\|cancelled&patient_id=&q=` | Follow-up list, by due date |
| `POST` | `/api/v1/patients/{id}/follow-ups` | Schedule a follow-up |
| `PATCH` | `/api/v1/follow-ups/{id}` | Reschedule or cancel |
| `POST` | `/api/v1/follow-ups/{id}/complete` | Mark completed, optionally with `{ visit_id }` |
| `GET` | `/api/v1/visits?date=&status=draft\|final` | Visits across all patients, newest first, with `patient_name` |
| `GET` | `/api/v1/dashboard` | Counts for the home screen: follow-ups overdue/due/upcoming, visits today, drafts, households, patients, AI status |

AI suggestions are never saved on their own. The client submits the values the worker
confirmed plus `ai_accepted_fields`, and each saved field records its source:
`manual`, `ai_accepted` or `ai_edited`. Validation errors on visit values come back as
`422 { "detail": ["<field>: <problem>", ...] }`.

Referrals, supplies, reports and sync:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/referral-rules` | Referral rules per form (`backend/referral_rules/*.json`, draft pending professional review). Finalizing a visit records a flag for every rule it meets; the AI is never involved |
| `GET` | `/api/v1/referral-flags?status=open&patient_id=&visit_id=` | Flags; `POST /referral-flags/{id}/dismiss` closes one |
| `POST` / `GET` | `/api/v1/referrals`, `/api/v1/referrals/{id}` | Create (optionally from a flag) and read referral slips |
| `GET` / `POST` | `/api/v1/supplies`, `/api/v1/supplies/{id}/movements` | Items with on-hand stock (sum of movements) and low-stock flag; record received / distributed / adjusted |
| `GET` | `/api/v1/supplies/request-list` | Low items with the quantity needed to reach the target |
| `GET` | `/api/v1/reports/summary?period=week\|month&date=` | Counts for the period and the previous one, plus unsynced records |
| `POST` | `/api/v1/reports/drafts` / `/reports/drafts/manual` | AI draft from aggregated numbers only (503 when the model is off) or a hand-written draft; `PATCH /reports/drafts/{id}` edits or approves |
| `GET` | `/api/v1/sync/status` | Pending / awaiting receipt / synced counts per record type |
| `PUT` | `/api/v1/sync/settings` | Admin: RHU passphrase (12+ characters) |
| `POST` | `/api/v1/sync/bundles` | Admin: encrypted, de-identified transfer file of all pending records |
| `POST` | `/api/v1/sync/receipts` | Admin: RHU receipt (signed with the passphrase); only then are records marked synced |

At the RHU, `RHU_PASSPHRASE=... python -m scripts.rhu_receipt transfer.json` checks a transfer
file and writes the receipt to import back on the device.

Use this same resource-oriented, versioned contract for future visits, referrals,
inventory, reporting, and sync APIs: validated request/response schemas, bounded
pagination, feature-specific routers, service-layer database operations, and
numbered migrations. This keeps frontend calls stable and discoverable as features grow.

**Windows note for llama-cpp-python:** If compilation fails, install the Microsoft C++ Build Tools, or install a prebuilt CPU wheel:
```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

---

## Frontend (web app)

The web app lives in `frontend/` (React + TypeScript + Vite, installable as a PWA). In
production the backend serves the built app on its own port, so health workers open
`http://127.0.0.1:8765/` on the laptop that runs it.

Current limits:
- `run.py` listens on `127.0.0.1` only, so phones on the same Wi-Fi cannot reach it yet. Opening
  it to the network would also need HTTPS for the PWA (offline shell, install) to work on phones.
- Leave `API_TOKEN` unset when using the built-in web app: the app does not send `X-API-Token`,
  so with a token set nobody can sign in. The token is for a desktop shell that calls the API itself.

```bash
cd frontend
npm install
npm run build        # writes frontend/dist, which the backend serves at /
npm run dev          # development: http://localhost:5173, proxies /api to 127.0.0.1:8765
npm test             # unit and component tests (Vitest)
```

The UI has English and Filipino (toggle in the header). Data never leaves the backend's
SQLite database; the service worker caches only the app shell.

---

## Running Evaluations & Tests

### Run Unit Tests
Tests need `httpx` (listed in `requirements.txt`); `llama-cpp-python` is not required to run them.
```bash
python -m unittest discover -s tests -v
```

### Run Clinical Model Evaluation Harness
To benchmark model accuracy, latency, and parse reliability on the Taglish/Filipino clinical dataset:
```bash
python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf                                   # original 19-field prenatal eval
python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form child_growth --pseudonymize  # a form's AI fields, masked notes
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
    forms.py              Form loading and value validation
    assist.py             Shared local model, note masking, AI suggestions
    visits.py             Visits: draft/final lifecycle and AI provenance
    follow_ups.py         Follow-up scheduling and due/overdue state
  forms/                  Checkup form definitions (JSON, pending DOH review)
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
frontend/
  src/api/                Fetch wrapper and endpoint types
  src/auth/               Session token, sign-in state, route guards
  src/forms/              Form renderer and AI suggestion review state
  src/pages/              One file per screen
  src/i18n/               en.json / fil.json and the language toggle
```

---

## Configuration (Environment Variables)

| Variable | Default | Purpose |
|---|---|---|
| `APP_DATA_DIR` | OS user-data dir | Override folder where `app.db` and `models/` reside |
| `MODEL_PATH` | `models/Qwen3-4B-Q4_K_M.gguf` | Path to GGUF weights (falls back to `MockLLM` if missing) |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins for desktop shell / web UI |
| `API_TOKEN` | `None` | If set, requests must include `X-API-Token` header |
| `FRONTEND_DIST` | `frontend/dist` | Built web app the backend serves at `/` (skipped when missing) |
