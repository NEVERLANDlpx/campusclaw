"""Official MCP SDK client wrapper used by the Flask host."""
from __future__ import annotations

import asyncio
import ipaddress
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MCPClientError(RuntimeError):
    pass


DEFAULT_ALLOWED_HOSTS = 'mcp-tools,localhost,localhost.localdomain,127.0.0.1,::1'


def validate_mcp_endpoint(endpoint: str, allowed_hosts: str | list[str] | tuple[str, ...] | set[str]) -> str:
    """Validate a configured endpoint without resolving or contacting it."""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('MCP 端点必须是完整的 HTTP(S) URL')
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('MCP 端点不得包含用户信息或 URL fragment')
    if isinstance(allowed_hosts, str):
        allowed = {item.strip().casefold() for item in allowed_hosts.split(',') if item.strip()}
    else:
        allowed = {str(item).strip().casefold() for item in allowed_hosts if str(item).strip()}
    hostname = parsed.hostname.casefold()
    if hostname not in allowed:
        raise ValueError(f'MCP 端点主机不在部署允许列表中：{hostname}')
    return endpoint


def _is_loopback_endpoint(endpoint: str) -> bool:
    """Bypass environment proxies only for explicit local loopback endpoints."""
    hostname = (urlparse(endpoint).hostname or '').casefold()
    if hostname in {'localhost', 'localhost.localdomain'}:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _http_client(endpoint: str, token: str, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={'Authorization': f'Bearer {token}'},
        timeout=timeout,
        # A developer machine proxy must not intercept 127.0.0.0/8 or ::1.
        # Remote MCP endpoints retain normal HTTP(S)_PROXY behavior.
        trust_env=not _is_loopback_endpoint(endpoint),
    )


def _plain_tool(tool) -> dict[str, Any]:
    return {
        'name': tool.name,
        'description': tool.description or '',
        'input_schema': tool.inputSchema,
    }


def _exception_text(exc: BaseException) -> str:
    """Flatten async ExceptionGroup/cause chains into a useful, redacted-safe message."""
    messages = []
    visited = set()

    def collect(item):
        if id(item) in visited:
            return
        visited.add(id(item))
        message = str(item).strip()
        if message and message not in messages:
            messages.append(message)
        for child in getattr(item, 'exceptions', ()) or ():
            collect(child)
        cause = getattr(item, '__cause__', None) or getattr(item, '__context__', None)
        if cause is not None:
            collect(cause)

    collect(exc)
    return ' | '.join(messages)[:2000] or exc.__class__.__name__


async def _discover(endpoint: str, token: str, timeout: float) -> list[dict[str, Any]]:
    async with _http_client(endpoint, token, timeout) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                tools = []
                cursor = None
                while True:
                    result = await session.list_tools(cursor=cursor)
                    tools.extend(_plain_tool(tool) for tool in result.tools)
                    cursor = result.nextCursor
                    if not cursor:
                        return tools


async def _call(endpoint: str, token: str, tool_name: str, arguments: dict[str, Any], timeout: float):
    async with _http_client(endpoint, token, timeout) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments, read_timeout_seconds=timedelta(seconds=timeout))
                content = []
                for item in result.content:
                    if hasattr(item, 'model_dump'):
                        content.append(item.model_dump(mode='json'))
                    else:
                        content.append({'type': 'text', 'text': str(item)})
                return {'content': content, 'isError': bool(result.isError)}


class MCPClient:
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    def discover(self, endpoint: str, token: str) -> list[dict[str, Any]]:
        try:
            return asyncio.run(_discover(endpoint, token, self.timeout))
        except Exception as exc:
            raise MCPClientError(_exception_text(exc)[:500]) from exc

    def call(self, endpoint: str, token: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return asyncio.run(_call(endpoint, token, tool_name, arguments, self.timeout))
        except Exception as exc:
            raise MCPClientError(_exception_text(exc)[:500]) from exc

