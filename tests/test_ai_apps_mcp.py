import io
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app import create_app
from app.assistant_core import render_template, stable_function_name
from app.db import connect, initialize
from app.knowledge import rebuild_material_index
from app.mcp_client import MCPClient, MCPClientError, _exception_text


class FakeEmbedding:
    model = 'fake-embedding'
    dim = 3
    def embed(self, text):
        return [1.0, 0.0, 0.0]


class SimpleChat:
    def __init__(self): self.calls = []
    def complete(self, messages):
        self.calls.append(messages)
        return '测试回答 [1]'


class CapturingChat:
    model = 'capture-chat-model'
    def __init__(self): self.calls = []
    def complete_traceable(self, payload):
        self.calls.append(payload)
        return {'choices':[{'index':0,'message':{'role':'assistant','content':'捕获请求完成。'},'finish_reason':'stop'}]}


class RuntimeSkillChat(SimpleChat):
    def complete(self, messages):
        self.calls.append(messages)
        system=messages[0]['content']
        if '先澄清已知条件和目标' in system:
            return '已知条件已整理；步骤一分析目标，步骤二推导，最后检查结果。 [1]'
        if '逐项区分资料事实与推断' in system:
            return '根据本次真实证据可得结论，并对应引用 [1]。'
        if '课程术语查询或公式提示' in system:
            return '术语含义已说明；公式处理先检查表达式结构，再给出计算提示。'
        return '测试回答 [1]'


class ToolChat:
    model = 'fake-tool-model'
    def __init__(self, function_name, arguments='{"term":"MCP"}'):
        self.function_name, self.arguments, self.calls = function_name, arguments, []
    def complete_traceable(self, payload):
        self.calls.append(payload)
        if len(self.calls) == 1:
            return {'id':'first','choices':[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':[{
                'id':'call-1','type':'function','function':{'name':self.function_name,'arguments':self.arguments}}]},'finish_reason':'tool_calls'}]}
        return {'id':'second','choices':[{'index':0,'message':{'role':'assistant','content':'MCP 是标准工具协议。'},'finish_reason':'stop'}]}


class AlwaysToolChat(ToolChat):
    def complete_traceable(self,payload):
        self.calls.append(payload)
        return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{
            'id':f'call-{len(self.calls)}','type':'function','function':{'name':self.function_name,'arguments':self.arguments}}]}}]}


class FakeMCP:
    def __init__(self): self.calls = []
    def discover(self, endpoint, token):
        return [{'name':'lookup_course_glossary','description':'查课程术语','input_schema':{
            'type':'object','properties':{'term':{'type':'string'}},'required':['term'],'additionalProperties':False}}]
    def call(self, endpoint, token, tool_name, arguments):
        self.calls.append((endpoint,tool_name,arguments))
        return {'content':[{'type':'text','text':'MCP：Model Context Protocol。'}],'isError':False}


def make_app(chat=None, mcp=None):
    root=Path('tmp')/f'ai-apps-mcp-{secrets.token_hex(8)}'; root.mkdir(parents=True,exist_ok=True)
    cfg={'TESTING':True,'SECRET_KEY':secrets.token_hex(32),'DATABASE':str(root/'app.db'),
         'UPLOAD_ROOT':str(root/'uploads'),'EMBEDDING_CLIENT':FakeEmbedding(),
         'CHAT_CLIENT':chat or SimpleChat(),'MCP_CLIENT':mcp or FakeMCP(),
         'MCP_ALLOWED_HOSTS':'mcp.invalid,localhost,127.0.0.1,::1'}
    initialize(cfg['DATABASE'],cfg['UPLOAD_ROOT']); initialize(cfg['DATABASE'],cfg['UPLOAD_ROOT'])
    app=create_app(cfg)
    with connect(cfg['DATABASE']) as conn:
        for row in conn.execute('SELECT id,class_id FROM materials'):
            rebuild_material_index(conn,row['id'],row['class_id'],cfg['EMBEDDING_CLIENT'])
    return app


