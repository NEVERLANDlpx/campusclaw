"""Generate a fresh local .env, never overwrite an existing one."""
import secrets
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'.env'
try:
    with path.open('x',encoding='utf-8') as f:
        f.write('SECRET_KEY='+secrets.token_hex(32)+'\nJWT_SECRET_KEY='+secrets.token_hex(32)+
                '\nMCP_SERVICE_TOKEN='+secrets.token_urlsafe(36)+'\nCOOKIE_SECURE=0\n')
    path.chmod(0o600)
    print('Created .env with a fresh key.')
except FileExistsError:
    text=path.read_text(encoding='utf-8')
    if not any(line.startswith('MCP_SERVICE_TOKEN=') and line.split('=',1)[1].strip() for line in text.splitlines()):
        with path.open('a',encoding='utf-8') as f:
            if text and not text.endswith('\n'): f.write('\n')
            f.write('MCP_SERVICE_TOKEN='+secrets.token_urlsafe(36)+'\n')
        print('Existing .env kept; appended a fresh MCP_SERVICE_TOKEN.')
    else:
        print('.env already exists; left unchanged. Check SECRET_KEY before startup.')
