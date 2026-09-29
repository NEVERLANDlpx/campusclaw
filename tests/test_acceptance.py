import io,re,secrets
from pathlib import Path
import bcrypt,pytest
from itsdangerous import TimestampSigner
from app import create_app
from app.db import initialize,connect,resolve_material_file,material_relative_path

@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root=tmp_path_factory.mktemp('campusclaw')
    cfg={'TESTING':True,'SECRET_KEY':secrets.token_hex(32),'DATABASE':str(root/'app.db'),'UPLOAD_ROOT':str(root/'uploads')}
    initialize(cfg['DATABASE'],cfg['UPLOAD_ROOT'])
    return create_app(cfg)
@pytest.fixture
def client(app):return app.test_client()
def token(c):
    page=c.get('/login')
    if page.status_code==302:return c.get('/api/me').json['csrf_token']
    return re.search(rb'name="csrf_token" value="([^"]+)"',page.data)[1].decode()
def login(c,name='teacher_a',password='Campus@2026'):
    return c.post('/login',data={'username':name,'password':password,'csrf_token':token(c)})
def snapshot(app):
    with connect(app.config['DATABASE']) as db:
        counts=tuple(db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('materials','knowledge_entries','lectures'))
    return counts,sorted(str(p) for p in Path(app.config['UPLOAD_ROOT']).rglob('*') if p.is_file())
def stored_file(app,row):
    return resolve_material_file(app.config['UPLOAD_ROOT'],row['file_path'],row['class_id'])[0]
def upload(c,body=b'New class content',name='test.md',**extra):
    return c.post('/api/materials/upload',data={'csrf_token':token(c),'title':'验收材料','file':(io.BytesIO(body),name),**extra})
@pytest.mark.parametrize('name,role,cid',[('teacher_a','teacher',1),('student_a1','student',1),('student_b1','student',2)])
def test_login_roles(client,name,role,cid):
    r=login(client,name);assert r.status_code==302 and r.headers['Location']=='/materials'
    assert all(x in r.headers['Set-Cookie'] for x in ('HttpOnly','SameSite=Lax','Expires='))
    me=client.get('/api/me').json
    assert me['user']['role']==role and me['user']['class_id']==cid and 'password' not in str(me)
    with client.session_transaction() as s:assert s['role']==role and s['class_id']==cid and s['user_id']>0
@pytest.mark.parametrize('name,password',[('teacher_a','wrong'),('missing','wrong')])
def test_invalid_login(client,name,password):
    assert login(client,name,password).status_code==401
    assert client.get('/api/me').status_code==401

def test_anonymous(client):
    p=client.get('/materials');a=client.get('/api/materials')
    assert p.status_code==302 and p.headers['Location']=='/login'
    assert a.status_code==401 and 'A 班' not in a.text
    assert client.get('/health').json['status']=='ok'

def test_class_isolation(client):
    login(client,'student_a1')
    items=client.get('/api/materials?class_id=2').json['materials']
    assert items and all(x['class_id']==1 for x in items) and 'B 班' not in str(items)
    searched=client.get('/api/materials?q=B%20%E7%8F%AD&class_id=2').json['materials']
    assert searched==[]
    r=client.get('/api/materials/3');assert r.status_code==404 and 'B 班' not in r.text and 'body_text' not in r.text
    page=client.get('/materials').text
    assert 'upload-form' not in page
    assert 'id="material-search"' in page and '/api/materials' in Path('app/static/app.js').read_text(encoding='utf-8')
    assert 'delete-form' not in client.get('/materials/1').text

def test_teacher_cross_class_delete(client,app):
    login(client);before=snapshot(app)
    assert client.post('/api/materials/3/delete',data={'csrf_token':token(client)}).status_code==404
    assert snapshot(app)==before

def test_student_writes(client,app):
    login(client,'student_a1');before=snapshot(app)
    assert upload(client).status_code==403
    assert client.post('/api/materials/1/delete',data={'csrf_token':token(client)}).status_code==403
    assert snapshot(app)==before