@pytest.fixture
def app(): return make_app()


def login(client,name='teacher_a'):
    response=client.post('/api/auth/token',json={'username':name,'password':'Campus@2026'})
    assert response.status_code==200
    client.token=response.json['access_token']
    return {'Authorization':f'Bearer {client.token}'}


def parse_sse(data):
    result=[]
    for block in data.decode().strip().split('\n\n'):
        lines=block.splitlines(); event=next(x[7:] for x in lines if x.startswith('event: ')); payload=next(x[6:] for x in lines if x.startswith('data: '))
        result.append((event,json.loads(payload)))
    return result


def test_idempotent_migration_and_four_apps_per_class(app):
    initialize(app.config['DATABASE'],app.config['UPLOAD_ROOT'])
    with connect(app.config['DATABASE']) as conn:
        assert conn.execute('SELECT COUNT(*) FROM assistant_apps').fetchone()[0]==8
        assert conn.execute('SELECT COUNT(*) FROM prompt_templates').fetchone()[0]==8
        assert conn.execute('SELECT COUNT(*) FROM skills WHERE class_id IS NOT NULL').fetchone()[0]==6


def test_prompt_copy_isolation_and_variables(app):
    client=app.test_client(); headers=login(client)
    apps=client.get('/api/assistant/apps',headers=headers).json['apps']; first,second=apps[:2]
    before=client.get(f'/api/assistant/apps/{second["id"]}',headers=headers).json['app']['system_prompt_template']
    response=client.put(f'/api/assistant/apps/{first["id"]}',headers=headers,json={'system_prompt_template':'{{app_name}} / {{class_name}} / {{skill_content}}'})
    assert response.status_code==200
    assert client.get(f'/api/assistant/apps/{second["id"]}',headers=headers).json['app']['system_prompt_template']==before
    assert render_template('{{app_name}}',{'app_name':'A'})=='A'
    assert client.put(f'/api/assistant/apps/{first["id"]}',headers=headers,json={'system_prompt_template':'{{__import__}}'}).status_code==400


def test_teacher_prompt_templates_persist_and_drive_runtime(app):
    teacher=app.test_client(); headers=login(teacher)
    apps=teacher.get('/api/assistant/apps',headers=headers).json['apps']
    general=next(item for item in apps if item['app_key']=='general_chat')
    other=next(item for item in apps if item['app_key']=='knowledge_qa')
    other_before=teacher.get(f'/api/assistant/apps/{other["id"]}',headers=headers).json['app']['system_prompt_template']
    saved=teacher.put(f'/api/assistant/apps/{general["id"]}',headers=headers,json={
        'system_prompt_template':'{{app_name}} 自定义持久化 Prompt {{skill_content}}',
        'temperature':0.7,'top_k':6,'retrieval_enabled':False,
    })
    assert saved.status_code==200
    refreshed=teacher.get(f'/api/assistant/apps/{general["id"]}',headers=headers).json['app']
    assert refreshed['system_prompt_template']=='{{app_name}} 自定义持久化 Prompt {{skill_content}}'
    assert refreshed['temperature']==0.7 and refreshed['top_k']==6 and refreshed['retrieval_enabled']==0
    templates=teacher.get('/api/assistant/prompt-templates',headers=headers).json['templates']
    assert [item['name'] for item in templates]==[
        '通用 AI 对话模板','课程知识库问答模板','学习辅导助手模板','课程工具助手模板']
    template=next(item for item in templates if item['name']=='通用 AI 对话模板')
    applied=teacher.put(f'/api/assistant/apps/{general["id"]}',headers=headers,json={
        'system_prompt_template':template['content']+' 可编辑副本','temperature':0.8,
    })
    assert applied.status_code==200
    assert applied.json['app']['system_prompt_template'].endswith('可编辑副本')
    assert teacher.get(f'/api/assistant/apps/{other["id"]}',headers=headers).json['app']['system_prompt_template']==other_before
    student=app.test_client(); student_headers=login(student,'student_a1')
    app.config['CHAT_CLIENT'].calls.clear()
    response=student.post('/api/assistant/ask',headers=student_headers,json={
        'app_id':general['id'],'question':'验证最新 Prompt 配置'})
    assert response.status_code==200
    parse_sse(response.data)
    request=app.config['CHAT_CLIENT'].calls[-1]
    assert '可编辑副本' in request[0]['content']
    with connect(app.config['DATABASE']) as conn:
        logged=json.loads(conn.execute('SELECT request_json FROM llm_call_logs ORDER BY id DESC LIMIT 1').fetchone()['request_json'])
    assert logged['temperature']==0.8 and '可编辑副本' in logged['messages'][0]['content']


