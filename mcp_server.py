"""CampusClaw read-only MCP server using the official Python SDK."""
from __future__ import annotations

import ast
import hmac
import math
import os
import time

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse


class EnvironmentTokenVerifier:
    async def verify_token(self, token: str):
        expected = os.environ.get('MCP_SERVICE_TOKEN', '')
        if not expected or not hmac.compare_digest(token, expected):
            return None
        return AccessToken(token='<redacted>', client_id='campusclaw-host', scopes=['tools:read'], expires_at=int(time.time()) + 3600)


base_url = os.environ.get('MCP_PUBLIC_URL', 'http://127.0.0.1:8090')
mcp = FastMCP(
    'CampusClaw Course Tools', host='0.0.0.0', port=int(os.environ.get('MCP_PORT', '8090')),
    streamable_http_path='/mcp', stateless_http=True, json_response=True,
    token_verifier=EnvironmentTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(base_url), resource_server_url=AnyHttpUrl(base_url), required_scopes=['tools:read']
    ),
)

GLOSSARY = {
    'sdd': 'Software Design Document：在实现前明确目标、边界、设计决策与验收场景。',
    'mcp': 'Model Context Protocol：让宿主以标准方式发现并调用外部上下文与工具的协议。',
    'rag': 'Retrieval-Augmented Generation：先检索证据，再把选中证据提供给生成模型。',
    'rbac': 'Role-Based Access Control：依据服务端可信角色执行授权。',
}


@mcp.tool(description='查询 CampusClaw 课程术语解释；只读、无副作用。')
def lookup_course_glossary(term: str) -> str:
    """Look up a course glossary term."""
    key = (term or '').strip().casefold()
    if not key or len(key) > 80:
        raise ValueError('term 必须是 1-80 个字符')
    return GLOSSARY.get(key, f'课程术语表中未找到“{term.strip()}”。')


ALLOWED_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                  ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                  ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b}
ALLOWED_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def _evaluate(node):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY:
        return ALLOWED_BINARY[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY:
        return ALLOWED_UNARY[type(node.op)](_evaluate(node.operand))
    raise ValueError('只支持数字、括号和 + - * / ** %')


@mcp.tool(description='检查简单数学表达式并给出计算提示；只读、无副作用。')
def formula_hint(expression: str) -> str:
    """Return a safe hint for a simple arithmetic expression."""
    expression = (expression or '').strip()
    if not expression or len(expression) > 120:
        raise ValueError('expression 必须是 1-120 个字符')
    tree = ast.parse(expression, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 40:
        raise ValueError('表达式过于复杂')
    value = _evaluate(tree)
    if not math.isfinite(value) or abs(value) > 1e100:
        raise ValueError('计算结果超出安全范围')
    return f'先按括号、乘方、乘除、加减的顺序化简。该表达式的校验结果为 {value:g}。'


@mcp.custom_route('/health', methods=['GET'])
async def health(_request: Request):
    return JSONResponse({'status': 'ok', 'service': 'campusclaw-mcp'})


if __name__ == '__main__':
    if not os.environ.get('MCP_SERVICE_TOKEN'):
        raise RuntimeError('MCP_SERVICE_TOKEN must be supplied through the environment')
    mcp.run(transport='streamable-http')