def test_upload_read_delete(client,app):
    login(client);before=snapshot(app)
    r=upload(client,'新课程正文，学生可读。'.encode(),class_id='2');assert r.status_code==201 and r.json['class_id']==1
    mid=r.json['material_id']
    with connect(app.config['DATABASE']) as db:
        row=db.execute('SELECT m.class_id,m.file_path,k.body_text,k.class_id AS kc FROM materials m JOIN knowledge_entries k ON k.material_id=m.id WHERE m.id=?',(mid,)).fetchone()
        assert row['class_id']==row['kc']==1 and row['file_path'].startswith('1/') and not Path(row['file_path']).is_absolute()
        assert stored_file(app,row).exists() and '学生可读' in row['body_text']
    s=app.test_client();login(s,'student_a1')
    assert any(x['id']==mid for x in s.get('/api/materials').json['materials'])
    assert '学生可读' in s.get(f'/api/materials/{mid}').text
    b=app.test_client();login(b,'student_b1');assert b.get(f'/api/materials/{mid}').status_code==404
    assert client.post(f'/api/materials/{mid}/delete',data={'csrf_token':token(client)}).status_code==200
    assert snapshot(app)==before
@pytest.mark.parametrize('body,name',[(b'','empty.txt'),(b'x','evil.exe'),(b'\xff\xfe','broken.md'),(b'\x00a','binary.txt'),(b'   \n','space.md')])
def test_invalid_files(client,app,body,name):
    login(client);before=snapshot(app)
    assert upload(client,body,name).status_code==400
    assert snapshot(app)==before

def test_oversize(client,app):
    login(client);before=snapshot(app)
    assert upload(client,b'a'*(2*1024*1024+1)).status_code==413
    assert snapshot(app)==before

def test_database_rollback(client,app):
    login(client);before=snapshot(app)
    with connect(app.config['DATABASE']) as db:db.execute("CREATE TRIGGER fail_knowledge BEFORE INSERT ON knowledge_entries BEGIN SELECT RAISE(ABORT,'test failure'); END")
    try:assert upload(client).status_code==503
    finally:
        with connect(app.config['DATABASE']) as db:db.execute('DROP TRIGGER fail_knowledge')
    assert snapshot(app)==before

def test_csrf(client,app):
    login(client);before=snapshot(app)
    assert client.post('/api/materials/upload',data={'file':(io.BytesIO(b'x'),'x.md')}).status_code==403
    assert snapshot(app)==before

def test_tamper_expiration_logout(client,app,monkeypatch):
    login(client);key=app.config['SESSION_COOKIE_NAME'];cookie=client.get_cookie(key).value
    other=app.test_client();other.set_cookie(key,cookie[:-8]+'tampered');assert other.get('/api/me').status_code==401
    with client.session_transaction() as s:payload=dict(s)
    signer=app.session_interface.get_signing_serializer(app)
    with monkeypatch.context() as m:
        m.setattr(TimestampSigner,'get_timestamp',lambda self:1);expired=signer.dumps(payload)
    other.set_cookie(key,expired);assert other.get('/api/me').status_code==401
    assert client.post('/logout',data={'csrf_token':token(client)}).status_code==302
    other.set_cookie(key,cookie);assert other.get('/api/me').status_code==401

def test_authoritative_database_role(client,app):
    login(client);before=snapshot(app)
    with connect(app.config['DATABASE']) as db:db.execute("UPDATE users SET role='student' WHERE username='teacher_a'")
    try:
        assert client.get('/api/me').json['user']['role']=='student'
        assert upload(client).status_code==403
    finally:
        with connect(app.config['DATABASE']) as db:db.execute("UPDATE users SET role='teacher' WHERE username='teacher_a'")
    assert snapshot(app)==before