def test_builtin_skill_details_enablement_and_binding_persist(app):
    teacher=app.test_client(); headers=login(teacher)
    items=teacher.get('/api/assistant/skills',headers=headers).json['items']
    builtin=[item for item in items if item['source_type']=='builtin']
    assert {item['skill_key'] for item in builtin}=={'solving_guidance','knowledge_citation','course_tool_assistant'}
    assert all(item['content'] and item['description'] and item['trigger_keywords'] for item in builtin)
    apps=teacher.get('/api/assistant/apps',headers=headers).json['apps']
    learning=next(item for item in apps if item['app_key']=='learning_tutor')
    detail=teacher.get(f'/api/assistant/apps/{learning["id"]}',headers=headers).json
    original_ids=[item['id'] for item in detail['skills']]
    solving=next(item for item in builtin if item['skill_key']=='solving_guidance')
    disabled=teacher.put(f'/api/assistant/skills/{solving["id"]}',headers=headers,json={
        'enabled':False,'trigger_keywords':solving['trigger_keywords'],'content':solving['content']})
    assert disabled.status_code==200 and disabled.json['enabled'] is False
    refreshed=teacher.get('/api/assistant/skills',headers=headers).json['items']
    assert next(item for item in refreshed if item['id']==solving['id'])['enabled']==0
    assert teacher.put(f'/api/assistant/skills/{solving["id"]}',headers=headers,json={
        'enabled':True,'trigger_keywords':solving['trigger_keywords'],'content':solving['content']}).status_code==200
    without=[sid for sid in original_ids if sid!=solving['id']]
    assert teacher.put(f'/api/assistant/apps/{learning["id"]}/skills',headers=headers,json={'skill_ids':without}).status_code==200
    assert solving['id'] not in [item['id'] for item in teacher.get(f'/api/assistant/apps/{learning["id"]}',headers=headers).json['skills']]
    assert teacher.put(f'/api/assistant/apps/{learning["id"]}/skills',headers=headers,json={'skill_ids':original_ids}).status_code==200
    assert solving['id'] in [item['id'] for item in teacher.get(f'/api/assistant/apps/{learning["id"]}',headers=headers).json['skills']]


def test_three_builtin_skills_reach_runtime_requests_and_expected_answers():
    chat=RuntimeSkillChat(); app=make_app(chat=chat)
    student=app.test_client(); headers=login(student,'student_a1')
    apps={item['app_key']:item for item in student.get('/api/assistant/apps',headers=headers).json['apps']}
    cases=(
        ('learning_tutor','请按解题思路和步骤说明 CampusClaw 登录实验','solving_guidance','先澄清已知条件和目标','步骤一'),
        ('knowledge_qa','请根据资料来源和引用依据说明 CampusClaw','knowledge_citation','逐项区分资料事实与推断','对应引用'),
        ('course_tools','解释 MCP 术语定义并给出公式计算提示','course_tool_assistant','课程术语查询或公式提示','公式处理'),
    )
    for app_key,question,skill_key,instruction,answer_marker in cases:
        response=student.post('/api/assistant/ask',headers=headers,json={'app_id':apps[app_key]['id'],'question':question})
        events=parse_sse(response.data)
        answer=''.join(data['text'] for event,data in events if event=='delta')
        conversation_id=next(data['conversation_id'] for event,data in events if event=='done')
        trace=student.get(f'/api/assistant/traces/{conversation_id}',headers=headers).json
        route=trace['skill_routes'][0]
        request=json.loads(trace['llm_calls'][0]['request_json'])
        with connect(app.config['DATABASE']) as conn:
            skill=conn.execute('SELECT id,content FROM skills WHERE class_id=1 AND skill_key=?',(skill_key,)).fetchone()
        assert route['selected_skill_id']==skill['id'] and route['injected_sha256']
        assert instruction in request['messages'][0]['content'] and skill['content'] in request['messages'][0]['content']
        assert answer_marker in answer and trace['llm_calls'][0]['id']>0 and conversation_id>0


