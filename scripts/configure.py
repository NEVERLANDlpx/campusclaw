"""Generate a fresh local .env, never overwrite an existing one."""
import secrets
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'.env'
try:
    with path.open('x',encoding='utf-8') as f:
        f.write('SECRET_KEY='+secrets.token_hex(32)+'\nCOOKIE_SECURE=0\n')
    path.chmod(0o600)
    print('Created .env with a fresh key.')
except FileExistsError:
    print('.env already exists; left unchanged. Check SECRET_KEY before startup.')
