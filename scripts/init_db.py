import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import initialize
root=Path(__file__).resolve().parents[1]
initialize(os.environ.get('DATABASE_PATH',str(root/'data/app.db')),os.environ.get('UPLOAD_ROOT',str(root/'uploads')))
print('Database initialized; existing data preserved.')