def test_skill_routing_controls_actual_llm_messages_and_uses_latest_saved_content():
    chat=CapturingChat(); app=make_app(chat=chat)
    teacher=app.test_client(); teacher_headers=login(teacher)
    student=app.test_client(); student_headers=login(student,'student_a1')
    apps=teacher.get('/api/assistant/apps',headers=teacher_headers).json['apps']
    general=next(item for item in apps if item['app_key']=='general_chat')
    skills=teacher.get('/api/assistant/skills',headers=teacher_headers).json['items']
    solving=next(item for item in skills if item['skill_key']=='solving_guidance')
    tool=next(item for item in skills if item['skill_key']=='course_tool_assistant')

    def bind(*skill_ids):
        response=teacher.put(f'/api/assistant/apps/{general["id"]}/skills',headers=teacher_headers,
                             json={'skill_ids':list(skill_ids)})
        assert response.status_code==200

    def save(skill, *, enabled=True, content=None):
        response=teacher.put(f'/api/assistant/skills/{skill["id"]}',headers=teacher_headers,json={
            'enabled':enabled,
            'trigger_keywords':skill['trigger_keywords'],
            'content':skill['content'] if content is None else content,
        })
        assert response.status_code==200

    def ask(question):
        before=len(chat.calls)
        response=student.post('/api/assistant/ask',headers=student_headers,
                              json={'app_id':general['id'],'question':question})
        assert response.status_code==200
        events=parse_sse(response.data)
        assert len(chat.calls)==before+1
        conversation_id=next(data['conversation_id'] for event,data in events if event=='done')
        trace=student.get(f'/api/assistant/traces/{conversation_id}',headers=student_headers).json
        logged=json.loads(trace['llm_calls'][0]['request_json'])
        assert logged['messages']==chat.calls[-1]['messages']
        return chat.calls[-1]['messages'][0]['content'],trace['skill_routes'][0]

    bind(solving['id'])
    system,route=ask('请给我解题思路')
    assert solving['content'] in system
    assert route['selected_skill_id']==solving['id']

    save(solving,enabled=False)
    system,route=ask('请给我解题思路')
    assert solving['content'] not in system
    assert route['selected_skill_id'] is None

    save(solving,enabled=True)
    bind()
    system,route=ask('请给我解题思路')
    assert solving['content'] not in system
    assert route['selected_skill_id'] is None

    bind(solving['id'])
    system,route=ask('请引导我解方程。先让我识别已知条件和目标，再问第一步如何操作，并逐步引导。')
    assert solving['content'] not in system
    candidate=json.loads(route['candidates_json'])[0]
    assert candidate['keywords']==solving['trigger_keywords'].split()
    assert candidate['matches']==[]

    latest='这是保存后立即生效的全新完整 Skill 指令。'
    save(solving,content=latest)
    system,route=ask('请给我一个解题思路')
    assert latest in system and solving['content'] not in system
    assert route['selected_skill_id']==solving['id']

    bind(solving['id'],tool['id'])
    system,route=ask('请解题并使用公式')
    assert tool['content'] in system and latest not in system
    assert route['selected_skill_id']==tool['id']


