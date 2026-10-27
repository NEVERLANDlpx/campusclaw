import io
import json
import re
import secrets
from pathlib import Path

import pytest

from app import create_app
from app.db import connect, initialize
from app.knowledge import rebuild_material_index, rrf_fuse


class FakeEmbedding:
    model = 'fake-embedding'
    dim = 3

    def __init__(self):
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if 'B班唯一词' in text or 'B 班独有' in text:
            return [0.0, 1.0, 0.0]
        if '无关低分' in text:
            return [0.0, 0.0, 1.0]
        return [1.0, 0.0, 0.0]


class FakeChat:
    def __init__(self):
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        system = messages[0]['content']
        if 'solving_guidance' in system:
            return '可以先依据材料判断：没有依据时应固定说明未找到，并继续思考为什么不能编造出处 [1]'
        return '资料说明，没有依据时应返回固定文本，且不得编造出处 [1]'


def make_tmp_root(name):
    root = Path('tmp') / f'{name}-{secrets.token_hex(8)}'
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_app():
    tmp_path = make_tmp_root('ai-assistant')
    cfg = {
        'TESTING': True,
        'SECRET_KEY': secrets.token_hex(32),
        'DATABASE': str(tmp_path / 'app.db'),
        'UPLOAD_ROOT': str(tmp_path / 'uploads'),
        'EMBEDDING_CLIENT': FakeEmbedding(),
        'CHAT_CLIENT': FakeChat(),
    }
    initialize(cfg['DATABASE'], cfg['UPLOAD_ROOT'])
    app = create_app(cfg)
    with connect(cfg['DATABASE']) as db:
        for row in db.execute('SELECT id,class_id FROM materials'):
            rebuild_material_index(db, row['id'], row['class_id'], cfg['EMBEDDING_CLIENT'])
    return app


@pytest.fixture
def app():
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def token_login(client, name='student_a1'):
    response = client.post('/api/auth/token', json={'username': name, 'password': 'Campus@2026'})
    assert response.status_code == 200
    client._access_token = response.json['access_token']
    return response


def auth(client):
    return {'Authorization': f"Bearer {client._access_token}"}


def csrf(client):
    with client.session_transaction() as session:
        return session.get('csrf_token', '')


def teacher_upload(client, body, name='ai-qa-proof.md', title='ai-qa-proof.md'):
    token_login(client, 'teacher_a')
    return client.post(
        '/api/materials/upload',
        headers=auth(client),
        data={'csrf_token': csrf(client), 'title': title, 'file': (io.BytesIO(body.encode()), name)},
    )


def parse_sse(raw):
    events = []
    for block in raw.decode().strip().split('\n\n'):
        lines = block.splitlines()
        event = next((line[7:] for line in lines if line.startswith('event: ')), '')
        data = next((line[6:] for line in lines if line.startswith('data: ')), '{}')
        events.append((event, json.loads(data)))
    return events


def test_assistant_requires_bearer(client):
    assert client.post('/api/assistant/ask', json={'question': 'x'}).status_code == 401


def test_upload_creates_knowledge_index(client, app):
    response = teacher_upload(client, '# CampusClaw 知识库验收材料\n\n没有资料依据时不得编造出处。')
    assert response.status_code == 201 and response.json['index']['failed'] == 0
    with connect(app.config['DATABASE']) as db:
        mid = response.json['material_id']
        chunks = db.execute('SELECT * FROM knowledge_chunks WHERE material_id=?', (mid,)).fetchall()
        embeddings = db.execute('SELECT * FROM knowledge_chunk_embeddings WHERE chunk_id=?', (chunks[0]['id'],)).fetchall()
    assert chunks and chunks[0]['index_status'] == 'ready' and embeddings


def test_keyword_vector_hybrid_and_rrf(client, app):
    token_login(client, 'student_a1')
    keyword = client.get('/api/knowledge/search?q=HTTP 登录实验&mode=keyword&class_id=2', headers=auth(client)).json
    assert keyword['results'] and app.config['EMBEDDING_CLIENT'].calls
    calls_after_keyword = len(app.config['EMBEDDING_CLIENT'].calls)
    vector = client.get('/api/knowledge/search?q=CampusClaw 没有依据&mode=vector', headers=auth(client)).json
    hybrid = client.get('/api/knowledge/search?q=CampusClaw 没有依据&mode=hybrid', headers=auth(client)).json
    assert len(app.config['EMBEDDING_CLIENT'].calls) > calls_after_keyword
    assert vector['results'] and hybrid['results'] and hybrid['mode'] == 'hybrid'
    assert rrf_fuse([(1, 9), (2, 8)], [(2, 9), (3, 8)])[0][0] == 2