def test_seed_hash(app):
    before=snapshot(app);initialize(app.config['DATABASE'],app.config['UPLOAD_ROOT']);assert snapshot(app)==before
    with connect(app.config['DATABASE']) as db:
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'classes','users','lectures','assignments','assistants','skills','materials','knowledge_entries'}<=names
        for row in db.execute('SELECT password_hash FROM users'):
            assert row[0].startswith('$2') and bcrypt.checkpw(b'Campus@2026',row[0].encode())

def test_missing_secret(monkeypatch):
    monkeypatch.delenv('SECRET_KEY',raising=False)
    with pytest.raises(RuntimeError):create_app()

def test_health_failure(tmp_path):
    app=create_app({'SECRET_KEY':secrets.token_hex(32),'DATABASE':str(tmp_path/'missing'/'db')})
    assert app.test_client().get('/health').status_code==503

@pytest.mark.parametrize('method',['get','head'])
def test_download_requires_auth(client,method):
    r=getattr(client,method)('/api/materials/1/download')
    assert r.status_code==401
    assert 'attachment' not in r.headers.get('Content-Disposition','')

@pytest.mark.parametrize('name,mid',[('teacher_a',1),('student_a1',1),('student_b1',3)])
def test_download_same_class(client,app,name,mid):
    login(client,name)
    with connect(app.config['DATABASE']) as db:
        row=db.execute('SELECT class_id,file_path,original_name FROM materials WHERE id=?',(mid,)).fetchone()
    r=client.get(f'/api/materials/{mid}/download?class_id=999')
    try:
        assert r.status_code==200 and r.data==stored_file(app,row).read_bytes()
        assert r.headers['Content-Disposition'].startswith('attachment;')
        assert row['original_name'] in r.headers['Content-Disposition']
        assert r.mimetype=='application/octet-stream'
        assert r.headers['Cache-Control']=='no-store' and r.headers['X-Content-Type-Options']=='nosniff'
    finally:r.close()
    assert 'download-link' in client.get(f'/materials/{mid}').text

@pytest.mark.parametrize('name,mid',[('teacher_a',3),('student_a1',3),('student_b1',1)])
def test_download_cross_class(client,name,mid):
    login(client,name)
    r=client.get(f'/api/materials/{mid}/download?class_id={2 if mid==3 else 1}')
    assert r.status_code==404 and 'file_path' not in r.text
    assert 'attachment' not in r.headers.get('Content-Disposition','')

def test_download_missing_file(client,app):
    login(client)
    assert client.get('/api/materials/999999/download').status_code==404
    with connect(app.config['DATABASE']) as db:row=db.execute('SELECT class_id,file_path FROM materials WHERE id=1').fetchone()
    p=stored_file(app,row)
    staged=p.with_suffix('.temporarily-missing');p.rename(staged)
    try:assert client.get('/api/materials/1/download').status_code==404
    finally:staged.rename(p)

@pytest.mark.parametrize('mode',['outside','other_class','symlink','directory'])
def test_download_path_boundary(client,app,tmp_path,mode):
    login(client)
    with connect(app.config['DATABASE']) as db:
        original=db.execute('SELECT file_path FROM materials WHERE id=1').fetchone()[0]
        other=db.execute('SELECT file_path FROM materials WHERE id=3').fetchone()[0]
    outside=tmp_path/'private.txt';outside.write_text('PRIVATE CONTENT')
    link=None
    if mode=='outside':bad=outside
    elif mode=='other_class':bad=Path(other)
    elif mode=='directory':bad='1'
    else:
        link=Path(app.config['UPLOAD_ROOT'])/'1'/'escape.txt'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f'current Windows account cannot create symlinks: {exc}')
        bad='1/escape.txt'
    with connect(app.config['DATABASE']) as db:db.execute('UPDATE materials SET file_path=? WHERE id=1',(str(bad),))
    try:
        r=client.get('/api/materials/1/download')
        assert r.status_code==404 and 'PRIVATE CONTENT' not in r.text and str(bad) not in r.text
    finally:
        with connect(app.config['DATABASE']) as db:db.execute('UPDATE materials SET file_path=? WHERE id=1',(original,))
        if link:link.unlink()

