# Gitkeepers

## Backend

Local-first backend: SQLite + (optional) llama.cpp. No cloud services required.

### Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --port 8765        # or: uvicorn api:app --reload
```
Open http://127.0.0.1:8000/docs for the interactive API docs.

### Configuration (environment variables)
| Variable | Purpose |
|---|---|
| `APP_DATA_DIR` | Override where the database and models live (default: OS user-data folder) |
| `ALLOWED_ORIGINS` | Comma-separated origins the UI calls from (CORS) |
| `API_TOKEN` | If set, requests must send `X-API-Token: <value>` (except `/health`) |

The desktop shell should start the backend with `python run.py --port <free port>`, a random
`API_TOKEN`, wait for `/health`, and stop the process on exit. The server only listens on 127.0.0.1.

### Database
- File: `app.db` in the data directory (see `core/config.py`), created automatically. Not in the repo.
- Schema changes: add a new numbered file in `migrations/` (e.g. `002_add_tags.sql`).
  Never edit an existing migration after it's been merged. Migrations apply on startup.

### Models
Models are not stored in git. Put GGUF files in the `models/` folder inside the data directory
(created automatically; path is `core.config.MODELS_DIR`).
Until then the API uses `MockLLM`, so the frontend can start immediately.
