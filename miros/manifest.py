"""
Stage manifest: what each stage read, what it wrote, and when. A stage is
stale when any input's content hash changed or any output is missing, so
`miros run` redoes only the work that is actually out of date.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return 'sha256:' + h.hexdigest()


def value_hash(value: Any) -> str:
    return 'cfg:' + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:32]


def dir_hash(path) -> str:
    """Hash of a directory's file names and contents (sorted)."""
    h = hashlib.sha256()
    for p in sorted(Path(path).rglob('*')):
        if p.is_file():
            h.update(str(p.relative_to(path)).encode())
            h.update(file_hash(p).encode())
    return 'dir:' + h.hexdigest()[:32]


class Manifest:
    def __init__(self, path):
        self.path = Path(path)
        self.data: Dict[str, Dict[str, Any]] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding='utf-8')

    def record(self, stage: str, inputs: Dict[str, str], outputs: List[str], extra: Optional[dict] = None) -> None:
        self.data[stage] = {
            'inputs': inputs,
            'outputs': [str(o) for o in outputs],
            'finished_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'extra': extra or {},
        }
        self.save()

    def forget(self, stage: str) -> None:
        self.data.pop(stage, None)
        self.save()

    def status(self, stage: str, inputs: Dict[str, str]) -> Tuple[str, str]:
        """
        ('fresh' | 'stale' | 'never', reason)
        """
        rec = self.data.get(stage)
        if rec is None:
            return 'never', 'not run yet'
        for o in rec.get('outputs', []):
            if not Path(o).exists():
                return 'stale', 'output missing: %s' % Path(o).name
        old = rec.get('inputs', {})
        for k, v in inputs.items():
            if old.get(k) != v:
                return 'stale', 'input changed: %s' % k
        for k in old:
            if k not in inputs:
                return 'stale', 'input set changed'
        return 'fresh', rec.get('finished_at', '')
