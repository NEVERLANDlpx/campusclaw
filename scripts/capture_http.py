"""Capture exact HTTP/1.1 bytes from a running local service (stdlib only)."""
import argparse
import json
import re
import socket
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode


def capture(host='127.0.0.1',port=8080,output='http-evidence'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    records=[];cookies={}
    def exchange(label,method,path,body=b'',content_type=None):
        headers=[('Host',f'{host}:{port}'),('User-Agent','CampusClaw-Evidence/1.0'),('Accept','*/*'),('Connection','close')]
        if cookies:headers.append(('Cookie','; '.join(f'{k}={v}' for k,v in cookies.items())))
        if content_type:headers.extend([('Content-Type',content_type),('Content-Length',str(len(body)))])
        request=(f'{method} {path} HTTP/1.1\r\n'+''.join(f'{k}: {v}\r\n' for k,v in headers)+'\r\n').encode()+body
        with socket.create_connection((host,port),timeout=10) as sock:
            sock.sendall(request);chunks=[]
            while True:
                chunk=sock.recv(65536)
                if not chunk:break
                chunks.append(chunk)
        response=b''.join(chunks)
        head,payload=response.split(b'\r\n\r\n',1)
        status=int(head.split(b' ')[1])
        for line in head.decode('iso-8859-1').split('\r\n')[1:]:
            if line.lower().startswith('set-cookie:'):
                parsed=SimpleCookie();parsed.load(line.split(':',1)[1].strip())
                for k,v in parsed.items():
                    if v.value:cookies[k]=v.value
                    else:cookies.pop(k,None)
        (out/f'{label}-request.http').write_bytes(request)
        (out/f'{label}-response.http').write_bytes(response)
        records.append((label,request,response,status))
        return status,payload
    status,html=exchange('00-login-page','GET','/login');assert status==200
    csrf=re.search(rb'name="csrf_token" value="([^"]+)"',html)[1].decode()
    body=urlencode({'username':'teacher_a','password':'Campus@2026','csrf_token':csrf}).encode()
    status,_=exchange('01-login-success','POST','/login',body,'application/x-www-form-urlencoded');assert status==302
    authenticated_cookie=dict(cookies)
    status,payload=exchange('02-current-user','GET','/api/me');assert status==200
    me=json.loads(payload)
    status,_=exchange('03-logout','POST','/logout',urlencode({'csrf_token':me['csrf_token']}).encode(),'application/x-www-form-urlencoded');assert status==302
    cookies.update(authenticated_cookie)
    status,_=exchange('04-replay-after-logout','GET','/api/me');assert status==401
    cookies.clear()
    _,html=exchange('05-login-before-failure','GET','/login')
    csrf=re.search(rb'name="csrf_token" value="([^"]+)"',html)[1].decode()
    status,_=exchange('06-login-failure','POST','/login',urlencode({'username':'teacher_a','password':'wrong-password','csrf_token':csrf}).encode(),'application/x-www-form-urlencoded');assert status==401
    status,_=exchange('07-health','GET','/health');assert status==200
    report=['0923-系统登录时的请求参数、响应结果以及HTTP响应完整内容',
            'CampusClaw 实际运行采集；时间：'+datetime.now(timezone.utc).isoformat(),
            f'地址：http://{host}:{port}；服务：Gunicorn 23.0.0 / Flask 3.1.2 / SQLite',
            '登录采用表单POST，成功返回302，不是200 JSON。Location指向/materials，Set-Cookie写入会话。',
            '参数：username=teacher_a；password=Campus@2026（公开演示账号）；csrf_token由GET /login产生。',
            '请求体为application/x-www-form-urlencoded；@被编码为%40。',
            '后续GET /api/me携带Cookie，返回教师A、teacher、class_id=1及班级A。',
            '全部状态行、响应头、空行和响应正文均来自socket原始响应，没有省略Set-Cookie。',
            '采集末尾已退出，旧Cookie重放401。报文保留作为证据，不是可复用的有效登录凭据。',
            '原始CRLF字节版本见同目录*.http；下面是便于阅读的UTF-8排版。\n']
    for label,request,response,status in records:
        report.extend(['='*72,label+f'  [实际HTTP {status}]','--- 完整请求 ---',request.decode('utf-8'),'--- 完整响应 ---',response.decode('utf-8'),''])
    (out/'02_登录请求与完整HTTP响应.txt').write_text('\n'.join(report),encoding='utf-8')
    (out/'capture-summary.json').write_text(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'identity':me['user'],'responses':{l:s for l,_,_,s in records},'old_cookie_revoked':True},ensure_ascii=False,indent=2))
    print('Captured',len(records),'HTTP request/response pairs. Old session revoked.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8080);p.add_argument('--output',default='http-evidence');args=p.parse_args()
    capture(args.host,args.port,args.output)
