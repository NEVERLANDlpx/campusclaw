"""Server-side clients for course embedding and chat gateways."""
import json
import os
import urllib.error
import urllib.request
from json import JSONDecodeError


class AIClientError(RuntimeError):
    pass


def _post_json(base_url, api_key, path, payload, stream=False):
    if not base_url or not api_key:
        raise AIClientError('AI 网关环境变量未配置')
    url = base_url.rstrip('/') + path
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream' if stream else 'application/json',
        },
        method='POST',
    )
    try:
        return urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as exc:
        raise AIClientError(f'AI 网关请求失败：HTTP {exc.code}') from exc
    except urllib.error.URLError as exc:
        raise AIClientError('AI 网关暂不可用') from exc


class EmbeddingClient:
    def __init__(self, base_url=None, api_key=None, model=None, dim=None):
        self.base_url = base_url if base_url is not None else os.environ.get('EMBEDDING_BASE_URL', '')
        self.api_key = api_key if api_key is not None else os.environ.get('EMBEDDING_API_KEY', '')
        self.model = model if model is not None else os.environ.get('EMBEDDING_MODEL', '')
        raw_dim = dim if dim is not None else os.environ.get('EMBEDDING_DIM', '')
        self.dim = int(raw_dim) if str(raw_dim).strip() else 0

    def embed(self, text):
        if not self.model or self.dim <= 0:
            raise AIClientError('embedding 模型或维度未配置')
        try:
            with _post_json(self.base_url, self.api_key, '/embeddings', {'model': self.model, 'input': text}) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except JSONDecodeError as exc:
            raise AIClientError('embedding 响应不是合法 JSON') from exc
        try:
            vector = data['data'][0]['embedding']
        except (KeyError, IndexError, TypeError) as exc:
            raise AIClientError('embedding 响应格式不正确') from exc
        if len(vector) != self.dim:
            raise AIClientError(f'EMBEDDING_DIM={self.dim} 与实际 embedding 长度 {len(vector)} 不一致')
        return [float(x) for x in vector]

    def validate_dimension(self):
        self.embed('CampusClaw embedding dimension check')


class ChatClient:
    def __init__(self, base_url=None, api_key=None, model=None):
        self.base_url = base_url if base_url is not None else os.environ.get('CHAT_BASE_URL') or os.environ.get('EMBEDDING_BASE_URL', '')
        self.api_key = api_key if api_key is not None else os.environ.get('CHAT_API_KEY') or os.environ.get('EMBEDDING_API_KEY', '')
        self.model = model if model is not None else os.environ.get('CHAT_MODEL', '')

    def complete_traceable(self, payload):
        if not self.model:
            raise AIClientError('chat 模型未配置')
        try:
            with _post_json(self.base_url, self.api_key, '/chat/completions', payload) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except JSONDecodeError as exc:
            raise AIClientError('chat 响应不是合法 JSON') from exc
        if not isinstance(data, dict) or not isinstance(data.get('choices'), list):
            raise AIClientError('chat 响应格式不正确')
        return data

    def complete(self, messages):
        payload = {'model': self.model, 'messages': messages, 'stream': False}
        data = self.complete_traceable(payload)
        try:
            return str(data['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError) as exc:
            raise AIClientError('chat 响应格式不正确') from exc
