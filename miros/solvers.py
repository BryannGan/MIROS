"""Locate external solvers on any OS."""
import glob
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

_CANDIDATES = ['OneDSolver', 'svOneDSolver', 'OneDSolver.exe', 'svOneDSolver.exe']

_KNOWN_DIRS = {
    'linux': ['/usr/local/sv/oneDSolver/*/bin', '/usr/local/sv/svOneDSolver/*/bin', '/usr/local/sv/svOneDSolver/*',
              '/opt/sv/oneDSolver/*/bin', '~/sv/oneDSolver/*/bin'],
    'darwin': ['/usr/local/sv/oneDSolver/*/bin', '/Applications/SimVascular/svOneDSolver/*', '/usr/local/sv/svOneDSolver/*'],
    'win32': ['C:/Program Files/SimVascular/svOneDSolver/*', 'C:/Program Files/SimVascular/oneDSolver/*/bin'],
}


def find_onedsolver(configured: Optional[str] = None) -> Optional[str]:
    """
    Order: explicit path from case.yaml -> MIROS_ONEDSOLVER -> PATH -> known
    install directories for this OS. Returns a path or None.
    """
    for p in (configured, os.environ.get('MIROS_ONEDSOLVER')):
        if p:
            p = os.path.expanduser(p)
            if Path(p).is_file():
                return p
    for name in _CANDIDATES:
        w = shutil.which(name)
        if w:
            return w
    key = 'win32' if sys.platform.startswith('win') else ('darwin' if sys.platform == 'darwin' else 'linux')
    found: List[str] = []
    for d in _KNOWN_DIRS[key]:
        for name in _CANDIDATES:
            found += glob.glob(os.path.join(os.path.expanduser(d), name))
    found = [f for f in found if os.path.isfile(f) and os.access(f, os.X_OK)]
    return sorted(found)[-1] if found else None      # newest version directory sorts last
