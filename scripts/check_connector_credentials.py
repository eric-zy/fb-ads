"""Read-only overseas credential state check; never reads token columns."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fb_connector.models import ConnectorCredential, connector_session_factory


def credential_states(db, credential_ids=None, limit=100):
    if not 1 <= limit <= 100:
        raise ValueError("limit 必须为 1 至 100")
    ids = list(dict.fromkeys(credential_ids or []))
    if len(ids) > 100:
        raise ValueError("一次最多检查 100 个凭据 ID")
    query = db.query(ConnectorCredential.id, ConnectorCredential.status, ConnectorCredential.expires_at)
    if ids:
        query = query.filter(ConnectorCredential.id.in_(ids))
    total = query.count()
    rows = query.order_by(ConnectorCredential.id).limit(100 if ids else limit).all()
    now = datetime.utcnow()
    items = [{"credential_id": row.id, "status": "EXPIRED" if row.status == "ACTIVE" and row.expires_at and row.expires_at <= now else row.status,
              "expires_at": row.expires_at.isoformat() if row.expires_at else None} for row in rows]
    found = {item["credential_id"] for item in items}
    items.extend({"credential_id": key, "status": "MISSING", "expires_at": None} for key in ids if key not in found)
    return {"matched_records": total, "truncated": not ids and total > limit, "items": items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-id", action="append", help="国内引用的海外凭据 ID，可重复指定")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    with connector_session_factory() as db:
        result = credential_states(db, args.credential_id, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if not result["items"] or any(item["status"] != "ACTIVE" for item in result["items"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
