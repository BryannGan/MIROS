"""
`miros install`: the pieces MIROS drives, each fetched with one command.

    miros install pysvzerod          the 0D solver: a prebuilt wheel, else the git build
    miros install onedsolver         the 1D solver executable, prebuilt, into ~/.miros/bin
    miros install seqseg [--gpu]     SeqSeg with a torch for this machine, then the aorta weights
    miros install all                the three of them

The prebuilt wheels and executables are compiled from SimVascular's sources
by .github/workflows/build-solvers.yml on GitHub's Linux, macOS and Windows
runners and attached to this repository's release tagged `solvers`. When
nothing there fits this machine, pysvzerod is built from source (a C++
compiler is all that needs to be present; pip fetches CMake and Ninja) and
OneDSolver is left to the install guide.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .paths import bin_dir, home_dir

REPO = 'BryannGan/MIROS'
RELEASE_TAG = 'solvers'
ZEROD_GIT = 'git+https://github.com/simvascular/svZeroDSolver.git'
TORCH_CUDA_INDEX = 'https://download.pytorch.org/whl/cu128'
INSTALL_GUIDE = 'https://github.com/BryannGan/MIROS/blob/main/docs/install.md'


class InstallError(RuntimeError):
    pass


# ---- naming ----------------------------------------------------------------

def platform_key(system: Optional[str] = None, machine: Optional[str] = None) -> str:
    """'linux-x86_64', 'macos-arm64', 'macos-x86_64' or 'windows-x86_64': how the release names its assets."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    os_name = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}.get(system)
    arch = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine)
    if os_name is None or arch is None:
        raise InstallError('no prebuilt solvers for %s on %s; see %s' % (system, machine, INSTALL_GUIDE))
    return '%s-%s' % (os_name, arch)


def onedsolver_asset(key: str) -> str:
    return 'OneDSolver-%s%s' % (key, '.exe' if key.startswith('windows') else '')


def onedsolver_target(key: str) -> Path:
    return bin_dir() / ('OneDSolver.exe' if key.startswith('windows') else 'OneDSolver')


def wheel_matches(name: str, key: str, py: Sequence[int] = sys.version_info[:2]) -> bool:
    """A pysvzerod wheel for this interpreter (cp310 ...) and this platform."""
    if not (name.startswith('pysvzerod') and name.endswith('.whl')):
        return False
    if '-cp%d%d-' % tuple(py[:2]) not in name:
        return False
    os_name, arch = key.split('-')
    if os_name == 'windows':
        return 'win_amd64' in name
    if os_name == 'macos':
        return 'macosx' in name and (arch in name or 'universal2' in name)
    return 'linux' in name and 'x86_64' in name and 'macosx' not in name


# ---- the release -----------------------------------------------------------

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'miros', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def release_assets(tag: str = RELEASE_TAG, fetch: Callable[[str], bytes] = _get) -> List[Dict]:
    """[{name, url, size}] attached to the release; raises InstallError when it cannot be reached."""
    url = 'https://api.github.com/repos/%s/releases/tags/%s' % (REPO, tag)
    try:
        data = json.loads(fetch(url))
    except Exception as e:                       # noqa: BLE001 - offline, no such release, rate limit
        raise InstallError('cannot list the prebuilt solvers at %s (%s)' % (url, e))
    return [{'name': a['name'], 'url': a['browser_download_url'], 'size': a.get('size', 0)}
            for a in data.get('assets', [])]


