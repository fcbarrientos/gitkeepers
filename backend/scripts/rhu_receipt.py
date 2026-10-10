"""RHU side of a manual transfer: check a GitKeepers transfer file and write its signed receipt.

Run from backend/:
    RHU_PASSPHRASE=... python -m scripts.rhu_receipt path/to/transfer.json
The passphrase comes from the environment so it does not end up in shell history.
"""
import json
import os
import sys
from pathlib import Path

from core.sync import unpack_and_resolve_bundle
from core.sync_state import make_receipt


def write_receipt(bundle_path: Path, passphrase: str) -> Path:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    records = unpack_and_resolve_bundle(bundle, passphrase)  # raises if the passphrase is wrong
    if len(records) != bundle["record_count"]:
        raise ValueError("record count does not match the payload")
    receipt_path = bundle_path.with_name(f"{bundle_path.stem}.receipt.json")
    receipt_path.write_text(json.dumps(make_receipt(bundle, passphrase), indent=2), encoding="utf-8")
    return receipt_path


if __name__ == "__main__":
    secret = os.environ.get("RHU_PASSPHRASE")
    if len(sys.argv) != 2 or not secret:
        sys.exit("usage: RHU_PASSPHRASE=... python -m scripts.rhu_receipt TRANSFER_FILE.json")
    print("wrote", write_receipt(Path(sys.argv[1]), secret))
