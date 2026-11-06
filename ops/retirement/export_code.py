"""Verify/copy only four reviewed operator modules before any private key read."""

import hashlib
from pathlib import Path

if __package__:
    from .operator_files import directory, parse, read
else:
    from operator_files import directory, parse, read

FILES = ("operator_deadline.py", "archive.py", "backup_protocol.py", "export_peer.py")


def verify(root: Path, expected: str) -> None:
    directory(root)
    raw = read(root / "code-manifest.json", 16384)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("retirement_export_code_manifest_mismatch")
    value = parse(raw)
    if set(value) != set(FILES):
        raise RuntimeError("retirement_export_code_set_invalid")
    for name in FILES:
        if hashlib.sha256(read(root / name, 131072)).hexdigest() != value[name]:
            raise RuntimeError("retirement_export_code_changed")


BOOTSTRAP = r"""
import hashlib,json,os,pathlib,stat,sys,types
root=pathlib.Path('/operator')
def private(path,limit):
 d=path.parent.lstat()
 if path.resolve(strict=True)!=path or not stat.S_ISDIR(d.st_mode) or d.st_uid!=1000 or stat.S_IMODE(d.st_mode)!=0o700:raise RuntimeError('operator_code_directory')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode) or before.st_uid!=1000 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or not 0<before.st_size<=limit:raise RuntimeError('operator_code_file')
  raw=os.read(fd,limit+1);after,named=os.fstat(fd),path.lstat()
  if len(raw)!=before.st_size or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) or (named.st_dev,named.st_ino)!=(before.st_dev,before.st_ino):raise RuntimeError('operator_code_changed')
  return raw
 finally:os.close(fd)
raw=private(root/'code-manifest.json',16384)
if hashlib.sha256(raw).hexdigest()!=sys.argv[1]:raise RuntimeError('operator_manifest')
manifest=json.loads(raw)
names=('operator_deadline.py','archive.py','backup_protocol.py','export_peer.py')
if type(manifest)is not dict or set(manifest)!=set(names):raise RuntimeError('operator_files')
cache={name:private(root/name,131072) for name in names}
if any(hashlib.sha256(cache[name]).hexdigest()!=manifest[name] for name in names):raise RuntimeError('operator_bytes')
for name in ('ops','ops.retirement'):
 module=types.ModuleType(name);module.__path__=[];sys.modules[name]=module
for filename in names:
 name='ops.retirement.'+filename[:-3];module=types.ModuleType(name)
 module.__file__=str(root/filename);module.__package__='ops.retirement';sys.modules[name]=module
 exec(compile(cache[filename],module.__file__,'exec'),module.__dict__)
action=sys.argv[2]
if action not in ('head','export'):raise RuntimeError('operator_action')
sys.argv=[str(root/'export_peer.py'),'--action',action]
sys.modules['ops.retirement.export_peer'].main()
"""
