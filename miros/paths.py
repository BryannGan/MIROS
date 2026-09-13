"""Where MIROS keeps what it fetches: ~/.miros (override with MIROS_HOME)."""
import os
from pathlib import Path


def home_dir() -> Path:
    d = os.environ.get('MIROS_HOME')
    return Path(d).expanduser() if d else Path.home() / '.miros'


def bin_dir() -> Path:
    """Executables `miros install` fetched, e.g. OneDSolver."""
    return home_dir() / 'bin'


def models_dir() -> Path:
    """SeqSeg weights (MIROS_MODELS_DIR overrides)."""
    d = os.environ.get('MIROS_MODELS_DIR')
    return Path(d).expanduser() if d else home_dir() / 'models'
