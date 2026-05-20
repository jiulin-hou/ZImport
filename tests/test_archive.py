import io
import os
import tarfile
import pytest
from zimbra_import import archive


def _make_tgz(path, files, fmt=tarfile.PAX_FORMAT):
    """files: dict of arcname -> bytes content."""
    with tarfile.open(path, "w:gz", format=fmt) as tar:
        for arcname, content in files.items():
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))


def test_unpack_pax_archive(tmp_path):
    tgz = tmp_path / "a.tgz"
    longname = "Re_ " + "入出库通知" * 6 + ".eml"  # >100 bytes, non-ASCII
    _make_tgz(str(tgz), {longname: b"From: a@b\r\n\r\nhi"})
    dest = tmp_path / "out"
    archive.unpack_tgz(str(tgz), str(dest))
    assert (dest / longname).read_bytes() == b"From: a@b\r\n\r\nhi"


def test_unpack_rejects_path_traversal(tmp_path):
    tgz = tmp_path / "evil.tgz"
    _make_tgz(str(tgz), {"../escape.eml": b"x"})
    with pytest.raises(ValueError):
        archive.unpack_tgz(str(tgz), str(tmp_path / "out2"))
    assert not (tmp_path / "escape.eml").exists()


def test_unpack_rejects_symlink_entry(tmp_path):
    tgz = tmp_path / "sym.tgz"
    with tarfile.open(str(tgz), "w:gz") as tar:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../outside"
        tar.addfile(info)
    with pytest.raises(ValueError):
        archive.unpack_tgz(str(tgz), str(tmp_path / "out3"))


def test_detect_eml_bundle(tmp_path):
    d = tmp_path / "b1"
    d.mkdir()
    (d / "1.eml").write_bytes(b"x")
    (d / "2.eml").write_bytes(b"y")
    assert archive.detect_kind(str(d)) == "eml-bundle"


def test_detect_zimbra_export(tmp_path):
    d = tmp_path / "b2"
    sub = d / "Inbox"
    sub.mkdir(parents=True)
    (sub / "100").write_bytes(b"msg")
    (sub / "100.meta").write_bytes(b"<meta/>")
    assert archive.detect_kind(str(d)) == "zimbra-export"
