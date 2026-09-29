"""Capture extra assignment API/upload/download evidence from a live server."""
import argparse
import hashlib
import json
import re
import secrets
import socket
from datetime import datetime,timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode


def capture(host='127.0.0.1',port=8080,output='extra-http-evidence'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    records=[];cookies={}
    def exchange(label,method,path,body=b'',content_type=None):
        headers=[('Host',f'{host}:{port}'),('User-Agent','CampusClaw-Extra-Evidence/1.0'),('Accept','*/*'),('Connection','close')]
        if cookies:headers.append(('Cookie','; '.join(f'{k}={v}' for k,v in cookies.items())))
        if content_type:headers.extend([('Content-Type',content_type),('Content-Length',str(len(body)))])
        request=(f'{method} {path} HTTP/1.1\r\n'+''.join(f'{k}: {v}\r\n' for k,v in headers)+'\r\n').encode()+body
        with socket.create_connection((host,port),timeout=10) as sock:
            sock.sendall(request);chunks=[]
            while True:
                piece=sock.recv(65536)
                if not piece:break
                chunks.append(piece)
        response=b''.join(chunks);head,payload=response.split(b'\r\n\r\n',1)
        status=int(head.split(b' ')[1])
        for line in head.decode('iso-8859-1').split('\r\n')[1:]:
            if line.lower().startswith('content-length:'):assert int(line.split(':',1)[1])==len(payload)
            if line.lower().startswith('set-cookie:'):
                jar=SimpleCookie();jar.load(line.split(':',1)[1].strip())
                for k,v in jar.items():
                    if v.value:cookies[k]=v.value
                    else:cookies.pop(k,None)
        (out/f'{label}-request.http').write_bytes(request)
        (out/f'{label}-response.http').write_bytes(response)
        records.append({'label':label,'method':method,'path':path,'status':status,'response_bytes':len(payload)})
        return status,payload,head
    def login(name,prefix):
        _,html,_=exchange(prefix+'-login-page','GET','/login')
        csrf=re.search(rb'name="csrf_token" value="([^"]+)"',html)[1].decode()
        code,_,_=exchange(prefix+'-login','POST','/login',urlencode({'username':name,'password':'Campus@2026','csrf_token':csrf}).encode(),'application/x-www-form-urlencoded');assert code==302
        _,body,_=exchange(prefix+'-identity','GET','/api/me');return json.loads(body)['csrf_token']
    def post_file(label,csrf,filename,content):
        boundary='CampusClawBoundary'+secrets.token_hex(10)
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="csrf_token"\r\n\r\n{csrf}\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+content+f'\r\n--{boundary}--\r\n'.encode()
        return exchange(label,'POST','/api/materials/upload',body,'multipart/form-data; boundary='+boundary)
    assert exchange('01-anonymous-api','GET','/api/me')[0]==401
    assert exchange('02-anonymous-download','GET','/api/materials/1/download')[0]==401
    assert exchange('03-public-health','GET','/health')[0]==200
    csrf=login('teacher_a','04-teacher')
    code,payload,_=exchange('05-teacher-list','GET','/api/materials?class_id=2');assert code==200 and all(x['class_id']==1 for x in json.loads(payload)['materials'])
    code,_,headers=exchange('06-teacher-download','GET','/api/materials/1/download');assert code==200 and b'attachment' in headers
    assert exchange('07-teacher-cross-class','GET','/api/materials/3/download?class_id=2')[0]==404
    source=b'\xef\xbb\xbf'+('# 原文件下载验收\r\n中文内容与原始字节保持一致。\r\n'.encode())
    code,payload,_=post_file('08-valid-md-upload',csrf,'download-proof.md',source);assert code==201;mid=json.loads(payload)['material_id']
    assert post_file('09-unsupported-pdf',csrf,'lesson.pdf',b'%PDF-1.4\nDemo\n')[0]==400
    assert post_file('10-unsupported-docx',csrf,'lesson.docx',b'PK\x03\x04demo')[0]==400
    assert exchange('11-address-bar-get-upload','GET','/api/materials/upload')[0]==405
    assert exchange('12-teacher-logout','POST','/logout',urlencode({'csrf_token':csrf}).encode(),'application/x-www-form-urlencoded')[0]==302
    csrf=login('student_a1','13-student')
    code,download,headers=exchange('14-student-download','GET',f'/api/materials/{mid}/download');assert code==200 and download==source
    assert b'Cache-Control: no-store' in headers and b'Content-Type: application/octet-stream' in headers
    (out/'下载得到的原文件.md').write_bytes(download)
    assert post_file('15-student-upload-denied',csrf,'student.txt',b'denied')[0]==403
    assert exchange('16-student-cross-class','GET','/api/materials/3/download')[0]==404
    prior=dict(cookies)
    assert exchange('17-student-logout','POST','/logout',urlencode({'csrf_token':csrf}).encode(),'application/x-www-form-urlencoded')[0]==302
    cookies.update(prior)
    assert exchange('18-revoked-download','GET',f'/api/materials/{mid}/download')[0]==401
    summary={'captured_at':datetime.now(timezone.utc).isoformat(),'base':f'http://{host}:{port}','records':records,'download_material_id':mid,'uploaded_sha256':hashlib.sha256(source).hexdigest(),'downloaded_sha256':hashlib.sha256(download).hexdigest(),'byte_identical':source==download,'cookies_revoked':True}
    (out/'extra-http-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    report=['新增作业真实HTTP记录','采集时间：'+summary['captured_at'],'以下响应来自实际运行服务；Cookie已在采集结束退出撤销。','上传与下载原文件SHA-256：'+summary['uploaded_sha256'],'字节完全一致：'+str(summary['byte_identical']),'']
    for row in records:
        label=row['label'];report.extend(['='*70,f"{label}: {row['method']} {row['path']} → {row['status']}",'--- Request ---',(out/f'{label}-request.http').read_bytes().decode('utf-8',errors='backslashreplace'),'--- Response ---',(out/f'{label}-response.http').read_bytes().decode('utf-8',errors='backslashreplace'),''])
    (out/'新增作业完整HTTP记录.txt').write_text('\n'.join(report),encoding='utf-8')
    print('Extra HTTP evidence:',len(records),'exchanges; downloaded bytes identical; cookies revoked.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8080);p.add_argument('--output',default='extra-http-evidence');a=p.parse_args();capture(a.host,a.port,a.output)
