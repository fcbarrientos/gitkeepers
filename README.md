# Gitkeepers

## Backend

### Requirements
- Python 3.11 or 3.12 (the newest Python versions may not have prebuilt wheels for `llama-cpp-python`)
- About 8 GB of RAM and no GPU is the target hardware. The model file is roughly 2.5 GB.
### Quick start
Run everything from the `backend/` folder.
 
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.download_model     # one-time, ~2.5 GB, see "Model" below
python run.py --port 8765
```
 
Interactive API docs: http://127.0.0.1:8765/docs
 
**Windows:** if `pip install llama-cpp-python` fails with a compiler error, install the
Microsoft C++ Build Tools, or use a prebuilt CPU wheel:
 
```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```
 
### Model
- **Model:** Qwen3-4B, 4-bit (`Q4_K_M`) GGUF, from the official `Qwen/Qwen3-4B-GGUF` repo.
  License: Apache 2.0. Keep this line updated if the model changes.
- **Download:** `python -m scripts.download_model` saves the file to the `models/` folder inside
  the data directory (see below). Models are never committed to git.
- **Offline / sideloading:** copy the `.gguf` file into that `models/` folder by hand. No
  internet is needed after that.
- **Selecting the file:** set `MODEL_PATH` to override the default location. If no model file is
  found, the API falls back to `MockLLM` (canned replies) so the frontend team can still work.
- **Thinking mode:** Qwen3 "thinks" before answering by default, which is slow on a CPU. Add
  `/no_think` to the prompt to turn it off, and strip any empty `<think></think>` tags from the output.
- **Memory:** load one model at a time. When speech-to-text is added, load and unload it
  separately from the language model so the two never sit in RAM together.
### Measured performance
Fill this in on the slowest machine you can test, so the team can judge feasibility.
 
| Machine (CPU / RAM) | Time to first token | Tokens per second | Peak RAM |
|---|---|---|---|
| _add yours_ | | | |
 
### Configuration (environment variables)
| Variable | Purpose |
|---|---|
| `APP_DATA_DIR` | Override where the database and models live (default: OS user-data folder) |
| `MODEL_PATH` | Path to the GGUF model file (default: `models/Qwen3-4B-Q4_K_M.gguf` in the data dir) |
| `ALLOWED_ORIGINS` | Comma-separated origins the UI calls from (CORS) |
| `API_TOKEN` | If set, requests must send `X-API-Token: <value>` (except `/health`) |
 
The desktop shell should start the backend with `python run.py --port <free port>` and a random
`API_TOKEN`, wait for `/health` to respond, and stop the process on exit. The server only
listens on 127.0.0.1.
 
### Where is my data?
The database and models live in your OS user-data folder, not in the repo. To print the exact path:
 
```bash
python -c "from core.config import DATA_DIR; print(DATA_DIR)"
```
 
For local development, set `APP_DATA_DIR` to a folder such as `backend/data/` (already gitignored)
if you'd rather keep everything inside the project.
 
### Database
- File: `app.db` in the data directory, created automatically. Never committed.
- Schema changes: add a new numbered file in `migrations/` (for example `002_add_visits.sql`).
  Never edit a migration after it has been merged. Migrations apply on startup.
- Don't run migration files by hand from an IDE's SQL console. That would apply them without
  recording them in `schema_version`, and the next startup would fail.
- The vector table is created in code (`enable_vectors(conn, dim)`), not in a migration,
  because its size depends on the embedding model.
### API
See `/docs` for the full, current list. Endpoints so far:
 
| Endpoint | Purpose |
|---|---|
| `GET /health` | Open (no token). Used by the desktop shell to check the backend is ready |
| `GET /conversations` | List conversations |
| `GET /conversations/{id}/messages` | Messages in a conversation |
| `POST /chat` | Send a message, streamed back as Server-Sent Events |
 
The frontend must read `/chat` with `fetch` and a streamed response, not `EventSource`, because
`EventSource` can't send the `X-API-Token` header.
 
### Project layout
```
backend/
  api.py              FastAPI app (CORS, token auth, endpoints)
  run.py              launcher used by the desktop shell
  core/
    config.py         paths and environment settings
    storage.py        SQLite connection, migrations, vector setup
    inference.py      LLM interface: LlamaCppLLM and MockLLM
  migrations/         numbered .sql files
  scripts/
    download_model.py one-time model download
```
