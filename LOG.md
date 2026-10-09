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
