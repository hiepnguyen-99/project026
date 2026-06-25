import sys
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
project_root = str(PROJECT_ROOT)
if project_root in sys.path:
    sys.path.remove(project_root)
sys.path.insert(0, project_root)

os.environ.setdefault("N8N_POLICY_SECRET", "test-n8n-policy-secret-please-rotate")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "test-token-encryption-key-please-rotate")
os.environ.setdefault("SESSION_TTL_MINUTES", "480")
os.environ.setdefault("EDUVAULT_SEED_PASSWORD_GV001", "test-gv001-password")
os.environ.setdefault("EDUVAULT_SEED_PASSWORD_GVNEW", "test-gvnew-password")
os.environ.setdefault("EDUVAULT_SEED_PASSWORD_TBM01", "test-tbm01-password")
os.environ.setdefault("EDUVAULT_SEED_PASSWORD_ADMIN", "test-admin-password")
