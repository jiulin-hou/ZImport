import os
import tarfile


def _safe_members(tar, dest):
    dest = os.path.realpath(dest)
    members = tar.getmembers()
    for m in members:
        if m.issym() or m.islnk():
            raise ValueError("archive contains a link entry: %s" % m.name)
        target = os.path.realpath(os.path.join(dest, m.name))
        if target != dest and not target.startswith(dest + os.sep):
            raise ValueError("unsafe path in archive: %s" % m.name)
    return members


def unpack_tgz(tgz_path, dest_dir):
    """Extract a .tgz to dest_dir. Handles pax/gnu formats. Rejects path
    traversal and link entries. Returns dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(tgz_path, "r:*") as tar:
        members = _safe_members(tar, dest_dir)
        tar.extractall(dest_dir, members=members)
    return dest_dir