def test_cross_class_unique_content_hidden(client):
    token_login(client, 'student_a1')
    response = client.get('/api/knowledge/search?q=B班唯一词&mode=keyword&class_id=2', headers=auth(client))
    assert response.status_code == 200
    assert response.json['results'] == [] and 'B班唯一词' not in response.text


def test_no_hits_skips_chat_and_returns_fixed_text(client, app):
    token_login(client, 'student_a1')
    response = client.post('/api/assistant/ask', headers=auth(client), json={'question': '无关低分'})
    assert response.content_type.startswith('text/event-stream')
    events = parse_sse(response.data)
    assert ('delta', {'text': '资料中未找到相关内容'}) in events
    assert any(event == 'citations' and data['citations'] == [] for event, data in events)
    assert app.config['CHAT_CLIENT'].calls == []


def test_hits_call_chat_and_citations_are_real_chunks(client, app):
    teacher_upload(client, '# CampusClaw 知识库验收材料\n\n当本班资料没有依据时，助手应返回“资料中未找到相关内容”，不得编造出处。')
    student = app.test_client()
    token_login(student, 'student_a1')
    response = student.post('/api/assistant/ask', headers=auth(student), json={'question': '资料没有依据时不得编造出处应该怎么处理？', 'class_id': 2})
    events = parse_sse(response.data)
    text = ''.join(data['text'] for event, data in events if event == 'delta')
    citations = next(data['citations'] for event, data in events if event == 'citations')
    assert '[1]' in text and citations[0]['material_title'] == 'ai-qa-proof.md'
    with connect(app.config['DATABASE']) as db:
        chunk = db.execute('SELECT chunk_text FROM knowledge_chunks WHERE id=? AND class_id=1', (citations[0]['chunk_id'],)).fetchone()
    assert chunk and citations[0]['excerpt'].replace('...', '')[:20] in chunk['chunk_text']
    assert app.config['CHAT_CLIENT'].calls


def test_prompt_and_skill_teacher_only_and_affect_next_round(client, app):
    student = app.test_client()
    token_login(student, 'student_a1')
    assert student.put('/api/assistant/prompt', headers=auth(student), json={'content': 'bad'}).status_code == 403
    assert student.put('/api/assistant/skills/solving-guidance', headers=auth(student), json={'enabled': True}).status_code == 403
    teacher = app.test_client()
    token_login(teacher, 'teacher_a')
    assert teacher.put('/api/assistant/prompt', headers=auth(teacher), json={'content': '自定义教师 Prompt'}).status_code == 200
    assert teacher.put('/api/assistant/skills/solving-guidance', headers=auth(teacher), json={'enabled': True}).status_code == 200
    app.config['CHAT_CLIENT'].calls.clear()
    response = student.post('/api/assistant/ask', headers=auth(student), json={'question': 'CampusClaw 没有依据怎么处理？', 'skill_enabled': False})
    text = ''.join(data['text'] for event, data in parse_sse(response.data) if event == 'delta')
    assert '先依据材料判断' in text
    system = app.config['CHAT_CLIENT'].calls[-1][0]['content']
    assert '自定义教师 Prompt' in system and 'solving_guidance' in system


def test_sse_events_and_conversation_owner(client, app):
    token_login(client, 'student_a1')
    response = client.post('/api/assistant/ask', headers=auth(client), json={'question': 'CampusClaw 没有依据怎么处理？'})
    events = parse_sse(response.data)
    names = [event for event, _ in events]
    assert {'meta', 'delta', 'citations', 'done'} <= set(names)
    conversation_id = next(data['conversation_id'] for event, data in events if event == 'done')
    assert client.get(f'/api/assistant/conversations/{conversation_id}', headers=auth(client)).status_code == 200
    other = app.test_client()
    token_login(other, 'student_b1')
    assert other.get(f'/api/assistant/conversations/{conversation_id}', headers=auth(other)).status_code == 404


def test_external_api_errors_redact_keys(client, app):
    class BrokenEmbedding(FakeEmbedding):
        def embed(self, text):
            raise RuntimeError('Bearer SECRET-KEY-123 failed')

    app.config['EMBEDDING_CLIENT'] = BrokenEmbedding()
    token_login(client, 'student_a1')
    response = client.get('/api/knowledge/search?q=x&mode=vector', headers=auth(client))
    assert response.status_code == 503 and 'SECRET-KEY' not in response.text


def test_env_file_not_tracked():
    assert '.env' in {line.strip() for line in Path('.gitignore').read_text(encoding='utf-8').splitlines() if line.strip()}
