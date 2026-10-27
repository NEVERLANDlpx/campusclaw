"""Safe prompt rendering, deterministic Skill routing, and trace helpers."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ALLOWED_TEMPLATE_VARIABLES = {'app_name', 'class_name', 'knowledge_policy', 'skill_content'}
TEMPLATE_PATTERN = re.compile(r'{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}')
TOOL_REF_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{1,64}@[A-Za-z0-9_.-]{1,64}$')
SECRET_KEYS = {'authorization', 'api_key', 'apikey', 'access_token', 'token', 'secret', 'password'}
MAX_LOG_JSON = 200_000


def validate_template(content: str) -> set[str]:
    if not isinstance(content, str) or not content.strip():
        raise ValueError('提示词不能为空')
    variables = set(TEMPLATE_PATTERN.findall(content))
    unknown = variables - ALLOWED_TEMPLATE_VARIABLES
    if unknown:
        raise ValueError('模板包含不允许的变量：' + ', '.join(sorted(unknown)))
    if '{{' in TEMPLATE_PATTERN.sub('', content) or '}}' in TEMPLATE_PATTERN.sub('', content):
        raise ValueError('模板变量格式不正确')
    return variables


def render_template(content: str, values: dict[str, str]) -> str:
    validate_template(content)
    return TEMPLATE_PATTERN.sub(lambda match: str(values.get(match.group(1), '')), content)


def route_skill(conn, app_id: int, question: str) -> dict[str, Any]:
    rows = conn.execute(
        '''SELECT s.id,s.skill_key,s.name,s.description,s.content,s.trigger_keywords,
                  s.priority AS skill_priority,aks.priority AS binding_priority
           FROM assistant_app_skills aks JOIN skills s ON s.id=aks.skill_id
           WHERE aks.app_id=? AND s.enabled=1
           ORDER BY aks.priority DESC,s.priority DESC,s.id ASC''',
        (app_id,),
    ).fetchall()
    normalized = (question or '').casefold()
    candidates = []
    for row in rows:
        keywords = [part.strip() for part in re.split(r'[,，;；\s]+', row['trigger_keywords'] or '') if part.strip()]
        matches = [word for word in keywords if word.casefold() in normalized]
        candidates.append({
            'id': row['id'], 'skill_key': row['skill_key'], 'name': row['name'],
            'keywords': keywords,
            'matches': matches, 'match_count': len(matches),
            'priority': row['binding_priority'], 'skill_priority': row['skill_priority'],
            'content': row['content'],
        })
    matched = [item for item in candidates if item['match_count']]
    matched.sort(key=lambda item: (-item['match_count'], -item['priority'], -item['skill_priority'], item['id']))
    selected = matched[0] if matched else None
    public_candidates = [{k: v for k, v in item.items() if k != 'content'} for item in candidates]
    reason = (
        '连续子串命中关键词：' + '、'.join(selected['matches'])
        if selected else f'已检查 {len(candidates)} 个绑定且启用的 Skill；没有配置关键词以连续子串命中问题'
    )
    return {'candidates': public_candidates, 'selected': selected, 'reason': reason}


def instruction_hash(content: str | None) -> str | None:
    return hashlib.sha256(content.encode('utf-8')).hexdigest() if content else None


def stable_function_name(tool_name: str, server_name: str) -> str:
    raw = f'{tool_name}@{server_name}'
    stem = re.sub(r'[^A-Za-z0-9_]', '_', f'{server_name}_{tool_name}').strip('_')[:48] or 'tool'
    if stem[0].isdigit():
        stem = 't_' + stem
    return f'{stem}_{hashlib.sha256(raw.encode()).hexdigest()[:10]}'


def parse_tool_ref(tool_ref: str) -> tuple[str, str]:
    if not isinstance(tool_ref, str) or not TOOL_REF_PATTERN.fullmatch(tool_ref):
        raise ValueError('工具引用必须使用 tool_name@server_name 格式')
    tool_name, server_name = tool_ref.split('@', 1)
    return tool_name, server_name


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ('<redacted>' if key.casefold() in SECRET_KEYS else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+\-/]+=*', 'Bearer <redacted>', value)
    return value


def dump_log_json(value: Any, limit: int = MAX_LOG_JSON) -> tuple[str, int]:
    text = json.dumps(redact(value), ensure_ascii=False, separators=(',', ':'))
    if len(text.encode('utf-8')) <= limit:
        return text, 0
    encoded = text.encode('utf-8')[:limit]
    while True:
        try:
            clipped = encoded.decode('utf-8')
            break
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return json.dumps({'truncated': True, 'prefix': clipped}, ensure_ascii=False), 1