def download(url: str, target: Path, progress=None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')

    def hook(count, block, total):
        if progress:
            progress(min(count * block, total), total)
    urllib.request.urlretrieve(url, str(part), reporthook=hook)
    part.replace(target)
    return target


# ---- the pieces ------------------------------------------------------------

def _pip(args: Sequence[str]) -> int:
    return subprocess.call([sys.executable, '-m', 'pip', 'install'] + list(args))


def importable(module: str) -> bool:
    """In a fresh interpreter, so a package installed a moment ago counts."""
    return subprocess.call([sys.executable, '-c', 'import ' + module],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def install_pysvzerod(log=print, run=_pip, fetch=_get, fetch_file=download, progress=None) -> str:
    """Returns 'present', 'wheel' or 'source'."""
    if importable('pysvzerod'):
        log('pysvzerod is already installed')
        return 'present'
    key = platform_key()
    try:
        assets = [a for a in release_assets(fetch=fetch) if wheel_matches(a['name'], key)]
    except InstallError as e:
        log(str(e))
        assets = []
    if assets:
        a = assets[0]
        log('prebuilt wheel %s (%.1f MB)' % (a['name'], a['size'] / 1e6))
        path = fetch_file(a['url'], home_dir() / 'wheels' / a['name'], progress)
        if run([str(path)]) == 0 and importable('pysvzerod'):
            return 'wheel'
        log('the prebuilt wheel did not work here; building from source instead')
    else:
        log('no prebuilt pysvzerod wheel for %s and Python %d.%d; building from source' % (key, *sys.version_info[:2]))
    log('this needs a C++ compiler (build-essential, the Xcode command line tools, or Visual Studio Build '
        'Tools with "Desktop development with C++"); CMake and Ninja are fetched by pip. A few minutes.')
    if run([ZEROD_GIT]) != 0 or not importable('pysvzerod'):
        raise InstallError('pysvzerod did not build; the compiler is the usual reason. See %s, step 3' % INSTALL_GUIDE)
    return 'source'


def install_onedsolver(log=print, fetch=_get, fetch_file=download, progress=None, verify: bool = True) -> Path:
    key = platform_key()
    want = onedsolver_asset(key)
    hit = next((a for a in release_assets(fetch=fetch) if a['name'] == want), None)
    if hit is None:
        raise InstallError('no prebuilt OneDSolver for %s in the `%s` release. Install SimVascular\'s package '
                           'or build it: %s, step 4' % (key, RELEASE_TAG, INSTALL_GUIDE))
    target = onedsolver_target(key)
    log('%s (%.1f MB) -> %s' % (want, hit['size'] / 1e6, target))
    fetch_file(hit['url'], target, progress)
    if os.name != 'nt':
        target.chmod(0o755)
    if verify:
        try:                                     # no arguments: it prints its usage and exits; running is the test
            subprocess.run([str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except OSError as e:
            raise InstallError('%s was downloaded but does not run here (%s)' % (target, e))
    return target


def has_nvidia_gpu() -> bool:
    return shutil.which('nvidia-smi') is not None


def install_seqseg(gpu: Optional[bool] = None, models: Sequence[str] = ('aorta_ct',), log=print, run=_pip,
                   progress=None) -> None:
    system = platform.system()
    if gpu is None:
        gpu = has_nvidia_gpu()
        log('NVIDIA GPU %s' % ('found (nvidia-smi)' if gpu else 'not found; torch for the CPU'))
    if gpu and system in ('Linux', 'Windows'):
        log('torch with CUDA 12.8 from %s' % TORCH_CUDA_INDEX)
        if run(['torch', '--index-url', TORCH_CUDA_INDEX]) != 0:
            raise InstallError('torch did not install from %s' % TORCH_CUDA_INDEX)
    elif gpu and system == 'Darwin':
        log('macOS: torch uses Apple silicon through MPS; there is no CUDA build')
    log('SeqSeg, nnU-Net and SimpleITK')
    if run(['seqseg>=2.1', 'SimpleITK']) != 0:
        raise InstallError('seqseg did not install')
    if models:
        from .models import download as download_model
        for name in models:
            log('weights: %s' % name)
            download_model(name, progress=progress)


def install_all(gpu: Optional[bool] = None, models: Sequence[str] = ('aorta_ct',), log=print, progress=None) -> Dict[str, str]:
    """Every piece; a missing prebuilt OneDSolver is reported, not fatal."""
    done = {}
    done['pysvzerod'] = install_pysvzerod(log=log, progress=progress)
    try:
        done['onedsolver'] = str(install_onedsolver(log=log, progress=progress))
    except InstallError as e:
        log(str(e))
        done['onedsolver'] = 'missing'
    install_seqseg(gpu=gpu, models=models, log=log, progress=progress)
    done['seqseg'] = 'ok'
    return done
