"""Entry point for the desktop shell: python run.py --port 8765
Binds to localhost only. Set API_TOKEN in the environment to require auth."""
import argparse

import uvicorn

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    uvicorn.run("api:app", host="127.0.0.1", port=args.port)