def test_knowledge_policy_remains_in_actual_llm_messages():
    chat=CapturingChat(); app=make_app(chat=chat)
    student=app.test_client(); headers=login(student,'student_a1')
    general=next(item for item in student.get('/api/assistant/apps',headers=headers).json['apps']
                 if item['app_key']=='general_chat')
    response=student.post('/api/assistant/ask',headers=headers,
                          json={'app_id':general['id'],'question':'普通对话，不触发 Skill'})
    assert response.status_code==200
    parse_sse(response.data)
    system=chat.calls[-1]['messages'][0]['content']
    assert '本应用未启用知识库检索，不得声称已经查阅班级资料。' in system


def test_teacher_settings_frontend_async_and_interaction_contract():
    js=Path('app/static/app.js').read_text(encoding='utf-8')
    html=Path('app/templates/materials.html').read_text(encoding='utf-8')
    assert "const button = event.currentTarget;" in js
    assert "event.currentTarget.disabled = false" not in js
    assert "templateSelect?.addEventListener('change'" in js
    assert 'data-skill-id' in js and "assistant-skill-list')?.addEventListener('click'" in js
    assert 'id="assistant-skill-detail"' in html and 'id="save-skill-settings"' in html
    assert 'data-mcp-action="connect"' in js and "mcp-server-list')?.addEventListener('click'" in js
    assert 'id="assistant-skill-tools"' in html and '/tools`' in js


def test_students_and_cross_class_cannot_mutate(app):
    teacher=app.test_client(); th=login(teacher); app_id=teacher.get('/api/assistant/apps',headers=th).json['apps'][0]['id']
    student=app.test_client(); sh=login(student,'student_a1')
    assert student.put(f'/api/assistant/apps/{app_id}',headers=sh,json={'temperature':1}).status_code==403
    assert student.get('/api/mcp/servers',headers=sh).status_code==403
    other=app.test_client(); oh=login(other,'student_b1')
    assert other.get(f'/api/assistant/apps/{app_id}',headers=oh).status_code==404
    assert other.get('/api/mcp/servers/1/tools',headers=oh).status_code==404


def test_mcp_endpoint_allowlist_blocks_unapproved_server_access(app):
    teacher=app.test_client(); headers=login(teacher)
    response=teacher.post('/api/mcp/servers',headers=headers,json={
        'name':'metadata','endpoint_url':'http://169.254.169.254/latest','token_env_key':'CAMPUSCLAW_TEST_MCP_TOKEN'})
    assert response.status_code==400
    assert '允许列表' in response.json['error']
    with connect(app.config['DATABASE']) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mcp_servers WHERE name='metadata'").fetchone()[0]==0


def test_async_mcp_error_groups_keep_diagnostic_nested_cause():
    error=ExceptionGroup('unhandled errors in a TaskGroup',[ConnectionError('All connection attempts failed')])
    text=_exception_text(error)
    assert 'TaskGroup' in text and 'All connection attempts failed' in text


def test_skill_upload_does_not_bind_or_execute(app):
    client=app.test_client(); headers=login(client)
    response=client.post('/api/assistant/skills/upload',headers=headers,data={
        'file':(io.BytesIO(b'# Demo\n```python\nraise RuntimeError()\n```'),'demo.md'),
        'trigger_keywords':'demo'})
    assert response.status_code==201
    with connect(app.config['DATABASE']) as conn:
        assert conn.execute('SELECT COUNT(*) FROM assistant_app_skills WHERE skill_id=?',(response.json['id'],)).fetchone()[0]==0
        assert 'raise RuntimeError' in conn.execute('SELECT content FROM skills WHERE id=?',(response.json['id'],)).fetchone()['content']


