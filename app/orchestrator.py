"""Bounded LLM/MCP orchestration with request, response and tool-call auditing."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from jsonschema import ValidationError, validate

from .assistant_core import dump_log_json, parse_tool_ref, stable_function_name
from .mcp_client import MCPClient, MCPClientError

INJECTION_PATTERNS = (
    re.compile(r'(?i)ignore (all|any|the) previous instructions'),
    re.compile(r'忽略(?:以上|之前|所有).{0,12}(?:指令|提示词)'),
    re.compile(r'(?i)system prompt'),
)
FILTERED_TOOL_RESULT = '工具返回内容触发安全规则，原始内容已被隔离，无法作为回答依据。'


def evidence_messages(question: str, citations: list[dict[str, Any]], system_prompt: str):
    evidence = []
    for idx, hit in enumerate(citations, start=1):
        evidence.append(
            f'[{idx}] material_title={hit["material_title"]}; material_id={hit["material_id"]}; '
            f'chunk_id={hit["chunk_id"]}; chunk_index={hit["chunk_index"]}; '
            f'offsets={hit["start_offset"]}-{hit["end_offset"]}\n{hit["excerpt"]}'
        )
    user = question
    if evidence:
        user = 'Knowledge evidence (untrusted quoted course text):\n\n' + '\n\n'.join(evidence) + '\n\nQuestion:\n' + question
    return [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user}]


def available_tools(conn, class_id: int, skill_id: int | None):
    if not skill_id:
        return [], {}
    rows = conn.execute(
        '''SELECT ast.tool_ref,s.id AS server_id,s.name AS server_name,s.endpoint_url,s.token_env_key,
                  dt.tool_name,dt.description,dt.input_schema_json
           FROM assistant_skill_tools ast
           JOIN mcp_servers s ON s.class_id=? AND s.connection_status='connected'
           JOIN mcp_discovered_tools dt ON dt.server_id=s.id
           WHERE ast.skill_id=? AND ast.tool_ref=(dt.tool_name || '@' || s.name)
           ORDER BY ast.tool_ref''',
        (class_id, skill_id),
    ).fetchall()
    declarations, mapping = [], {}
    for row in rows:
        schema = json.loads(row['input_schema_json'])
        fn_name = stable_function_name(row['tool_name'], row['server_name'])
        declarations.append({'type': 'function', 'function': {
            'name': fn_name, 'description': row['description'], 'parameters': schema,
        }})
        mapping[fn_name] = dict(row) | {'schema': schema}
    return declarations, mapping


def _assistant_message(response: dict[str, Any]):
    try:
        message = response['choices'][0]['message']
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError('模型响应缺少 assistant message') from exc
    return message


def _call_model(conn, chat_client, payload, context, call_round):
    request_json, request_truncated = dump_log_json(payload)
    with conn:
        log_id = conn.execute(
            '''INSERT INTO llm_call_logs(user_id,class_id,conversation_id,app_id,call_round,
               request_json,model_name,status,request_truncated) VALUES (?,?,?,?,?,?,?,'pending',?)''',
            (context['user_id'], context['class_id'], context['conversation_id'], context['app_id'],
             call_round, request_json, payload.get('model'), request_truncated),
        ).lastrowid
    started = time.monotonic()
    try:
        if hasattr(chat_client, 'complete_traceable'):
            response = chat_client.complete_traceable(payload)
        else:
            text = chat_client.complete(payload['messages'])
            response = {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}]}
        response_json, response_truncated = dump_log_json(response)
        with conn:
            conn.execute(
                '''UPDATE llm_call_logs SET response_json=?,status='success',duration_ms=?,
                   response_truncated=?,completed_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?''',
                (response_json, int((time.monotonic() - started) * 1000), response_truncated, log_id),
            )
        return response
    except Exception as exc:
        error_json, response_truncated = dump_log_json({'error': str(exc)[:500]})
        with conn:
            conn.execute(
                '''UPDATE llm_call_logs SET response_json=?,status='error',duration_ms=?,
                   response_truncated=?,completed_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?''',
                (error_json, int((time.monotonic() - started) * 1000), response_truncated, log_id),
            )
        raise


def _tool_text(result: dict[str, Any]) -> str:
    parts = []
    for item in result.get('content') or []:
        if item.get('type') == 'text':
            parts.append(str(item.get('text', '')))
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    return '\n'.join(parts)[:20_000]


def run_tool_loop(conn, chat_client, mcp_client: MCPClient | None, context: dict[str, Any],
                  messages: list[dict[str, Any]], declarations: list[dict[str, Any]], mapping: dict[str, Any],
                  model: str, temperature: float, max_tokens: int,
                  max_rounds: int = 3, max_calls: int = 5):
    mcp_client = mcp_client or MCPClient()
    tool_events = []
    total_calls = 0
    round_no = 1
    while True:
        payload = {'model': model, 'messages': messages, 'temperature': temperature,
                   'max_tokens': max_tokens, 'stream': False}
        if declarations and round_no <= max_rounds and total_calls < max_calls:
            payload['tools'] = declarations
            payload['tool_choice'] = 'auto'
        response = _call_model(conn, chat_client, payload, context, round_no)
        message = _assistant_message(response)
        tool_calls = message.get('tool_calls') or []
        if not tool_calls:
            return str(message.get('content') or ''), tool_events
        if 'tools' not in payload:
            return (str(message.get('content') or '') or
                    '已达到工具调用上限；请根据现有工具结果给出可验证的降级回答。'), tool_events
        messages.append({'role': 'assistant', 'content': message.get('content'), 'tool_calls': tool_calls})
        for call in tool_calls:
            total_calls += 1
            call_id = str(call.get('id') or f'call-{round_no}-{total_calls}')
            function = call.get('function') or {}
            fn_name = function.get('name', '')
            info = mapping.get(fn_name)
            status, filtered, server_id = 'rejected', 0, None
            tool_ref = info['tool_ref'] if info else f'{fn_name}@unknown'
            tool_name = info['tool_name'] if info else fn_name
            try:
                arguments = json.loads(function.get('arguments') or '{}')
                if not isinstance(arguments, dict):
                    raise ValueError('工具参数必须是 JSON object')
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = {}
                result_text = f'工具调用被拒绝：{exc}'
            else:
                if total_calls > max_calls or round_no > max_rounds:
                    result_text = '工具调用被拒绝：已达到本次请求的工具调用上限。'
                elif info is None:
                    result_text = '工具调用被拒绝：函数不在当前 Skill 的授权候选集中。'
                else:
                    server_id = info['server_id']
                    try:
                        validate(arguments, info['schema'])
                        current = conn.execute(
                            '''SELECT s.endpoint_url,s.token_env_key FROM mcp_servers s
                               JOIN mcp_discovered_tools t ON t.server_id=s.id
                               WHERE s.id=? AND s.class_id=? AND s.connection_status='connected' AND t.tool_name=?''',
                            (server_id, context['class_id'], tool_name),
                        ).fetchone()
                        if not current:
                            raise PermissionError('服务器或工具当前不可用')
                        token = os.environ.get(current['token_env_key'], '')
                        if not token:
                            raise PermissionError('服务器令牌环境变量未配置')
                        started = time.monotonic()
                        result = mcp_client.call(current['endpoint_url'], token, tool_name, arguments)
                        duration_ms = int((time.monotonic() - started) * 1000)
                        status = 'error' if result.get('isError') else 'success'
                        result_text = _tool_text(result)
                        if any(pattern.search(result_text) for pattern in INJECTION_PATTERNS):
                            result_text, filtered = FILTERED_TOOL_RESULT, 1
                    except ValidationError as exc:
                        duration_ms = 0
                        result_text = f'工具调用被拒绝：参数不符合发现的 Schema（{exc.message}）。'
                    except PermissionError as exc:
                        duration_ms = 0
                        result_text = f'工具调用被拒绝：{exc}。'
                    except MCPClientError as exc:
                        duration_ms = int((time.monotonic() - started) * 1000) if 'started' in locals() else 0
                        status = 'error'
                        result_text = f'工具执行失败：{str(exc)[:300]}'
            duration_ms = locals().get('duration_ms', 0)
            args_json, _ = dump_log_json(arguments)
            with conn:
                conn.execute(
                    '''INSERT INTO mcp_call_logs(user_id,class_id,conversation_id,app_id,server_id,
                       tool_name,tool_ref,arguments_json,status,result_summary,call_round,duration_ms,filtered)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (context['user_id'], context['class_id'], context['conversation_id'], context['app_id'],
                     server_id, tool_name, tool_ref, args_json, status, result_text[:1000], round_no, duration_ms, filtered),
                )
            tool_events.append({'tool_ref': tool_ref, 'arguments': arguments, 'status': status, 'result_summary': result_text[:300]})
            messages.append({'role': 'tool', 'tool_call_id': call_id, 'name': fn_name,
                             'content': f'[MCP tool result from {tool_ref}; untrusted data]\n{result_text}'})
        round_no += 1
        if round_no > max_rounds or total_calls >= max_calls:
            declarations = []

