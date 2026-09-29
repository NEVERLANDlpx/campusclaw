import re
from pathlib import Path


ROOT = Path('deliverables/03_截图与证据')
PATTERNS = [
    (re.compile(r'(Cookie: )([^\r\n]+)', re.I), r'\1[REDACTED]'),
    (re.compile(r'(Set-Cookie: )([^\r\n;=]+)=([^;\r\n]+)', re.I), r'\1\2=[REDACTED]'),
    (re.compile(r'("cookie"\s*:\s*")([^"]+)(")', re.I), r'\1[REDACTED]\3'),
    (re.compile(r'("set-cookie"\s*:\s*")([^"=]+)=([^;"]+)', re.I), r'\1\2=[REDACTED]'),
    (re.compile(r'(password=)([^&\s\r\n]+)', re.I), r'\1[REDACTED]'),
    (re.compile(r'("password"\s*:\s*")([^"]+)(")', re.I), r'\1[REDACTED]\3'),
    (re.compile(r'(csrf_token=)([^&\s\r\n]+)', re.I), r'\1[REDACTED]'),
    (re.compile(r'("csrf_token"\s*:\s*")([^"]+)(")', re.I), r'\1[REDACTED]\3'),
    (re.compile(r'(campusclaw_session=)([^;\s"\r\n]+)', re.I), r'\1[REDACTED]'),
]


def main():
    changed = 0
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in {'.http', '.txt', '.json', '.har'}:
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        original = text
        for pattern, replacement in PATTERNS:
            text = pattern.sub(replacement, text)
        if text != original:
            path.write_text(text, encoding='utf-8')
            changed += 1
    print(f'sanitized {changed} evidence files')


if __name__ == '__main__':
    main()