def prepare_tool_app(app, chat, mcp, monkeypatch, endpoint='http://mcp.invalid/mcp', token='local-test-token'):
    app.config['CHAT_CLIENT']=chat; app.config['MCP_CLIENT']=mcp
    monkeypatch.setenv('CAMPUSCLAW_TEST_MCP_TOKEN',token)
    teacher=app.test_client(); headers=login(teacher)
    server=teacher.post('/api/mcp/servers',headers=headers,json={'name':'course-tools','endpoint_url':endpoint,'token_env_key':'CAMPUSCLAW_TEST_MCP_TOKEN'})
    assert server.status_code==201
    assert teacher.post(f'/api/mcp/servers/{server.json["id"]}/connect',headers=headers).status_code==200
    apps=teacher.get('/api/assistant/apps',headers=headers).json['apps']; tool_app=next(item for item in apps if item['app_key']=='course_tools')
    skills=teacher.get('/api/assistant/skills',headers=headers).json['items']; skill=next(item for item in skills if item['skill_key']=='course_tool_assistant')
    assert teacher.put(f'/api/assistant/skills/{skill["id"]}/tools',headers=headers,json={'tool_refs':['lookup_course_glossary@course-tools']}).status_code==200
    refreshed=teacher.get('/api/assistant/skills',headers=headers).json['items']
    assert next(item for item in refreshed if item['id']==skill['id'])['tool_refs']==['lookup_course_glossary@course-tools']
    return tool_app,server


def test_mcp_discovery_tool_loop_traces_and_sse_order(monkeypatch):
    mcp=FakeMCP(); fn=stable_function_name('lookup_course_glossary','course-tools'); chat=ToolChat(fn)
    app=make_app(chat,mcp); tool_app,server=prepare_tool_app(app,chat,mcp,monkeypatch)
    student=app.test_client(); headers=login(student,'student_a1')
    response=student.post('/api/assistant/ask',headers=headers,json={'app_id':tool_app['id'],'question':'请查询 MCP 术语定义'})
    events=parse_sse(response.data); names=[name for name,_ in events]
    assert 'tool_call' in names and names.index('tool_call')<names.index('delta')
    assert mcp.calls==[('http://mcp.invalid/mcp','lookup_course_glossary',{'term':'MCP'})]
    conversation_id=next(data['conversation_id'] for name,data in events if name=='done')
    trace=student.get(f'/api/assistant/traces/{conversation_id}',headers=headers).json
    assert len(trace['llm_calls'])==2 and len(trace['mcp_calls'])==1
    assert 'local-test-token' not in json.dumps(trace,ensure_ascii=False)
    assert 'tools' in json.loads(trace['llm_calls'][0]['request_json'])
    assert json.loads(trace['llm_calls'][1]['request_json'])['messages'][-1]['role']=='tool'
    teacher=app.test_client(); th=login(teacher)
    assert teacher.post(f'/api/mcp/servers/{server.json["id"]}/disconnect',headers=th).status_code==200
    assert teacher.get(f'/api/mcp/servers/{server.json["id"]}/tools',headers=th).json['tools']==[]


def test_invalid_tool_arguments_are_rejected_before_mcp(monkeypatch):
    mcp=FakeMCP(); fn=stable_function_name('lookup_course_glossary','course-tools'); chat=ToolChat(fn,'{"unknown":1}')
    app=make_app(chat,mcp); tool_app,_=prepare_tool_app(app,chat,mcp,monkeypatch)
    student=app.test_client(); headers=login(student,'student_a1')
    response=student.post('/api/assistant/ask',headers=headers,json={'app_id':tool_app['id'],'question':'查询术语'})
    events=parse_sse(response.data)
    assert response.status_code==200 and mcp.calls==[] and any(name=='tool_call' for name,_ in events)
    with connect(app.config['DATABASE']) as conn:
        row=conn.execute('SELECT status,result_summary FROM mcp_call_logs ORDER BY id DESC LIMIT 1').fetchone()
        assert row is not None
        assert row['status']=='rejected' and 'Schema' in row['result_summary']


