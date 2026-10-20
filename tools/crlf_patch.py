"""Apply exact text replacements to a file, preserving its CRLF/LF line endings.

Usage: python crlf_patch.py FILE SPEC.py
SPEC.py defines REPLACEMENTS = [(old, new, expected_count), ...] written with LF.
"""
import sys, runpy

path, spec = sys.argv[1], sys.argv[2]
raw = open(path, 'rb').read().decode('utf-8')
crlf = '\r\n' in raw
text = raw.replace('\r\n', '\n')
for old, new, count in runpy.run_path(spec)['REPLACEMENTS']:
    found = text.count(old)
    if found != count:
        sys.exit(f"{path}: expected {count} match(es), found {found}:\n{old[:200]}")
    text = text.replace(old, new)
if crlf:
    text = text.replace('\n', '\r\n')
open(path, 'wb').write(text.encode('utf-8'))
print(f"patched {path} ({'CRLF' if crlf else 'LF'})")
