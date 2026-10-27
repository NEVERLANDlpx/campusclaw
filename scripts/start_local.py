import runpy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from app import load_local_env
load_local_env()
runpy.run_path(str(root/'scripts/init_db.py'))
runpy.run_path(str(root/'run.py'),run_name='__main__')