def test_reconnect_replaces_manifest_and_failure_preserves_old(monkeypatch):
    app=make_app(); mcp=app.config['MCP_CLIENT']; monkeypatch.setenv('CAMPUSCLAW_TEST_MCP_TOKEN','token')
    teacher=app.test_client(); headers=login(teacher)
    server=teacher.post('/api/mcp/servers',headers=headers,json={'name':'course-tools','endpoint_url':'http://mcp.invalid/mcp','token_env_key':'CAMPUSCLAW_TEST_MCP_TOKEN'}).json
    assert teacher.post(f'/api/mcp/servers/{server["id"]}/connect',headers=headers).status_code==200
    assert teacher.post(f'/api/mcp/servers/{server["id"]}/connect',headers=headers).status_code==200
    with connect(app.config['DATABASE']) as conn:
        assert conn.execute('SELECT COUNT(*) FROM mcp_discovered_tools WHERE server_id=?',(server['id'],)).fetchone()[0]==1
    class BrokenMCP:
        def discover(self,*_args): raise RuntimeError('discovery failed')
    app.config['MCP_CLIENT']=BrokenMCP()
    assert teacher.post(f'/api/mcp/servers/{server["id"]}/connect',headers=headers).status_code==503
    with connect(app.config['DATABASE']) as conn:
        assert conn.execute('SELECT COUNT(*) FROM mcp_discovered_tools WHERE server_id=?',(server['id'],)).fetchone()[0]==1
        assert conn.execute('SELECT connection_status FROM mcp_servers WHERE id=?',(server['id'],)).fetchone()[0]=='error'


def test_total_tool_call_limit_stops_execution(monkeypatch):
    mcp=FakeMCP(); fn=stable_function_name('lookup_course_glossary','course-tools'); chat=AlwaysToolChat(fn)
    app=make_app(chat,mcp); app.config['MCP_MAX_TOTAL_CALLS']=1
    tool_app,_=prepare_tool_app(app,chat,mcp,monkeypatch)
    student=app.test_client(); headers=login(student,'student_a1')
    events=parse_sse(student.post('/api/assistant/ask',headers=headers,json={'app_id':tool_app['id'],'question':'查询 MCP 术语'}).data)
    assert len(mcp.calls)==1 and sum(1 for name,_ in events if name=='tool_call')==1


@pytest.fixture(scope='module')
def real_mcp_server():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    token=secrets.token_urlsafe(24); base=f'http://127.0.0.1:{port}'
    env=os.environ.copy(); env.update(MCP_SERVICE_TOKEN=token,MCP_PORT=str(port),MCP_PUBLIC_URL=base)
    process=subprocess.Popen([sys.executable,'mcp_server.py'],cwd=Path(__file__).resolve().parents[1],env=env,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    direct_opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.time()+15
    while time.time()<deadline:
        try:
            with direct_opener.open(base+'/health',timeout=.5) as response:
                if response.status==200: break
        except Exception: time.sleep(.1)
    else:
        process.terminate(); raise RuntimeError('MCP test server did not start')
    yield base+'/mcp',token
    process.terminate()
    try: process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=3)


def test_real_official_mcp_handshake_auth_and_host_call(real_mcp_server,monkeypatch):
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.setenv(name,'http://127.0.0.1:9')
    for name in ('NO_PROXY','no_proxy'):
        monkeypatch.delenv(name,raising=False)
    endpoint,token=real_mcp_server; client=MCPClient(timeout=5)
    tools=client.discover(endpoint,token)
    assert {item['name'] for item in tools}=={'lookup_course_glossary','formula_hint'}
    assert client.call(endpoint,token,'formula_hint',{'expression':'2*(3+4)'})['isError'] is False
    with pytest.raises(MCPClientError): client.discover(endpoint,'wrong-token')
    fn=stable_function_name('lookup_course_glossary','course-tools'); chat=ToolChat(fn)
    app=make_app(chat,client); tool_app,_=prepare_tool_app(app,chat,client,monkeypatch,endpoint,token)
    student=app.test_client(); headers=login(student,'student_a1')
    events=parse_sse(student.post('/api/assistant/ask',headers=headers,json={
        'app_id':tool_app['id'],'question':'请查询 MCP 术语定义'}).data)
    tool_event=next(data for name,data in events if name=='tool_call')
    assert tool_event['status']=='success' and tool_event['tool_ref']=='lookup_course_glossary@course-tools'
