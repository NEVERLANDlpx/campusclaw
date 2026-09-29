"""SQLite schema, deterministic demo seed and class-scoped reads."""
import os
import sqlite3
from pathlib import PurePosixPath
from pathlib import Path
import bcrypt

SCHEMA = '''
CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('teacher','student')),
 class_id INTEGER NOT NULL REFERENCES classes(id), auth_version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS materials(
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id),
 title TEXT NOT NULL, original_name TEXT NOT NULL, file_path TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, uploaded_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
 UNIQUE(id, class_id));
CREATE TABLE IF NOT EXISTS knowledge_entries(
 id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL UNIQUE, class_id INTEGER NOT NULL,
 body_text TEXT NOT NULL,
 FOREIGN KEY(material_id,class_id) REFERENCES materials(id,class_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS lectures(
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id),
 title TEXT NOT NULL, material_id INTEGER UNIQUE REFERENCES materials(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, class_id INTEGER REFERENCES classes(id), title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assistants(id INTEGER PRIMARY KEY, class_id INTEGER REFERENCES classes(id), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skills(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seed_state(version INTEGER PRIMARY KEY);
'''

def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def initialize(db_path, upload_root):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(upload_root).mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        with conn:
            conn.executemany('INSERT OR IGNORE INTO classes VALUES (?,?)', [(1,'班级 A'),(2,'班级 B')])
            accounts = [(1,'teacher_a','教师 A','teacher',1),(2,'student_a1','学生 A1','student',1),(3,'student_b1','学生 B1','student',2)]
            for uid,name,display,role,cid in accounts:
                if not conn.execute('SELECT 1 FROM users WHERE username=?',(name,)).fetchone():
                    hashed = bcrypt.hashpw(b'Campus@2026',bcrypt.gensalt(rounds=12)).decode()
                    conn.execute('INSERT INTO users(id,username,display_name,password_hash,role,class_id) VALUES (?,?,?,?,?,?)',(uid,name,display,hashed,role,cid))
            if not conn.execute('SELECT 1 FROM seed_state WHERE version=1').fetchone():
                samples = [(1,'A 班 · SDD 与规约驱动开发导学','sdd-guide.md','# SDD 与规约驱动开发\n\n先明确需求、边界与验收，再实现代码。\n\n本次实验：用户登录、角色权限、班级隔离、材料上传。\n\n思考：浏览器如何在后续请求中携带登录身份？'),(1,'A 班 · HTTP 登录实验任务','http-lab.txt','HTTP 登录实验\n1. 记录登录请求方法、路径、请求头和参数。\n2. 记录响应状态、Set-Cookie 和响应正文。\n3. 使用 Cookie 请求 /api/me，检查用户、角色与班级。'),(2,'B 班 · 独立教学材料','b-class.md','# B 班独立材料\n\n这份内容只允许班级 B 的成员查看。A 班不能通过猜测材料编号读取它。')]
                for cid,title,name,body in samples:
                    folder = Path(upload_root)/str(cid); folder.mkdir(exist_ok=True)
                    path = folder/('seed-'+name); path.write_text(body,encoding='utf-8')
                    relative_path = f'{cid}/{path.name}'
                    mid = conn.execute('INSERT INTO materials(class_id,title,original_name,file_path,size_bytes,uploaded_by) VALUES (?,?,?,?,?,?)',(cid,title,name,relative_path,len(body.encode()),1 if cid==1 else 3)).lastrowid
                    conn.execute('INSERT INTO knowledge_entries(material_id,class_id,body_text) VALUES (?,?,?)',(mid,cid,body))
                    conn.execute('INSERT INTO lectures(class_id,title,material_id) VALUES (?,?,?)',(cid,title,mid))
                conn.execute('INSERT INTO seed_state VALUES(1)')
    finally:
        conn.close()

def list_materials(conn, class_id, query=''):
    sql = 'SELECT m.id,m.title,m.original_name,m.size_bytes,m.created_at,m.class_id,u.display_name AS uploader FROM materials m JOIN users u ON u.id=m.uploaded_by WHERE m.class_id=?'
    params = [class_id]
    query = (query or '').strip()
    if query:
        sql += ' AND (m.title LIKE ? OR m.original_name LIKE ?)'
        like = f'%{query}%'
        params.extend([like, like])
    sql += ' ORDER BY m.id DESC'
    return conn.execute(sql, params).fetchall()

def get_material(conn, material_id, class_id):
    return conn.execute('SELECT m.*,k.body_text,u.display_name AS uploader FROM materials m JOIN knowledge_entries k ON k.material_id=m.id AND k.class_id=m.class_id JOIN users u ON u.id=m.uploaded_by WHERE m.id=? AND m.class_id=?',(material_id,class_id)).fetchone()

def material_relative_path(stored_path, class_id):
    """Return the safe upload-root-relative path for current and legacy rows."""
    raw = str(stored_path or '').strip()
    if not raw:
        raise ValueError('empty material path')
    normalized = raw.replace('\\', '/')
    lower = normalized.lower()
    marker = '/uploads/'
    if marker in lower:
        normalized = normalized[lower.rfind(marker) + len(marker):]
    elif lower.startswith('uploads/'):
        normalized = normalized[len('uploads/'):]
    elif normalized.startswith('/') or (len(normalized) >= 2 and normalized[1] == ':'):
        raise ValueError('absolute material path must contain uploads directory')
    path = PurePosixPath(normalized)
    parts = path.parts
    if not parts or any(part in ('', '.', '..') for part in parts):
        raise ValueError('unsafe material path')
    if parts[0] != str(class_id):
        raise ValueError('material path class does not match database class_id')
    return '/'.join(parts)

def resolve_material_file(upload_root, stored_path, class_id, must_exist=True):
    """Resolve a DB path below UPLOAD_ROOT/class_id without trusting the DB path."""
    rel = material_relative_path(stored_path, class_id)
    root = Path(upload_root).resolve(strict=must_exist)
    allowed = (root / str(class_id)).resolve(strict=must_exist)
    target = (root / rel).resolve(strict=must_exist)
    target.relative_to(allowed)
    if must_exist and not target.is_file():
        raise ValueError('material path is not a file')
    return target, rel
