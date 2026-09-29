import os
import runpy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
for line in (root/'.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1); os.environ.setdefault(key,value)
runpy.run_path(str(root/'scripts/init_db.py'))
runpy.run_path(str(root/'run.py'),run_name='__main__')