def test_legacy_absolute_paths_resolve_for_download(client,app):
    upload_root=Path(app.config['UPLOAD_ROOT'])
    legacy_cases=[
        str(upload_root/'1'/'seed-sdd-guide.md'),
        '/app/uploads/1/seed-sdd-guide.md',
        '1/seed-sdd-guide.md',
    ]
    login(client)
    with connect(app.config['DATABASE']) as db:
        original=db.execute('SELECT file_path FROM materials WHERE id=1').fetchone()[0]
    for stored in legacy_cases:
        with connect(app.config['DATABASE']) as db:db.execute('UPDATE materials SET file_path=? WHERE id=1',(stored,))
        assert material_relative_path(stored,1)=='1/seed-sdd-guide.md'
        r=client.get('/api/materials/1/download')
        try:
            assert r.status_code==200 and r.data==(upload_root/'1'/'seed-sdd-guide.md').read_bytes()
        finally:
            r.close()
    with connect(app.config['DATABASE']) as db:db.execute('UPDATE materials SET file_path=? WHERE id=1',(original,))

@pytest.mark.parametrize('bad',['../1/seed-sdd-guide.md','1/../2/seed-b-class.md','2/seed-b-class.md','/tmp/seed-sdd-guide.md'])
def test_material_path_traversal_rejected(client,app,bad):
    login(client)
    with connect(app.config['DATABASE']) as db:
        original=db.execute('SELECT file_path FROM materials WHERE id=1').fetchone()[0]
        db.execute('UPDATE materials SET file_path=? WHERE id=1',(bad,))
    try:
        r=client.get('/api/materials/1/download')
        assert r.status_code==404 and 'seed-b-class' not in r.text
    finally:
        with connect(app.config['DATABASE']) as db:db.execute('UPDATE materials SET file_path=? WHERE id=1',(original,))

def test_download_original_bytes_and_revocation(client,app):
    login(client)
    original=b'\xef\xbb\xbf'+('# 原始文件\r\n保留BOM与换行\r\n'.encode())
    r=upload(client,original,'中文讲义.MD');assert r.status_code==201;mid=r.json['material_id']
    response=client.get(f'/api/materials/{mid}/download')
    try:
        assert response.data==original and "filename*=UTF-8''" in response.headers['Content-Disposition']
    finally:response.close()
    key=app.config['SESSION_COOKIE_NAME'];cookie=client.get_cookie(key).value
    client.post(f'/api/materials/{mid}/delete',data={'csrf_token':token(client)})
    assert client.get(f'/api/materials/{mid}/download').status_code==404
    client.post('/logout',data={'csrf_token':token(client)})
    replay=app.test_client();replay.set_cookie(key,cookie)
    assert replay.get('/api/materials/1/download').status_code==401

def test_upload_not_publicly_served(client):
    for path in ['/uploads/1/seed-sdd-guide.md','/static/uploads/1/seed-sdd-guide.md']:
        assert client.get(path).status_code==404
    login(client)
    assert client.get('/uploads/1/seed-sdd-guide.md').status_code==404

@pytest.mark.parametrize('name',['lesson.pdf','lesson.docx','lesson.xlsx','photo.png','data.csv','notes.json','script.exe','lesson.txt.exe'])
def test_unsupported_format(client,app,name):
    login(client);before=snapshot(app)
    assert upload(client,b'Plain text despite extension',name).status_code==400
    assert snapshot(app)==before

@pytest.mark.parametrize('name',['lesson.txt','lesson.md','lesson.TXT','lesson.MD'])
def test_supported_format(client,name):
    login(client);r=upload(client,'UTF-8 中文材料'.encode(),name);assert r.status_code==201
    mid=r.json['material_id']
    assert client.post(f'/api/materials/{mid}/delete',data={'csrf_token':token(client)}).status_code==200
