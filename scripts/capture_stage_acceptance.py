"""Generate sanitized, reproducible stage evidence with a controlled LLM and real local MCP service."""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app import create_app
from app.assistant_core import stable_function_name
from app.db import connect, initialize
from app.knowledge import rebuild_material_index
from app.mcp_client import MCPClient

OUT=ROOT/'deliverables'/'04_个人项目阶段验收'/'验收证据'


class EvidenceEmbedding:
    model='controlled-embedding'; dim=3
    def embed(self,_text): return [1.0,0.0,0.0]


class EvidenceChat:
    model='controlled-fake-chat'
    def complete_traceable(self,payload):
        if payload['messages'][-1]['role']=='tool':
            return {'id':'controlled-after-tool','choices':[{'index':0,'message':{'role':'assistant','content':'MCP 是用于标准化工具发现与调用的协议。'},'finish_reason':'stop'}]}
        if payload.get('tools'):
            name=payload['tools'][0]['function']['name']
            return {'id':'controlled-tool-request','choices':[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':[{'id':'evidence-call-1','type':'function','function':{'name':name,'arguments':'{"term":"MCP"}'}}]},'finish_reason':'tool_calls'}]}
        return {'id':'controlled-answer','choices':[{'index':0,'message':{'role':'assistant','content':'这是基于本次实际请求消息生成的可控测试回答 [1]。'},'finish_reason':'stop'}]}


def auth(client,name):
    response=client.post('/api/auth/token',json={'username':name,'password':'Campus@2026'})
    return {'Authorization':'Bearer '+response.json['access_token']}


def sse_events(data):
    events=[]
    for block in data.decode().strip().split('\n\n'):
        lines=block.splitlines(); event=next(line[7:] for line in lines if line.startswith('event: ')); raw=next(line[6:] for line in lines if line.startswith('data: '))
        events.append({'event':event,'data':json.loads(raw)})
    return events


def write_json(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    work=ROOT/'tmp'/('stage-evidence-'+secrets.token_hex(6)); work.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    token=secrets.token_urlsafe(32); base=f'http://127.0.0.1:{port}'
    env=os.environ.copy(); env.update(MCP_SERVICE_TOKEN=token,MCP_PORT=str(port),MCP_PUBLIC_URL=base)
    process=subprocess.Popen([sys.executable,str(ROOT/'mcp_server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(150):
            try:
                with urllib.request.urlopen(base+'/health',timeout=.4) as response:
                    if response.status==200: break
            except Exception: time.sleep(.1)
        else: raise RuntimeError('local MCP service failed to start')
        os.environ['CAMPUSCLAW_EVIDENCE_MCP_TOKEN']=token
        embedding=EvidenceEmbedding(); chat=EvidenceChat(); mcp=MCPClient(timeout=5)
        cfg={'TESTING':True,'SECRET_KEY':secrets.token_hex(32),'DATABASE':str(work/'app.db'),
             'UPLOAD_ROOT':str(work/'uploads'),'EMBEDDING_CLIENT':embedding,'CHAT_CLIENT':chat,'MCP_CLIENT':mcp}
        initialize(cfg['DATABASE'],cfg['UPLOAD_ROOT']); app=create_app(cfg)
        with connect(cfg['DATABASE']) as conn:
            for row in conn.execute('SELECT id,class_id FROM materials'):
                rebuild_material_index(conn,row['id'],row['class_id'],embedding)
        teacher=app.test_client(); th=auth(teacher,'teacher_a')
        apps=teacher.get('/api/assistant/apps',headers=th).json['apps']; by_key={item['app_key']:item for item in apps}
        server=teacher.post('/api/mcp/servers',headers=th,json={'name':'course-tools','endpoint_url':base+'/mcp','token_env_key':'CAMPUSCLAW_EVIDENCE_MCP_TOKEN'}).json
        discovery=teacher.post(f'/api/mcp/servers/{server["id"]}/connect',headers=th).json
        skills=teacher.get('/api/assistant/skills',headers=th).json['items']; course=next(item for item in skills if item['skill_key']=='course_tool_assistant')
        teacher.put(f'/api/assistant/skills/{course["id"]}/tools',headers=th,json={'tool_refs':['lookup_course_glossary@course-tools']})
        student=app.test_client(); sh=auth(student,'student_a1')
        runs={}
        for label,app_key,question in (
            ('general','general_chat','HTTP 登录实验包含哪些步骤？'),
            ('knowledge','knowledge_qa','HTTP 登录实验包含哪些步骤？'),
            ('skill','learning_tutor','HTTP 登录实验应该怎么做？'),
            ('mcp','course_tools','请查询 MCP 术语定义'),
        ):
            events=sse_events(student.post('/api/assistant/ask',headers=sh,json={'app_id':by_key[app_key]['id'],'question':question}).data)
            conversation=next(item['data']['conversation_id'] for item in events if item['event']=='done')
            trace=student.get(f'/api/assistant/traces/{conversation}',headers=sh).json
            runs[label]={'app':by_key[app_key],'question':question,'events':events,'trace':trace}
        write_json('01_应用提示词对照_可控LLM.json',{'evidence_type':'controlled_fake_llm','general':runs['general'],'knowledge':runs['knowledge']})
        write_json('02_检索切片证据_可控LLM.json',{'evidence_type':'controlled_fake_llm','run':runs['knowledge']})
        write_json('03_Skill路由与注入_可控LLM.json',{'evidence_type':'controlled_fake_llm','run':runs['skill']})
        write_json('04_MCP完整调用链_真实MCP_可控LLM.json',{
            'evidence_type':'real_official_mcp_with_controlled_fake_llm',
            'discovered_tools':discovery.get('tools',[]),'run':runs['mcp'],
            'credential_note':'MCP token was used only in the server-side transport and is intentionally absent.',
        })
        print(json.dumps({'output':str(OUT),'files':4,'mcp_tools':len(discovery.get('tools',[]))},ensure_ascii=False))
    finally:
        os.environ.pop('CAMPUSCLAW_EVIDENCE_MCP_TOKEN',None)
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=3)


if __name__=='__main__': main()
