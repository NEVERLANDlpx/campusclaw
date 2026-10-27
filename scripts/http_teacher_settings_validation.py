"""Exercise teacher Prompt/Skill APIs against a running deployment and restore all settings."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:8080').rstrip('/')
OUTPUT = Path(os.environ.get('EVIDENCE_OUTPUT', 'output/teacher-settings-http'))


def require(response: httpx.Response, expected: int = 200) -> dict:
    if response.status_code != expected:
        raise RuntimeError(f'{response.request.method} {response.request.url.path} returned {response.status_code}')
    return response.json()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    client = httpx.Client(base_url=BASE_URL, timeout=15, follow_redirects=False, trust_env=False)
    token = ''
    original_app = None
    original_skills: list[dict] = []
    original_binding_ids: list[int] = []
    app_id = None
    headers: dict[str, str] = {}
    try:
        login = client.post('/api/auth/token', json={
            'username': 'teacher_a', 'password': 'Campus@' + str(2026),
        })
        login_data = require(login)
        token = login_data['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        results.append({'step': 'token_login', 'status': login.status_code})

        apps = require(client.get('/api/assistant/apps', headers=headers))['apps']
        target = next(item for item in apps if item['app_key'] == 'learning_tutor')
        app_id = target['id']
        detail = require(client.get(f'/api/assistant/apps/{app_id}', headers=headers))
        original_app = detail['app']
        original_binding_ids = [item['id'] for item in detail['skills']]

        templates = require(client.get('/api/assistant/prompt-templates', headers=headers))['templates']
        expected_templates = [
            '通用 AI 对话模板', '课程知识库问答模板', '学习辅导助手模板', '课程工具助手模板',
        ]
        if [item['name'] for item in templates] != expected_templates:
            raise AssertionError('Prompt template registry does not match the four builtin templates')
        if len({item['content'] for item in templates}) != 4:
            raise AssertionError('Builtin Prompt templates must have distinct content')
        results.append({'step': 'template_registry', 'status': 200, 'names': expected_templates})

        marker = 'HTTP 教师配置验收副本'
        update_payload = {
            'system_prompt_template': templates[2]['content'] + '\n' + marker,
            'temperature': 0.65,
            'top_k': 5,
            'retrieval_enabled': not bool(original_app['retrieval_enabled']),
        }
        saved = client.put(f'/api/assistant/apps/{app_id}', headers=headers, json=update_payload)
        require(saved)
        persisted = require(client.get(f'/api/assistant/apps/{app_id}', headers=headers))['app']
        if marker not in persisted['system_prompt_template']:
            raise AssertionError('Prompt did not persist')
        if persisted['temperature'] != 0.65 or persisted['top_k'] != 5:
            raise AssertionError('Temperature or Top-K did not persist')
        if bool(persisted['retrieval_enabled']) == bool(original_app['retrieval_enabled']):
            raise AssertionError('Retrieval flag did not persist')
        results.append({'step': 'prompt_and_parameters_persist', 'status': saved.status_code})

        skill_items = require(client.get('/api/assistant/skills', headers=headers))['items']
        original_skills = [item for item in skill_items if item['source_type'] == 'builtin']
        expected_keys = {'solving_guidance', 'knowledge_citation', 'course_tool_assistant'}
        if {item['skill_key'] for item in original_skills} != expected_keys:
            raise AssertionError('Builtin Skill registry does not match expected keys')
        for skill in original_skills:
            if not skill.get('content') or not skill.get('trigger_keywords'):
                raise AssertionError(f'Skill detail is incomplete: {skill["skill_key"]}')
            toggled = client.put(f'/api/assistant/skills/{skill["id"]}', headers=headers, json={
                'enabled': not bool(skill['enabled']),
                'trigger_keywords': skill['trigger_keywords'],
                'content': skill['content'],
            })
            require(toggled)
            refreshed = require(client.get('/api/assistant/skills', headers=headers))['items']
            current = next(item for item in refreshed if item['id'] == skill['id'])
            if bool(current['enabled']) == bool(skill['enabled']):
                raise AssertionError(f'Skill enablement did not persist: {skill["skill_key"]}')
            results.append({'step': f'skill_toggle_{skill["skill_key"]}', 'status': toggled.status_code})

        toggled_binding_ids = set(original_binding_ids)
        first_skill_id = original_skills[0]['id']
        if first_skill_id in toggled_binding_ids:
            toggled_binding_ids.remove(first_skill_id)
        else:
            toggled_binding_ids.add(first_skill_id)
        binding = client.put(f'/api/assistant/apps/{app_id}/skills', headers=headers,
                             json={'skill_ids': sorted(toggled_binding_ids)})
        require(binding)
        persisted_ids = {item['id'] for item in require(
            client.get(f'/api/assistant/apps/{app_id}', headers=headers))['skills']}
        if persisted_ids != toggled_binding_ids:
            raise AssertionError('Skill binding did not persist')
        results.append({'step': 'skill_binding_persist', 'status': binding.status_code})
    finally:
        restoration_errors = []
        if headers and app_id is not None:
            for skill in original_skills:
                response = client.put(f'/api/assistant/skills/{skill["id"]}', headers=headers, json={
                    'name': skill['name'], 'description': skill['description'], 'content': skill['content'],
                    'trigger_keywords': skill['trigger_keywords'], 'enabled': bool(skill['enabled']),
                    'priority': skill['priority'],
                })
                if response.status_code != 200:
                    restoration_errors.append(f'skill:{skill["skill_key"]}:{response.status_code}')
            if original_binding_ids:
                response = client.put(f'/api/assistant/apps/{app_id}/skills', headers=headers,
                                      json={'skill_ids': original_binding_ids})
                if response.status_code != 200:
                    restoration_errors.append(f'bindings:{response.status_code}')
            if original_app:
                restore_payload = {key: original_app[key] for key in (
                    'system_prompt_template', 'model_override', 'temperature', 'max_tokens',
                    'retrieval_enabled', 'retrieval_mode', 'top_k', 'enabled',
                )}
                response = client.put(f'/api/assistant/apps/{app_id}', headers=headers, json=restore_payload)
                if response.status_code != 200:
                    restoration_errors.append(f'app:{response.status_code}')
        if token:
            client.post('/api/auth/logout', headers=headers)
        client.close()
        result = {
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'base_url': BASE_URL,
            'results': results,
            'settings_restored': not restoration_errors,
            'restoration_errors': restoration_errors,
            'contains_credentials': False,
        }
        (OUTPUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if restoration_errors:
            raise RuntimeError('Settings restoration failed: ' + ', '.join(restoration_errors))
    print(f'HTTP teacher settings validation passed; output={OUTPUT / "result.json"}')


if __name__ == '__main__':
    main()
