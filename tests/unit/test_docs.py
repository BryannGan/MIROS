"""The documentation stays true: the template in it is the one `miros init` writes, and its links resolve."""
import re
from pathlib import Path

from miros.config import write_template

ROOT = Path(__file__).resolve().parents[2]
PAGES = [ROOT / 'README.md', ROOT / 'AGENTS.md'] + sorted((ROOT / 'docs').glob('*.md'))


def template_text() -> str:
    import tempfile
    p = Path(tempfile.mkdtemp()) / 'case.yaml'
    write_template(p, outlet_names=['cap_2', 'cap_3'], inlet='cap_1')
    return p.read_text(encoding='utf-8')


def test_case_file_page_carries_the_current_template():
    page = (ROOT / 'docs' / 'case-file.md').read_text(encoding='utf-8')
    block = re.search(r'<!-- template:begin -->\n```yaml\n(.*?)```\n<!-- template:end -->', page, re.S)
    assert block, 'docs/case-file.md has no template block'
    assert block.group(1) == template_text(), 'docs/case-file.md is behind write_template(); regenerate the block'


def test_local_links_in_the_pages_resolve():
    broken = []
    for page in PAGES:
        for target in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', page.read_text(encoding='utf-8')):
            if re.match(r'[a-z]+:', target):                     # http, mailto
                continue
            if not (page.parent / target).exists():
                broken.append('%s -> %s' % (page.relative_to(ROOT), target))
    assert not broken, broken
