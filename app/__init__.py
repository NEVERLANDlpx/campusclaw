import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, session, stream_with_context, url_for
from werkzeug.exceptions import HTTPException
from jsonschema import Draft202012Validator, SchemaError
from .ai_clients import AIClientError, ChatClient, EmbeddingClient
from .db import DEFAULT_ASSISTANT_PROMPT, connect, initialize, list_materials, get_material, resolve_material_file
from .knowledge import rebuild_material_index, search_knowledge, safe_error
from .assistant_core import (dump_log_json, instruction_hash, parse_tool_ref, render_template as render_prompt_template,
                             route_skill, validate_template)
from .mcp_client import DEFAULT_ALLOWED_HOSTS, MCPClient, MCPClientError, validate_mcp_endpoint
from .orchestrator import available_tools, evidence_messages, run_tool_loop

ROOT = Path(__file__).resolve().parents[1]


def load_local_env():
    env_path = ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
        JWT_SECRET_KEY=os.environ.get('JWT_SECRET_KEY') or os.environ.get('SECRET_KEY'),
        JWT_ISSUER=os.environ.get('JWT_ISSUER','campusclaw'),
        JWT_ACCESS_TOKEN_SECONDS=int(os.environ.get('JWT_ACCESS_TOKEN_SECONDS','3600')),
        EMBEDDING_BASE_URL=os.environ.get('EMBEDDING_BASE_URL',''),
        EMBEDDING_API_KEY=os.environ.get('EMBEDDING_API_KEY',''),
        EMBEDDING_MODEL=os.environ.get('EMBEDDING_MODEL',''),
        EMBEDDING_DIM=os.environ.get('EMBEDDING_DIM',''),
        CHAT_BASE_URL=os.environ.get('CHAT_BASE_URL') or os.environ.get('EMBEDDING_BASE_URL',''),
        CHAT_API_KEY=os.environ.get('CHAT_API_KEY') or os.environ.get('EMBEDDING_API_KEY',''),
        CHAT_MODEL=os.environ.get('CHAT_MODEL',''),
        MCP_MAX_TOOL_ROUNDS=int(os.environ.get('MCP_MAX_TOOL_ROUNDS','3')),
        MCP_MAX_TOTAL_CALLS=int(os.environ.get('MCP_MAX_TOTAL_CALLS','5')),
        MCP_ALLOWED_HOSTS=os.environ.get('MCP_ALLOWED_HOSTS',DEFAULT_ALLOWED_HOSTS),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get('JWT_SECRET_KEY'):
        app.config['JWT_SECRET_KEY']=app.config.get('SECRET_KEY')
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
        raise RuntimeError('SECRET_KEY must be supplied through the environment (at least 32 characters)')
    if not app.config['JWT_SECRET_KEY'] or len(app.config['JWT_SECRET_KEY'])<32:
        raise RuntimeError('JWT_SECRET_KEY or SECRET_KEY must be supplied through the environment (at least 32 characters)')
    if (
        test_config is None
        and all(app.config.get(key) for key in ('EMBEDDING_BASE_URL','EMBEDDING_API_KEY','EMBEDDING_MODEL','EMBEDDING_DIM'))
        and not app.config.get('TESTING')
    ):
        EmbeddingClient(
            app.config['EMBEDDING_BASE_URL'], app.config['EMBEDDING_API_KEY'],
            app.config['EMBEDDING_MODEL'], app.config['EMBEDDING_DIM']
        ).validate_dimension()
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

    def issue_access_token(row):
        now=datetime.now(timezone.utc)
        expires_in=app.config['JWT_ACCESS_TOKEN_SECONDS']
        payload={
            'iss':app.config['JWT_ISSUER'],
            'sub':str(row['id']),
            'iat':now,
            'nbf':now,
            'exp':now+timedelta(seconds=expires_in),
            'auth_version':row['auth_version'],
            'role':row['role'],
            'class_id':row['class_id'],
        }
        return jwt.encode(payload,app.config['JWT_SECRET_KEY'],algorithm='HS256'),expires_in

    def authenticate_credentials(payload):
        payload=payload if isinstance(payload,dict) or hasattr(payload,'get') else {}
        name=payload.get('username',''); password=payload.get('password','')
        name=name.strip() if isinstance(name,str) else ''
        encoded=password.encode('utf-8') if isinstance(password,str) else b''
        row=db().execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
        hashed=row['password_hash'].encode() if row else dummy_hash
        valid=False
        if 0<len(encoded)<=72:
            valid=bcrypt.checkpw(encoded,hashed)
        return row if row and valid else None

    def token_error():
        return jsonify(error='Bearer Token 无效或已过期'),401

    def load_bearer_user():
        header=request.headers.get('Authorization','')
        parts=header.split()
        if len(parts)!=2 or parts[0].lower()!='bearer':
            return False
        try:
            claims=jwt.decode(
                parts[1],
                app.config['JWT_SECRET_KEY'],
                algorithms=['HS256'],
                issuer=app.config['JWT_ISSUER'],
                options={'require':['exp','iat','nbf','iss','sub','auth_version']},
            )
            uid=int(claims['sub'])
            version=int(claims['auth_version'])
        except (jwt.PyJWTError, ValueError, TypeError):
            return False
        row=db().execute('SELECT u.id,u.username,u.display_name,u.role,u.class_id,u.auth_version,c.name AS class_name FROM users u JOIN classes c ON c.id=u.class_id WHERE u.id=?',(uid,)).fetchone()
        if not row or row['auth_version']!=version:
            return False
        g.user=row
        return True

    def bearer_required(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not load_bearer_user():
                return token_error()
            return fn(*args,**kwargs)
        return wrapped

    def teacher_required():
        if g.user['role']!='teacher': abort(403,description='学生仅可查看本班材料，不能执行写入操作')

    def user_json():
        return {key:g.user[key] for key in ('id','username','display_name','role','class_id','class_name')}

    def embedding_client():
        return app.config.get('EMBEDDING_CLIENT') or EmbeddingClient(
            app.config.get('EMBEDDING_BASE_URL',''),
            app.config.get('EMBEDDING_API_KEY',''),
            app.config.get('EMBEDDING_MODEL',''),
            app.config.get('EMBEDDING_DIM',''),
        )

    def chat_client():
        return app.config.get('CHAT_CLIENT') or ChatClient(
            app.config.get('CHAT_BASE_URL',''),
            app.config.get('CHAT_API_KEY',''),
            app.config.get('CHAT_MODEL',''),
        )

    def get_prompt(class_id):
        row=db().execute('SELECT content FROM assistant_prompts WHERE class_id=?',(class_id,)).fetchone()
        return row['content'] if row else DEFAULT_ASSISTANT_PROMPT

    def get_skill_enabled(class_id):
        row=db().execute("SELECT enabled FROM assistant_skill_settings WHERE class_id=? AND skill_key='solving_guidance'",(class_id,)).fetchone()
        return bool(row['enabled']) if row else False

    def mcp_client():
        return app.config.get('MCP_CLIENT') or MCPClient()

    def get_assistant_app(app_id=None, enabled_only=True):
        params=[g.user['class_id']]
        condition='a.class_id=?'
        if app_id not in (None, ''):
            try:
                parsed=int(app_id)
            except (TypeError, ValueError):
                abort(400,description='app_id 不正确')
            condition += ' AND a.id=?'; params.append(parsed)
        else:
            condition += " AND a.app_key='knowledge_qa'"
        if enabled_only:
            condition += ' AND a.enabled=1'
        row=db().execute(
            f'''SELECT a.*,c.name AS class_name FROM assistant_apps a
                JOIN classes c ON c.id=a.class_id WHERE {condition}''', params).fetchone()
        if row is None:
            abort(404)
        return row

    def render_app_prompt(app_row, skill):
        knowledge_policy = (
            '只依据本次提供的本班知识证据回答；引用使用 [1]、[2]，没有证据时不得虚构来源。'
            if app_row['retrieval_enabled'] else '本应用未启用知识库检索，不得声称已经查阅班级资料。'
        )
        skill_content = ''
        if skill:
            skill_content = f"Skill: {skill['skill_key']}\n{skill['content']}"
        template=app_row['system_prompt_template']
        rendered=render_prompt_template(template, {
            'app_name':app_row['name'], 'class_name':app_row['class_name'],
            'knowledge_policy':knowledge_policy, 'skill_content':skill_content,
        })
        if '{{knowledge_policy}}' not in template:
            rendered += '\n\nKnowledge policy:\n' + knowledge_policy
        if skill_content and '{{skill_content}}' not in template:
            rendered += '\n\n' + skill_content
        return rendered

    def sse(event, data):
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def create_or_get_conversation(conversation_id):
        cid=g.user['class_id']; uid=g.user['id']
        if conversation_id:
            try: conversation_id=int(conversation_id)
            except (TypeError,ValueError): abort(400,description='conversation_id 不正确')
            row=db().execute('SELECT id FROM assistant_conversations WHERE id=? AND user_id=? AND class_id=?',(conversation_id,uid,cid)).fetchone()
            if row is None: abort(404)
            return conversation_id
        with db():
            return db().execute('INSERT INTO assistant_conversations(user_id,class_id) VALUES (?,?)',(uid,cid)).lastrowid

    def citation_payload(hits):
        citations=[]
        for idx,hit in enumerate(hits, start=1):
            item=dict(hit)
            item['citation_id']=f'[{idx}]'
            citations.append(item)
        return citations

    def build_messages(question, hits, prompt, skill_enabled):
        evidence=[]
        for idx,hit in enumerate(hits, start=1):
            evidence.append(
                f'[{idx}] material_title={hit["material_title"]}; material_id={hit["material_id"]}; '
                f'chunk_id={hit["chunk_id"]}; chunk_index={hit["chunk_index"]}; '
                f'offsets={hit["start_offset"]}-{hit["end_offset"]}\n{hit["excerpt"]}'
            )
        system=prompt + '\n\n只能依据下列 evidence 回答；引用必须使用 evidence 编号，例如 [1]。不得编造材料标题、chunk id 或出处。'
        if skill_enabled:
            system += '\n\nSkill: solving_guidance\n以启发式方式引导学生，优先给解题思路和关键步骤，引用本班资料，不直接给出最终答案，可通过问题引导学生继续思考。'
        return [
            {'role':'system','content':system},
            {'role':'user','content':'Knowledge evidence:\n\n'+'\n\n'.join(evidence)+'\n\nQuestion:\n'+question},
        ]

    def public_user_json(row):
        keys=('id','username','display_name','role','class_id')
        data={key:row[key] for key in keys}
        class_row=db().execute('SELECT name FROM classes WHERE id=?',(row['class_id'],)).fetchone()
        data['class_name']=class_row['name'] if class_row else ''
        return data

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
            # The server cannot observe the tab-scoped Bearer token in sessionStorage.
            # Always keep /login as a stable recovery page for mixed Session/Token state.
            return render_template('login.html',error=None)
        check_csrf()
        payload=request.get_json(silent=True) if request.is_json else request.form
        row=authenticate_credentials(payload)
        if not row:
            session.clear()
            if request.is_json: return jsonify(error='账号或密码错误'),401
            return render_template('login.html',error='账号或密码错误，请重试'),401
        session.clear()
        session.permanent=True
        session.update(user_id=row['id'],role=row['role'],class_id=row['class_id'],auth_version=row['auth_version'],csrf_token=secrets.token_urlsafe(32))
        if request.is_json:
            return jsonify(message='登录成功',user={k:row[k] for k in ('id','username','role','class_id')},csrf_token=session['csrf_token'])
        return redirect(url_for('materials'),code=302)

    @app.post('/api/auth/token')
    def token_login():
        payload=request.get_json(silent=True) if request.is_json else request.form
        row=authenticate_credentials(payload)
        if not row:
            session.clear()
            return jsonify(error='账号或密码错误'),401
        session.clear()
        session.permanent=True
        session.update(user_id=row['id'],role=row['role'],class_id=row['class_id'],auth_version=row['auth_version'],csrf_token=secrets.token_urlsafe(32))
        access_token,expires_in=issue_access_token(row)
        return jsonify(
            access_token=access_token,
            token_type='bearer',
            expires_in=expires_in,
            user=public_user_json(row),
            csrf_token=session['csrf_token'],
        )

    @app.post('/api/auth/logout')
    def api_logout():
        logout_user=g.user
        if logout_user is None and load_bearer_user():
            logout_user=g.user
        if logout_user is not None:
            with db():
                db().execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(logout_user['id'],))
        session.clear()
        return jsonify(message='已退出登录')

    @app.post('/logout')
    @login_required
    def logout():
        check_csrf()
        with db(): db().execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?',(g.user['id'],))
        session.clear()
        return redirect(url_for('login'))

    @app.get('/api/me')
    @bearer_required
    def me():
        return jsonify(user=user_json(),csrf_token=csrf_token())

    @app.get('/materials')
    @login_required
    def materials():
        rows=list_materials(db(),g.user['class_id'],request.args.get('q',''))
        return render_template('materials.html',rows=rows,total_bytes=sum(r['size_bytes'] for r in rows))

    @app.get('/api/materials')
    @bearer_required
    def materials_api():
        return jsonify(materials=[dict(r) for r in list_materials(db(),g.user['class_id'],request.args.get('q',''))])

    @app.get('/materials/<int:mid>')
    @login_required
    def detail(mid):
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        return render_template('detail.html',material=row)

    @app.get('/api/materials/<int:mid>')
    @bearer_required
    def detail_api(mid):
        row=get_material(db(),mid,g.user['class_id'])
        if row is None: abort(404)
        return jsonify(material={k:row[k] for k in ('id','title','original_name','class_id','size_bytes','created_at','body_text','uploader')})

    @app.get('/api/materials/<int:mid>/download')
    @bearer_required
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
    @bearer_required
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
            index_result=rebuild_material_index(db(),mid,cid,embedding_client())
        except (OSError,sqlite3.Error):
            path.unlink(missing_ok=True)
            app.logger.exception('Upload failed; new file removed and transaction rolled back')
            return jsonify(error='存储失败，请稍后重试'),503
        return jsonify(message='材料已上传并写入知识库',material_id=mid,class_id=cid,index=index_result),201

    @app.post('/api/materials/<int:mid>/delete')
    @bearer_required
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

    @app.get('/api/knowledge/search')
    @bearer_required
    def knowledge_search_api():
        query=request.args.get('q','')
        mode=request.args.get('mode','hybrid')
        try:
            client=None if mode=='keyword' else embedding_client()
            results,meta=search_knowledge(db(),g.user['class_id'],query,mode,client)
        except ValueError as exc:
            abort(400,description=str(exc))
        except AIClientError:
            return jsonify(error='知识检索暂不可用'),503
        return jsonify(results=results,**meta)

    @app.get('/api/assistant/prompt')
    @bearer_required
    def assistant_prompt_get():
        return jsonify(prompt=get_assistant_app()['system_prompt_template'])

    @app.put('/api/assistant/prompt')
    @bearer_required
    def assistant_prompt_put():
        teacher_required()
        payload=request.get_json(silent=True) or {}
        content=str(payload.get('content','')).strip()
        try: validate_template(content)
        except ValueError as exc: abort(400,description=str(exc))
        with db():
            db().execute(
                '''INSERT INTO assistant_prompts(class_id,content,updated_by,updated_at) VALUES (?,?,?,strftime('%Y-%m-%d %H:%M:%S','now'))
                   ON CONFLICT(class_id) DO UPDATE SET content=excluded.content,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                (g.user['class_id'],content,g.user['id']),
            )
            db().execute(
                "UPDATE assistant_apps SET system_prompt_template=?,updated_by=?,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE class_id=? AND app_key='knowledge_qa'",
                (content,g.user['id'],g.user['class_id']),
            )
        return jsonify(prompt=content)

    @app.get('/api/assistant/skills')
    @bearer_required
    def assistant_skills_get():
        rows=db().execute('SELECT id,skill_key,name,description,content,trigger_keywords,source_type,enabled,priority,updated_at FROM skills WHERE class_id=? ORDER BY id',(g.user['class_id'],)).fetchall()
        tool_refs={}
        if g.user['role']=='teacher':
            for binding in db().execute(
                '''SELECT ast.skill_id,ast.tool_ref FROM assistant_skill_tools ast
                   JOIN skills s ON s.id=ast.skill_id WHERE s.class_id=? ORDER BY ast.tool_ref''',
                (g.user['class_id'],)):
                tool_refs.setdefault(binding['skill_id'],[]).append(binding['tool_ref'])
        skills={row['skill_key']:dict(row) for row in rows}
        if 'solving_guidance' in skills:
            skills['solving_guidance']['enabled']=get_skill_enabled(g.user['class_id'])
        if g.user['role']!='teacher':
            for item in skills.values():
                item.pop('content',None)
        items=[]
        for row in rows:
            item=dict(row)
            if item['skill_key']=='solving_guidance':
                item['enabled']=skills['solving_guidance']['enabled']
            if g.user['role']!='teacher':
                item.pop('content',None)
            else:
                item['tool_refs']=tool_refs.get(item['id'],[])
            items.append(item)
        return jsonify(skills=skills,items=items)

    @app.put('/api/assistant/skills/solving-guidance')
    @bearer_required
    def assistant_skill_put():
        teacher_required()
        payload=request.get_json(silent=True) or {}
        enabled=1 if bool(payload.get('enabled')) else 0
        with db():
            db().execute(
                '''INSERT INTO assistant_skill_settings(class_id,skill_key,enabled,updated_by,updated_at)
                   VALUES (?,'solving_guidance',?,?,strftime('%Y-%m-%d %H:%M:%S','now'))
                   ON CONFLICT(class_id,skill_key) DO UPDATE SET enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                (g.user['class_id'],enabled,g.user['id']),
            )
            skill=db().execute("SELECT id FROM skills WHERE class_id=? AND skill_key='solving_guidance'",(g.user['class_id'],)).fetchone()
            default_app=db().execute("SELECT id FROM assistant_apps WHERE class_id=? AND app_key='knowledge_qa'",(g.user['class_id'],)).fetchone()
            if skill:
                db().execute("UPDATE skills SET enabled=?,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",(enabled,skill['id']))
            if enabled and skill and default_app:
                db().execute('INSERT OR IGNORE INTO assistant_app_skills(app_id,skill_id,priority) VALUES (?,?,200)',(default_app['id'],skill['id']))
        return jsonify(skill='solving_guidance',enabled=bool(enabled))

    @app.get('/api/assistant/apps')
    @bearer_required
    def assistant_apps_get():
        rows=db().execute(
            '''SELECT a.id,a.app_key,a.name,a.description,a.model_override,a.temperature,a.max_tokens,
                      a.retrieval_enabled,a.retrieval_mode,a.top_k,a.enabled,a.updated_at,
                      COUNT(aks.skill_id) AS skill_count
               FROM assistant_apps a LEFT JOIN assistant_app_skills aks ON aks.app_id=a.id
               WHERE a.class_id=? AND a.enabled=1 GROUP BY a.id ORDER BY a.id''',
            (g.user['class_id'],),).fetchall()
        return jsonify(apps=[dict(row) for row in rows])

    @app.get('/api/assistant/apps/<int:app_id>')
    @bearer_required
    def assistant_app_get(app_id):
        row=get_assistant_app(app_id,enabled_only=False)
        skills=[dict(item) for item in db().execute(
            '''SELECT s.id,s.skill_key,s.name,s.description,s.enabled,aks.priority
               FROM assistant_app_skills aks JOIN skills s ON s.id=aks.skill_id
               WHERE aks.app_id=? ORDER BY aks.priority DESC,s.id''',(app_id,))]
        return jsonify(app=dict(row),skills=skills)

    @app.put('/api/assistant/apps/<int:app_id>')
    @bearer_required
    def assistant_app_put(app_id):
        teacher_required(); row=get_assistant_app(app_id,enabled_only=False)
        payload=request.get_json(silent=True) or {}
        prompt=payload.get('system_prompt_template',row['system_prompt_template'])
        template_id=payload.get('template_id')
        if template_id is not None:
            template=db().execute('SELECT content FROM prompt_templates WHERE id=? AND class_id=?',(template_id,g.user['class_id'])).fetchone()
            if not template: abort(404)
            prompt=template['content']
        try: validate_template(str(prompt))
        except ValueError as exc: abort(400,description=str(exc))
        try:
            temperature=float(payload.get('temperature',row['temperature']))
            max_tokens=int(payload.get('max_tokens',row['max_tokens']))
            top_k=int(payload.get('top_k',row['top_k']))
        except (TypeError,ValueError): abort(400,description='应用参数格式不正确')
        mode=payload.get('retrieval_mode',row['retrieval_mode'])
        if not 0 <= temperature <= 2 or not 1 <= max_tokens <= 8192 or not 1 <= top_k <= 12 or mode not in ('keyword','vector','hybrid'):
            abort(400,description='应用参数超出允许范围')
        retrieval=1 if bool(payload.get('retrieval_enabled',row['retrieval_enabled'])) else 0
        enabled=1 if bool(payload.get('enabled',row['enabled'])) else 0
        model_override=str(payload.get('model_override',row['model_override']) or '').strip()[:120] or None
        with db():
            db().execute(
                '''UPDATE assistant_apps SET system_prompt_template=?,model_override=?,temperature=?,max_tokens=?,
                   retrieval_enabled=?,retrieval_mode=?,top_k=?,enabled=?,updated_by=?,
                   updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=? AND class_id=?''',
                (prompt,model_override,temperature,max_tokens,retrieval,mode,top_k,enabled,g.user['id'],app_id,g.user['class_id']))
        return jsonify(app=dict(get_assistant_app(app_id,enabled_only=False)))

    @app.get('/api/assistant/prompt-templates')
    @bearer_required
    def prompt_templates_get():
        rows=db().execute('SELECT * FROM prompt_templates WHERE class_id=? ORDER BY is_builtin DESC,id',(g.user['class_id'],)).fetchall()
        return jsonify(templates=[dict(row) for row in rows])

    @app.post('/api/assistant/prompt-templates')
    @bearer_required
    def prompt_templates_post():
        teacher_required(); payload=request.get_json(silent=True) or {}
        name=str(payload.get('name','')).strip()[:120]
        content=str(payload.get('content','')).strip()
        if not name: abort(400,description='模板名称不能为空')
        try: variables=sorted(validate_template(content))
        except ValueError as exc: abort(400,description=str(exc))
        try:
            with db():
                tid=db().execute(
                    '''INSERT INTO prompt_templates(class_id,name,description,content,variables_json,is_builtin,created_by)
                       VALUES (?,?,?,?,?,0,?)''',
                    (g.user['class_id'],name,str(payload.get('description',''))[:500],content,json.dumps(variables),g.user['id'])).lastrowid
        except sqlite3.IntegrityError: abort(400,description='模板名称已存在')
        return jsonify(id=tid),201

    @app.post('/api/assistant/skills')
    @bearer_required
    def assistant_skills_post():
        teacher_required(); payload=request.get_json(silent=True) or {}
        key=str(payload.get('skill_key','')).strip()
        name=str(payload.get('name','')).strip()
        content=str(payload.get('content','')).strip()
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}',key) or not name or not content:
            abort(400,description='Skill 标识、名称或内容不正确')
        try:
            with db():
                sid=db().execute(
                    '''INSERT INTO skills(class_id,skill_key,name,description,content,trigger_keywords,source_type,enabled,created_by,priority,created_at,updated_at)
                       VALUES (?,?,?,?,?,?, 'uploaded',1,?,?,strftime('%Y-%m-%d %H:%M:%S','now'),strftime('%Y-%m-%d %H:%M:%S','now'))''',
                    (g.user['class_id'],key,name,str(payload.get('description',''))[:500],content[:50000],str(payload.get('trigger_keywords',''))[:1000],g.user['id'],int(payload.get('priority',100)))).lastrowid
        except (sqlite3.IntegrityError,ValueError): abort(400,description='Skill 标识已存在或参数不正确')
        return jsonify(id=sid),201

    @app.post('/api/assistant/skills/upload')
    @bearer_required
    def assistant_skill_upload():
        teacher_required(); file=request.files.get('file')
        if not file or not file.filename or Path(file.filename).suffix.lower() not in ('.md','.markdown'):
            abort(400,description='只接受 Markdown Skill 文件')
        blob=file.read(256*1024+1)
        if len(blob)>256*1024: abort(413)
        try: content=blob.decode('utf-8-sig')
        except UnicodeDecodeError: abort(400,description='Skill 文件必须是 UTF-8')
        if not content.strip() or any(ord(ch)<32 and ch not in '\t\r\n' for ch in content):
            abort(400,description='Skill 文件为空或包含二进制内容')
        title_match=re.search(r'^#\s+(.+)$',content,re.M)
        name=(request.form.get('name') or (title_match.group(1).strip() if title_match else Path(file.filename).stem))[:120]
        key=(request.form.get('skill_key') or re.sub(r'[^a-z0-9_-]+','-',Path(file.filename).stem.lower()).strip('-'))[:64]
        keywords=request.form.get('trigger_keywords','')[:1000]
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}',key): abort(400,description='Skill 标识不正确')
        try:
            with db():
                sid=db().execute(
                    '''INSERT INTO skills(class_id,skill_key,name,description,content,trigger_keywords,source_type,enabled,created_by,priority,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,'uploaded',1,?,100,strftime('%Y-%m-%d %H:%M:%S','now'),strftime('%Y-%m-%d %H:%M:%S','now'))''',
                    (g.user['class_id'],key,name,request.form.get('description','')[:500],content,keywords,g.user['id'])).lastrowid
        except sqlite3.IntegrityError: abort(400,description='Skill 标识已存在')
        return jsonify(id=sid,name=name,skill_key=key,source_type='uploaded'),201

    @app.put('/api/assistant/skills/<int:skill_id>')
    @bearer_required
    def assistant_skill_update(skill_id):
        teacher_required()
        row=db().execute('SELECT * FROM skills WHERE id=? AND class_id=?',(skill_id,g.user['class_id'])).fetchone()
        if not row: abort(404)
        payload=request.get_json(silent=True) or {}
        name=str(payload.get('name',row['name'])).strip()[:120]
        description=str(payload.get('description',row['description'])).strip()[:500]
        content=str(payload.get('content',row['content'])).strip()[:50000]
        keywords=str(payload.get('trigger_keywords',row['trigger_keywords'])).strip()[:1000]
        enabled=1 if bool(payload.get('enabled',row['enabled'])) else 0
        try: priority=int(payload.get('priority',row['priority']))
        except (TypeError,ValueError): abort(400,description='Skill 优先级不正确')
        if not name or not content or not -1000 <= priority <= 1000: abort(400,description='Skill 内容或优先级不正确')
        with db():
            db().execute(
                '''UPDATE skills SET name=?,description=?,content=?,trigger_keywords=?,enabled=?,priority=?,
                   updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=? AND class_id=?''',
                (name,description,content,keywords,enabled,priority,skill_id,g.user['class_id']))
            if row['skill_key']=='solving_guidance':
                db().execute(
                    '''INSERT INTO assistant_skill_settings(class_id,skill_key,enabled,updated_by,updated_at)
                       VALUES (?,'solving_guidance',?,?,strftime('%Y-%m-%d %H:%M:%S','now'))
                       ON CONFLICT(class_id,skill_key) DO UPDATE SET enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                    (g.user['class_id'],enabled,g.user['id']))
        return jsonify(id=skill_id,enabled=bool(enabled))

    @app.put('/api/assistant/apps/<int:app_id>/skills')
    @bearer_required
    def assistant_app_skills_put(app_id):
        teacher_required(); get_assistant_app(app_id,enabled_only=False)
        payload=request.get_json(silent=True) or {}; skill_ids=payload.get('skill_ids',[])
        if not isinstance(skill_ids,list) or any(not isinstance(item,int) for item in skill_ids): abort(400,description='skill_ids 不正确')
        if skill_ids:
            placeholders=','.join('?' for _ in skill_ids)
            count=db().execute(f'SELECT COUNT(*) FROM skills WHERE class_id=? AND id IN ({placeholders})',[g.user['class_id'],*skill_ids]).fetchone()[0]
            if count != len(set(skill_ids)): abort(404)
        existing={row['skill_id']:row['priority'] for row in db().execute(
            'SELECT skill_id,priority FROM assistant_app_skills WHERE app_id=?',(app_id,))}
        with db():
            db().execute('DELETE FROM assistant_app_skills WHERE app_id=?',(app_id,))
            for sid in dict.fromkeys(skill_ids):
                priority=existing.get(sid,100)
                db().execute('INSERT INTO assistant_app_skills(app_id,skill_id,priority) VALUES (?,?,?)',(app_id,sid,priority))
        return jsonify(skill_ids=list(dict.fromkeys(skill_ids)))

    @app.put('/api/assistant/skills/<int:skill_id>/tools')
    @bearer_required
    def assistant_skill_tools_put(skill_id):
        teacher_required()
        if not db().execute('SELECT 1 FROM skills WHERE id=? AND class_id=?',(skill_id,g.user['class_id'])).fetchone(): abort(404)
        refs=(request.get_json(silent=True) or {}).get('tool_refs',[])
        if not isinstance(refs,list): abort(400,description='tool_refs 不正确')
        for ref in refs:
            try: tool_name,server_name=parse_tool_ref(ref)
            except ValueError as exc: abort(400,description=str(exc))
            found=db().execute(
                '''SELECT dt.input_schema_json FROM mcp_servers s JOIN mcp_discovered_tools dt ON dt.server_id=s.id
                   WHERE s.class_id=? AND s.name=? AND s.connection_status='connected' AND dt.tool_name=?''',
                (g.user['class_id'],server_name,tool_name)).fetchone()
            if not found: abort(400,description=f'工具当前不可绑定：{ref}')
            try: Draft202012Validator.check_schema(json.loads(found['input_schema_json']))
            except (json.JSONDecodeError,SchemaError): abort(400,description=f'工具 Schema 无效：{ref}')
        with db():
            db().execute('DELETE FROM assistant_skill_tools WHERE skill_id=?',(skill_id,))
            for ref in dict.fromkeys(refs): db().execute('INSERT INTO assistant_skill_tools(skill_id,tool_ref) VALUES (?,?)',(skill_id,ref))
        return jsonify(tool_refs=list(dict.fromkeys(refs)))

    @app.get('/api/assistant/conversations/<int:conversation_id>')
    @bearer_required
    def assistant_conversation_get(conversation_id):
        row=db().execute('SELECT id,created_at FROM assistant_conversations WHERE id=? AND user_id=? AND class_id=?',(conversation_id,g.user['id'],g.user['class_id'])).fetchone()
        if row is None: abort(404)
        messages=[dict(r) for r in db().execute('SELECT id,role,content,created_at FROM assistant_messages WHERE conversation_id=? ORDER BY id',(conversation_id,))]
        return jsonify(conversation=dict(row),messages=messages)

    @app.get('/api/mcp/servers')
    @bearer_required
    def mcp_servers_get():
        teacher_required()
        rows=db().execute(
            '''SELECT id,name,endpoint_url,token_env_key,connection_status,last_error,last_connected_at,updated_at
               FROM mcp_servers WHERE class_id=? ORDER BY id''',(g.user['class_id'],)).fetchall()
        return jsonify(servers=[dict(row) for row in rows])

    @app.post('/api/mcp/servers')
    @bearer_required
    def mcp_servers_post():
        teacher_required(); payload=request.get_json(silent=True) or {}
        name=str(payload.get('name','')).strip(); endpoint=str(payload.get('endpoint_url','')).strip()
        env_key=str(payload.get('token_env_key','')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name): abort(400,description='服务器名称不正确')
        if not re.fullmatch(r'https?://[^\s]{1,500}',endpoint): abort(400,description='MCP 端点必须是 HTTP(S) URL')
        try: validate_mcp_endpoint(endpoint,app.config['MCP_ALLOWED_HOSTS'])
        except ValueError as exc: abort(400,description=str(exc))
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,127}',env_key): abort(400,description='token_env_key 不正确')
        try:
            with db():
                sid=db().execute(
                    'INSERT INTO mcp_servers(class_id,name,endpoint_url,token_env_key,created_by) VALUES (?,?,?,?,?)',
                    (g.user['class_id'],name,endpoint,env_key,g.user['id'])).lastrowid
        except sqlite3.IntegrityError: abort(400,description='服务器名称已存在')
        return jsonify(id=sid),201

    @app.post('/api/mcp/servers/<int:server_id>/connect')
    @bearer_required
    def mcp_server_connect(server_id):
        teacher_required()
        server=db().execute('SELECT * FROM mcp_servers WHERE id=? AND class_id=?',(server_id,g.user['class_id'])).fetchone()
        if not server: abort(404)
        try:
            validate_mcp_endpoint(server['endpoint_url'],app.config['MCP_ALLOWED_HOSTS'])
        except ValueError as exc:
            detail=str(exc)
            with db(): db().execute("UPDATE mcp_servers SET connection_status='error',last_error=?,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",(detail,server_id))
            return jsonify(error=detail),400
        token=os.environ.get(server['token_env_key'],'')
        if not token:
            with db(): db().execute("UPDATE mcp_servers SET connection_status='error',last_error=?,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",('令牌环境变量未配置',server_id))
            return jsonify(error='MCP 令牌环境变量未配置'),503
        try:
            tools=mcp_client().discover(server['endpoint_url'],token)
            names=set()
            for tool in tools:
                name=tool.get('name'); schema=tool.get('input_schema')
                if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name) or name in names:
                    raise ValueError('发现结果包含无效或重复工具名')
                Draft202012Validator.check_schema(schema); names.add(name)
        except Exception as exc:
            raw=safe_error(exc)[:500]
            lowered=raw.casefold()
            if '401' in lowered or '403' in lowered or 'unauthorized' in lowered or 'forbidden' in lowered:
                detail='MCP 认证失败：请检查令牌环境变量名及容器配置'
            elif 'timeout' in lowered or 'timed out' in lowered:
                detail='MCP 连接或协议响应超时'
            elif any(marker in lowered for marker in ('connect', 'name or service', 'name resolution', 'temporary failure', 'nodename', 'getaddrinfo')):
                detail='MCP 网络连接失败：无法访问配置端点'
            else:
                detail='MCP 协议握手或工具发现失败：'+raw
            with db(): db().execute("UPDATE mcp_servers SET connection_status='error',last_error=?,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",(detail[:500],server_id))
            return jsonify(error=detail),503
        with db():
            db().execute('DELETE FROM mcp_discovered_tools WHERE server_id=?',(server_id,))
            for tool in tools:
                db().execute(
                    'INSERT INTO mcp_discovered_tools(server_id,tool_name,description,input_schema_json) VALUES (?,?,?,?)',
                    (server_id,tool['name'],str(tool.get('description',''))[:2000],json.dumps(tool['input_schema'],ensure_ascii=False)))
            db().execute(
                "UPDATE mcp_servers SET connection_status='connected',last_error=NULL,last_connected_at=strftime('%Y-%m-%d %H:%M:%S','now'),updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",
                (server_id,))
        return jsonify(status='connected',tools=tools)

    @app.post('/api/mcp/servers/<int:server_id>/disconnect')
    @bearer_required
    def mcp_server_disconnect(server_id):
        teacher_required()
        if not db().execute('SELECT 1 FROM mcp_servers WHERE id=? AND class_id=?',(server_id,g.user['class_id'])).fetchone(): abort(404)
        with db():
            db().execute('DELETE FROM mcp_discovered_tools WHERE server_id=?',(server_id,))
            db().execute("UPDATE mcp_servers SET connection_status='disconnected',last_error=NULL,updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?",(server_id,))
        return jsonify(status='disconnected')

    @app.get('/api/mcp/servers/<int:server_id>/tools')
    @bearer_required
    def mcp_server_tools(server_id):
        if not db().execute('SELECT 1 FROM mcp_servers WHERE id=? AND class_id=?',(server_id,g.user['class_id'])).fetchone(): abort(404)
        teacher_required()
        rows=db().execute('SELECT tool_name,description,input_schema_json,discovered_at FROM mcp_discovered_tools WHERE server_id=? ORDER BY tool_name',(server_id,)).fetchall()
        return jsonify(tools=[dict(row)|{'input_schema':json.loads(row['input_schema_json'])} for row in rows])

    @app.get('/api/mcp/calls')
    @bearer_required
    def mcp_calls_get():
        condition='class_id=?'; params=[g.user['class_id']]
        if g.user['role']!='teacher': condition+=' AND user_id=?'; params.append(g.user['id'])
        rows=db().execute(f'SELECT * FROM mcp_call_logs WHERE {condition} ORDER BY id DESC LIMIT 200',params).fetchall()
        return jsonify(calls=[dict(row) for row in rows])

    @app.get('/api/assistant/traces/<int:conversation_id>')
    @bearer_required
    def assistant_traces_get(conversation_id):
        condition='class_id=? AND conversation_id=?'; params=[g.user['class_id'],conversation_id]
        if g.user['role']!='teacher': condition+=' AND user_id=?'; params.append(g.user['id'])
        llm=[dict(row) for row in db().execute(f'SELECT * FROM llm_call_logs WHERE {condition} ORDER BY call_round,id',params)]
        mcp_logs=[dict(row) for row in db().execute(f'SELECT * FROM mcp_call_logs WHERE {condition} ORDER BY call_round,id',params)]
        routes=[dict(row) for row in db().execute(f'SELECT * FROM skill_route_logs WHERE {condition} ORDER BY id',params)]
        if not llm and not mcp_logs and not routes:
            conversation=db().execute('SELECT 1 FROM assistant_conversations WHERE id=? AND class_id=? AND (?="teacher" OR user_id=?)',(conversation_id,g.user['class_id'],g.user['role'],g.user['id'])).fetchone()
            if not conversation: abort(404)
        return jsonify(llm_calls=llm,mcp_calls=mcp_logs,skill_routes=routes)

    @app.post('/api/assistant/ask')
    @bearer_required
    def assistant_ask():
        payload=request.get_json(silent=True) or {}
        question=str(payload.get('question','')).strip()
        if not question: abort(400,description='问题不能为空')
        conversation_id=create_or_get_conversation(payload.get('conversation_id'))
        assistant_app=get_assistant_app(payload.get('app_id'))
        routed=route_skill(db(),assistant_app['id'],question)
        selected=routed['selected']
        with db():
            db().execute(
                '''INSERT INTO skill_route_logs(user_id,class_id,conversation_id,app_id,candidates_json,
                   selected_skill_id,reason,injected_sha256) VALUES (?,?,?,?,?,?,?,?)''',
                (g.user['id'],g.user['class_id'],conversation_id,assistant_app['id'],
                 json.dumps(routed['candidates'],ensure_ascii=False),selected['id'] if selected else None,
                 routed['reason'],instruction_hash(selected['content'] if selected else None)))
        total_chunks=db().execute("SELECT COUNT(*) FROM knowledge_chunks WHERE class_id=? AND index_status='ready'",(g.user['class_id'],)).fetchone()[0]
        if assistant_app['retrieval_enabled']:
            try:
                client=None if assistant_app['retrieval_mode']=='keyword' else embedding_client()
                hits,meta=search_knowledge(db(),g.user['class_id'],question,assistant_app['retrieval_mode'],client,limit=assistant_app['top_k'])
            except AIClientError:
                hits=[]; meta={'mode':assistant_app['retrieval_mode'],'degraded':True,'degrade_reason':'embedding unavailable'}
        else:
            hits=[]; meta={'mode':'disabled','degraded':False,'degrade_reason':None}
        meta.update({'total_chunks':total_chunks,'hit_chunk_ids':[hit['chunk_id'] for hit in hits],
                     'top_k':assistant_app['top_k'],'app_id':assistant_app['id'],'app_key':assistant_app['app_key']})
        citations=citation_payload(hits[:assistant_app['top_k']])
        system_prompt=render_app_prompt(assistant_app,selected)
        declarations,mapping=available_tools(db(),g.user['class_id'],selected['id'] if selected else None)

        def generate():
            yield sse('meta',{'conversation_id':conversation_id,'class_id':g.user['class_id'],'class_name':g.user['class_name'],'retrieval':meta})
            with db():
                db().execute('INSERT INTO assistant_messages(conversation_id,role,content) VALUES (?,?,?)',(conversation_id,'user',question))
            if assistant_app['retrieval_enabled'] and not citations:
                answer='资料中未找到相关内容'
                with db():
                    db().execute('INSERT INTO assistant_messages(conversation_id,role,content) VALUES (?,?,?)',(conversation_id,'assistant',answer))
                yield sse('delta',{'text':answer})
                yield sse('citations',{'citations':[]})
                yield sse('done',{'conversation_id':conversation_id})
                return
            try:
                chat=chat_client()
                model=assistant_app['model_override'] or getattr(chat,'model',None) or app.config.get('CHAT_MODEL') or 'test-chat-model'
                context={'user_id':g.user['id'],'class_id':g.user['class_id'],'conversation_id':conversation_id,'app_id':assistant_app['id']}
                answer,tool_events=run_tool_loop(
                    db(),chat,mcp_client(),context,evidence_messages(question,citations,system_prompt),
                    declarations,mapping,model,float(assistant_app['temperature']),int(assistant_app['max_tokens']),
                    app.config['MCP_MAX_TOOL_ROUNDS'],app.config['MCP_MAX_TOTAL_CALLS'])
                if not any(f'[{idx}]' in answer for idx in range(1,len(citations)+1)):
                    if citations: answer += ' [1]'
                with db():
                    db().execute('INSERT INTO assistant_messages(conversation_id,role,content) VALUES (?,?,?)',(conversation_id,'assistant',answer))
                for event in tool_events:
                    yield sse('tool_call',event)
                for offset in range(0,len(answer),24):
                    yield sse('delta',{'text':answer[offset:offset+24]})
                    time.sleep(0.001)
                yield sse('citations',{'citations':citations})
                yield sse('done',{'conversation_id':conversation_id})
            except Exception as exc:
                app.logger.warning('Assistant chat failed: %s',safe_error(exc))
                yield sse('error',{'message':'AI 回答暂不可用'})
        return Response(stream_with_context(generate()),mimetype='text/event-stream')

    @app.get('/health')
    def health():
        try:
            db().execute('SELECT id FROM classes LIMIT 1').fetchone()
        except sqlite3.Error:
            return jsonify(status='error',database='unavailable'),503
        return jsonify(status='ok',database='ok')

    return app
