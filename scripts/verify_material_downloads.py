"""Verify material downloads against a running CampusClaw server."""
import argparse
import html
import json
import re
import sqlite3
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


def request(opener, method, url, data=None, headers=None):
    body = None if data is None else data
    req = Request(url, data=body, method=method, headers=headers or {})
    try:
        res = opener.open(req, timeout=10)
        payload = res.read()
        return {'status': res.status, 'headers': dict(res.headers), 'body': payload}
    except Exception as exc:
        if hasattr(exc, 'code') and hasattr(exc, 'read'):
            return {'status': exc.code, 'headers': dict(exc.headers), 'body': exc.read()}
        raise


def login(base, username):
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    page = request(opener, 'GET', base + '/login')
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page['body']).group(1).decode()
    body = urlencode({'username': username, 'password': 'Campus@2026', 'csrf_token': token}).encode()
    res = request(opener, 'POST', base + '/login', body, {'Content-Type': 'application/x-www-form-urlencoded'})
    if res['status'] not in (200, 302):
        raise RuntimeError(f'login failed for {username}: {res["status"]}')
    return opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8080')
    parser.add_argument('--db', default='data/app.db')
    parser.add_argument('--upload-root', default='uploads')
    parser.add_argument('--output', default='deliverables/00_审查报告/material-path-migration/download-verification.json')
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    rows = [dict(row) for row in db.execute('SELECT id,class_id,title,original_name,file_path,size_bytes FROM materials ORDER BY id')]
    db.close()
    teacher = login(args.base, 'teacher_a')
    student_b = login(args.base, 'student_b1')
    anonymous = build_opener(HTTPCookieProcessor(CookieJar()))
    results = []
    upload_root = Path(args.upload_root)
    for row in rows:
        opener = teacher if row['class_id'] == 1 else student_b
        res = request(opener, 'GET', f"{args.base}/api/materials/{row['id']}/download")
        expected = (upload_root / row['file_path']).read_bytes()
        results.append({
            'id': row['id'],
            'class_id': row['class_id'],
            'title': row['title'],
            'file_path': row['file_path'],
            'status': res['status'],
            'bytes_match': res['body'] == expected,
            'content_disposition': res['headers'].get('Content-Disposition'),
        })
    anon = request(anonymous, 'GET', f"{args.base}/api/materials/{rows[0]['id']}/download")
    cross = request(teacher, 'GET', f"{args.base}/api/materials/3/download")
    summary = {
        'base': args.base,
        'downloads': results,
        'anonymous_download_status': anon['status'],
        'teacher_cross_class_download_status': cross['status'],
        'all_authorized_downloads_ok': all(r['status'] == 200 and r['bytes_match'] for r in results),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
