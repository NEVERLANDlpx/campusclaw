"""Audit and migrate materials.file_path to upload-root-relative paths."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import connect, material_relative_path, resolve_material_file


def classify(stored_path):
    value = str(stored_path or '')
    normalized = value.replace('\\', '/')
    if len(value) >= 2 and value[1] == ':':
        return 'windows_absolute'
    if value.startswith('/'):
        return 'linux_absolute'
    if value.startswith('\\\\'):
        return 'unc_absolute'
    if normalized.lower().startswith('uploads/'):
        return 'uploads_relative'
    return 'upload_root_relative'


def backup_database(db_path, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = backup_dir / f'{db_path.stem}.before-material-path-migration.{stamp}.bak'
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(target)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    return target


def audit(db_path, upload_root):
    root = Path(upload_root).resolve()
    rows = []
    referenced = set()
    conn = connect(db_path)
    try:
        for row in conn.execute('SELECT id,class_id,title,original_name,file_path FROM materials ORDER BY id'):
            item = {
                'id': row['id'],
                'class_id': row['class_id'],
                'title': row['title'],
                'original_name': row['original_name'],
                'old_path': row['file_path'],
                'path_kind': classify(row['file_path']),
                'new_path': None,
                'file_exists': False,
                'action': 'skip',
                'reason': '',
            }
            try:
                target, rel = resolve_material_file(root, row['file_path'], row['class_id'], must_exist=True)
                item['new_path'] = rel
                item['resolved_path'] = str(target)
                item['file_exists'] = True
                referenced.add(rel)
                if rel == row['file_path']:
                    item['action'] = 'keep'
                    item['reason'] = 'already relative'
                else:
                    item['action'] = 'update'
                    item['reason'] = 'safe legacy path converted to upload-root-relative path'
            except Exception as exc:
                try:
                    rel = material_relative_path(row['file_path'], row['class_id'])
                    item['new_path'] = rel
                    item['resolved_path'] = str((root / rel).resolve(strict=False))
                except Exception:
                    item['resolved_path'] = None
                item['reason'] = str(exc)
            rows.append(item)
    finally:
        conn.close()

    files = []
    if root.exists():
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            files.append({'relative_path': rel, 'referenced_by_db': rel in referenced, 'size_bytes': path.stat().st_size})
    return {'upload_root': str(root), 'materials': rows, 'upload_files': files}


def write_reports(result, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'material-path-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [
        '# Material Path Audit',
        '',
        f"Upload root: `{result['upload_root']}`",
        '',
        '| ID | class_id | kind | action | old_path | new_path | exists | reason |',
        '|---|---:|---|---|---|---|---|---|',
    ]
    for row in result['materials']:
        lines.append(f"| {row['id']} | {row['class_id']} | {row['path_kind']} | {row['action']} | `{row['old_path']}` | `{row.get('new_path') or ''}` | {row['file_exists']} | {row['reason']} |")
    lines.extend(['', '## Upload Files', '', '| relative_path | referenced_by_db | size_bytes |', '|---|---|---:|'])
    for file in result['upload_files']:
        lines.append(f"| `{file['relative_path']}` | {file['referenced_by_db']} | {file['size_bytes']} |")
    (output_dir / 'material-path-audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def migrate(db_path, upload_root, output_dir, execute):
    result = audit(db_path, upload_root)
    result['mode'] = 'execute' if execute else 'dry-run'
    result['backup_path'] = None
    updates = [row for row in result['materials'] if row['action'] == 'update']
    if execute and updates:
        backup = backup_database(Path(db_path), Path(output_dir) / 'backups')
        result['backup_path'] = str(backup)
        conn = connect(db_path)
        try:
            with conn:
                for row in updates:
                    conn.execute('UPDATE materials SET file_path=? WHERE id=?', (row['new_path'], row['id']))
        finally:
            conn.close()
        result = audit(db_path, upload_root)
        result['mode'] = 'execute'
        result['backup_path'] = str(backup)
    write_reports(result, Path(output_dir))
    return result


def main():
    parser = argparse.ArgumentParser(description='Audit or migrate CampusClaw material file paths.')
    parser.add_argument('--db', default=str(ROOT / 'data' / 'app.db'))
    parser.add_argument('--upload-root', default=str(ROOT / 'uploads'))
    parser.add_argument('--output-dir', default=str(ROOT / 'deliverables' / '00_审查报告' / 'material-path-migration'))
    parser.add_argument('--execute', action='store_true', help='apply safe updates after SQLite Backup API backup')
    args = parser.parse_args()
    result = migrate(args.db, args.upload_root, args.output_dir, args.execute)
    print(json.dumps({
        'mode': result['mode'],
        'backup_path': result.get('backup_path'),
        'updates': sum(1 for row in result['materials'] if row['action'] == 'update'),
        'kept': sum(1 for row in result['materials'] if row['action'] == 'keep'),
        'skipped': sum(1 for row in result['materials'] if row['action'] == 'skip'),
        'report_dir': args.output_dir,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
