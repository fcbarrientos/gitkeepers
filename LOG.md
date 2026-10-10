## 09/10/26 18:24
- Set up Qwen3-4B-GGUF as the local AI model
- Switched Python environment from 3.14 to 3.12

## 09/10/26 20:41
- Added files and modules to test Qwen3's translation capabilities from English to Filipino and vice versa
- Populating vocabulary with `glossary_fil.json` and `prenatal_fewshot.json`

## 09/10/26 22:30
- Expanded clinical schema from 9 prenatal fields to 19 comprehensive clinical fields (adding `vomiting`, `cough`, `colds`, `sore_throat`, `shortness_of_breath`, `chest_pain`, `abdominal_pain`, `diarrhea`, `rash`, `body_pain`)
- Updated Filipino-English translations in `i18n/en.json`, `i18n/fil.json`, and `prompts/glossary_fil.json`
- Created 25 realistic Taglish/Filipino clinical evaluation cases in `evals/samples.jsonl`

## 09/10/26 23:15
- Optimized extraction prompt and schema:
  - Enabled compact/sparse JSON output (omitting unmentioned fields) to dramatically reduce generation token length
  - Increased token ceiling to `max_tokens=512` in `core/extraction.py` and `core/inference.py`
  - Added clinical few-shot examples across all symptom categories in `prompts/prenatal_fewshot.json`
  - Reduced evaluation parse failure rate from 100% to 0.0% and cut per-sample inference latency by ~51% (11.6s -> 5.7s)

## 09/10/26 23:55
- Implemented offline-first Pseudonymization Engine (`core/pseudonymize.py`):
  - Rule-based & regex detection for Filipino name markers (`si`, `ni`, `kay`, `kina`), honorifics (`Nanay`, `Tatay`, `Aling`, `Mang`, `Ate`, `Kuya`, `Dra.`), Philippine phone numbers, PhilHealth PINs, and address markers (`Brgy.`, `Sitio`, `Purok`)
  - Deterministic entity tokenization (`PSN-PAT-...`, `PSN-PHONE-...`, `PSN-LOC-...`) with local reversible vault
- Implemented Secure RHU Sync Transfer Protocol (`core/sync.py`):
  - Encrypted key envelope using AES-256-GCM and HKDF key derivation
  - Supports de-identified transit over USB/mesh/internet and full identity restoration at the RHU/Hospital server
  - Supports anonymous extraction for municipal DOH epidemiological reporting
- Created comprehensive test suite (`tests/test_pseudonymize.py`) with all 26 backend unit tests passing

## 10/10/26 05:31
- Prenatal extraction baseline before the visits/forms work (Qwen3-4B-Q4_K_M, 25 samples, CPU-only):
  - raw notes: fields 81%, exact 20%, parse_fail 0%, avg 42.0s
  - pseudonymized notes (`--pseudonymize`): fields 81%, exact 16%, parse_fail 0%, avg 38.9s
  - Common misses: values stated in the note left empty (e.g. BP "170/100" -> null) and unmentioned symptoms set to false
- Added `--pseudonymize` to `evals/run_eval.py` so evals see the same masked notes as production

## 10/10/26 07:52
- Added the web app (`frontend/`, React + Vite PWA, English/Filipino): sign-in and sign-up with admin approval, profile, accounts, households and patients, checkup forms with AI suggest → review → confirm, visit timelines, follow-ups, and a bento dashboard; referrals, supplies, reports and sync shown as "coming soon"
- Backend: `GET /api/v1/dashboard`, `GET /api/v1/visits`, and serving `frontend/dist` at `/`

## 10/10/26 09:01
- Referrals (rule files + flags on finalize + slips), medicine and supply tracking, weekly/monthly reports with editable AI drafts from aggregated numbers, and manual sync (encrypted transfer file + signed RHU receipt); the four "Coming soon" tabs are now live
