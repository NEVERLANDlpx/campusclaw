import hmac
import os
import secrets
import sqlite3
import uuid
from datetime import timedelta
from functools import wraps
from pathlib import Path

import bcrypt
from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import HTTPException
from .db import connect, initialize, list_materials, get_material, resolve_material_file

ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DATABASE=os.environ.get('DATABASE_PATH',str(ROOT/'data/app.db')),
        UPLOAD_ROOT=os.environ.get('UPLOAD_ROOT',str(ROOT/'uploads')),
        SESSION_COOKIE_NAME='campusclaw_session', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE')=='1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2), SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=3*1024*1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('SECRET_KEY must be supplied through the environment (at least 32 characters)')
    app.json.ensure_ascii=False
    # Initialization is an explicit startup step, never run while serving health checks.
    dummy_hash = bcrypt.hashpw(b'nonexistent-user-password',bcrypt.gensalt(rounds=12))

    def db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db',None)
        if conn is not None: conn.close()

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token']=secrets.token_urlsafe(32)
        return session['csrf_token']

    app.jinja_env.globals['csrf_token']=csrf_token

    def check_csrf():
        payload=request.get_json(silent=True) if request.is_json else request.form
        payload=payload if hasattr(payload,'get') else {}
        supplied=request.headers.get('X-CSRF-Token') or payload.get('csrf_token','')
        expected=session.get('csrf_token','')
        if not isinstance(supplied,str) or not expected or not hmac.compare_digest(supplied,expected):
            abort(403,description='请求校验失败，请刷新页面后重试')

    @app.before_request
    def load_user():
        g.user=None
        if request.endpoint in ('static','health'): return
        uid=session.get('user_id')
        if uid:
            row=db().execute('SELECT u.id,u.username,u.display_name,u.role,u.class_id,u.auth_version,c.name AS class_name FROM users u JOIN classes c ON c.id=u.class_id WHERE u.id=?',(uid,)).fetchone()
            if row and row['auth_version']==session.get('auth_version'):
                g.user=row
            else:
                session.clear()

    def login_required(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if g.user is None:
                if request.path.startswith('/api/'):
                    return jsonify(error='请先登录'),401
                return redirect(url_for('login'))
            return fn(*args,**kwargs)
        return wrapped

    def teacher_required():
        if g.user['role']!='teacher': abort(403,description='学生仅可查看本班材料，不能执行写入操作')

    def user_json():
        return {key:g.user[key] for key in ('id','username','display_name','role','class_id','class_name')}

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
        if request.endpoint!='static': response.headers['Cache-Control']='no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages={400:'请求内容不正确',403:'没有执行此操作的权限',404:'材料不存在或不可访问',413:'文件过大，单文件上限为 2 MiB'}
        message=error.description if error.code in (400,403) else messages.get(error.code,'请求失败')
        if request.path.startswith('/api/'):
            return jsonify(error=message),error.code
        return render_template('error.html',code=error.code,message=message),error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception('Database operation failed')
        if request.path.startswith('/api/') or request.path=='/health':
            return jsonify(error='数据库暂不可用'),503
        return render_template('error.html',code=503,message='数据库暂不可用，请稍后重试'),503

    @app.get('/')
    def index():
        return redirect(url_for('materials' if g.user else 'login'))

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='GET':
            if g.user: return redirect(url_for('materials'))
            return render_template('login.html',error=None)
        check_csrf()
        payload=request.get_json(silent=True) if request.is_json else request.form
        payload=payload if isinstance(payload,dict) or hasattr(payload,'get') else {}
        name=payload.get('username',''); password=payload.get('password','')
        name=name.strip() if isinstance(name,str) else ''
        encoded=password.encode('utf-8') if isinstance(password,str) else b''
        row=db().execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
        hashed=row['password_hash'].encode() if row else dummy_hash
        valid=False
        if 0<len(encoded)<=72:
            valid=bcrypt.checkpw(encoded,hashed)
        if not row or not valid:
            session.clear()
            if request.is_json: return jsonify(error='账号或密码错误'),401
            return render_template('login.html',error='账号或密码错误，请重试'),401
        session.clear()
        session.permanent=True
        session.update(user_id=row['id'],role=row['role'],class_id=row['class_id'],auth_version=row['auth_version'],csrf_token=secrets.token_urlsafe(32))
        if request.is_json:
            return jsonify(message='登录成功',user={k:row[k] for k in ('id','username','role','class_id')},csrf_token=session['csrf_token'])
        return redirect(url_for('materials'),code=302)

    @app.post('/logout')
    @login_required
    def logout():
        check_csrf()
        with db(): db().execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(g.user['id'],))
        session.clear()
        return redirect(url_for('login'))

    @app.get('/api/me')
    @login_required
    def me():
        return jsonify(user=user_json(),csrf_token=csrf_token())

    @app.get('/materials')
    @login_required
    def materials():
        rows=list_materials(db(),g.user['class_id'],request.args.get('q',''))
        return render_template('materials.html',rows=rows,total_bytes=sum(r['size_bytes'] for r in rows))

    @app.get('/api/materials')
    @login_required
    def materials_api():
        return jsonify(materials=[dict(r) for r in list_materials(db(),g.user['class_id'],request.args.get('q',''))])

    @app.get('/materials/<int:mid>')
    @login_required
    def detail(mid):
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        return render_template('detail.html',material=row)

    @app.get('/api/materials/<int:mid>')
    @login_required
    def detail_api(mid):
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        return jsonify(material={k:row[k] for k in ('id','title','original_name','class_id','size_bytes','created_at','body_text','uploader')})

    @app.get('/api/materials/<int:mid>/download')
    @login_required
    def download_material(mid):
        # Same-class students may read/download; teacher write permission is not needed.
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        try:
            target,_=resolve_material_file(app.config['UPLOAD_ROOT'],row['file_path'],g.user['class_id'],must_exist=True)
            # Only use a database-selected path; never accept a path from the client.
            filename=row['original_name'].replace('\\','/').split('/')[-1]
            filename=''.join(c for c in filename if ord(c)>=32 and ord(c)!=127).strip()
            return send_file(target,as_attachment=True,download_name=filename or 'material.txt',
                             mimetype='application/octet-stream',conditional=False,etag=False,max_age=0)
        except (OSError,ValueError,RuntimeError):
            abort(404)

    @app.post('/api/materials/upload')
    @login_required
    def upload():
        teacher_required(); check_csrf()
        file=request.files.get('file')
        if not file or not file.filename: abort(400,description='请选择 txt 或 md 文件')
        original=file.filename.replace('\\','/').split('/')[-1][:180]
        suffix=Path(original).suffix.lower()
        if suffix not in ('.txt','.md'): abort(400,description='仅支持 UTF-8 编码的 txt 和 md 文件')
        blob=file.read(2*1024*1024+1)
        if len(blob)>2*1024*1024: abort(413)
        try: body=blob.decode('utf-8-sig')
        except UnicodeDecodeError: abort(400,description='文件不是有效的 UTF-8 文本')
        if not body.strip() or any(ord(ch)<32 and ch not in '\t\r\n' for ch in body):
            abort(400,description='文件为空或包含二进制内容')
        title=(request.form.get('title','').strip() or Path(original).stem)[:120]
        cid=g.user['class_id']
        folder=Path(app.config['UPLOAD_ROOT'])/str(cid)
        path=folder/(uuid.uuid4().hex+suffix)
        try:
            folder.mkdir(parents=True,exist_ok=True)
            path.write_bytes(blob)
            relative_path=f'{cid}/{path.name}'
            with db():
                mid=db().execute('INSERT INTO materials(class_id,title,original_name,file_path,size_bytes,uploaded_by) VALUES (?,?,?,?,?,?)',(cid,title,original,relative_path,len(blob),g.user['id'])).lastrowid
                db().execute('INSERT INTO knowledge_entries(material_id,class_id,body_text) VALUES (?,?,?)',(mid,cid,body))
                db().execute('INSERT INTO lectures(class_id,title,material_id) VALUES (?,?,?)',(cid,title,mid))
        except (OSError,sqlite3.Error):
            path.unlink(missing_ok=True)
            app.logger.exception('Upload failed; new file removed and transaction rolled back')
            return jsonify(error='存储失败，请稍后重试'),503
        return jsonify(message='材料已上传并写入知识库',material_id=mid,class_id=cid),201

    @app.post('/api/materials/<int:mid>/delete')
    @login_required
    def delete(mid):
        teacher_required(); check_csrf()
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        try:
            path,_=resolve_material_file(app.config['UPLOAD_ROOT'],row['file_path'],g.user['class_id'],must_exist=False)
        except (OSError,ValueError,RuntimeError):
            abort(404)
        staged=path.with_name(path.name+'.deleting-'+uuid.uuid4().hex)
        moved=False
        try:
            if path.exists(): path.rename(staged); moved=True
            with db(): db().execute('DELETE FROM materials WHERE id=? AND class_id=?',(mid,g.user['class_id']))
        except (sqlite3.Error,OSError):
            if moved: staged.rename(path)
            return jsonify(error='删除失败，请稍后重试'),503
        if moved:
            try: staged.unlink()
            except OSError: app.logger.warning('Deferred deletion required: %s',staged)
        return jsonify(message='材料及知识条目已删除')

    @app.get('/health')
    def health():
        try:
            db().execute('SELECT id FROM classes LIMIT 1').fetchone()
        except sqlite3.Error:
            return jsonify(status='error',database='unavailable'),503
        return jsonify(status='ok',database='ok')

    return app
