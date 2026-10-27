"""Safely rebuild SQLite knowledge chunks and embeddings for existing txt/md materials."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines() if (ROOT / '.env').exists() else []:
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value)

from app.ai_clients import EmbeddingClient
from app.db import connect, ensure_schema
from app.knowledge import rebuild_material_index


def main():
    db_path = os.environ.get('DATABASE_PATH', str(ROOT / 'data/app.db'))
    client = EmbeddingClient()
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            '''SELECT m.id,m.class_id,m.title,m.original_name
               FROM materials m JOIN knowledge_entries k ON k.material_id=m.id AND k.class_id=m.class_id
               WHERE lower(m.original_name) LIKE '%.txt' OR lower(m.original_name) LIKE '%.md'
               ORDER BY m.class_id,m.id'''
        ).fetchall()
        print(f'Found {len(rows)} material(s) to rebuild.')
        failures = 0
        for row in rows:
            result = rebuild_material_index(conn, row['id'], row['class_id'], client)
            failures += result['failed']
            print(f"material_id={row['id']} class_id={row['class_id']} title={row['title']} chunks={result['chunks']} failed={result['failed']}")
        return 1 if failures else 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
