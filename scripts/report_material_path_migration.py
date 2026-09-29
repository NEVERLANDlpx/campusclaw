"""Generate a before/after table for material path migration."""
import argparse
import sqlite3
from pathlib import Path


def rows_by_id(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {row['id']: row for row in conn.execute('SELECT id,class_id,title,original_name,file_path FROM materials ORDER BY id')}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', required=True)
    parser.add_argument('--after', default='data/app.db')
    parser.add_argument('--output', default='deliverables/00_审查报告/material-path-migration/迁移前后对照表.md')
    args = parser.parse_args()
    before = Path(args.before)
    after = Path(args.after)
    old_rows = rows_by_id(before)
    new_rows = rows_by_id(after)
    lines = [
        '# 材料路径迁移前后对照表',
        '',
        f'数据库备份：`{before}`',
        f'当前数据库：`{after}`',
        '',
        '| ID | class_id | title | original_name | 迁移前 file_path | 迁移后 file_path |',
        '|---|---:|---|---|---|---|',
    ]
    for mid in sorted(new_rows):
        old = old_rows[mid]
        new = new_rows[mid]
        lines.append(f"| {mid} | {new['class_id']} | {new['title']} | {new['original_name']} | `{old['file_path']}` | `{new['file_path']}` |")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
