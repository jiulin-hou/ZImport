import os
import io
import tarfile
import pytest

from zimport.config import Config
from zimport import archive, zimbra_auth, zimbra_inject

RUN = os.environ.get("ZIMBRA_IT") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="set ZIMBRA_IT=1 to run")

CONFIG = os.environ.get("ZIMBRA_IT_CONFIG", "/etc/zimport/config.ini")
TARGET = "importtest@msauto.com.cn"


def test_delegate_and_inject_single_eml(tmp_path):
    cfg = Config(CONFIG)
    token = zimbra_auth.delegate_token(cfg, TARGET)
    eml = tmp_path / "it.eml"
    eml.write_bytes(b"From: it@test\r\nSubject: IT probe\r\n\r\nbody\r\n")
    zimbra_inject.inject_eml(cfg, TARGET, "Inbox", token, str(eml))
    # 人工确认:登录 importtest 的 webmail,Inbox 应出现 "IT probe"


def test_normalize_and_inject_pax_bundle(tmp_path):
    cfg = Config(CONFIG)
    inp = tmp_path / "input"
    inp.mkdir() if False else os.makedirs(str(inp))
    longname = "Re_ " + "入出库通知采购" * 6 + ".eml"
    with tarfile.open(str(inp / "b.tgz"), "w:gz",
                      format=tarfile.PAX_FORMAT) as tar:
        content = b"From: it@test\r\nSubject: IT pax probe\r\n\r\nx\r\n"
        info = tarfile.TarInfo(name=longname)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    work = tmp_path / "work"
    os.makedirs(str(work))
    norm = archive.normalize(str(inp), str(work))
    assert norm.kind == "eml-bundle" and len(norm.eml_paths) == 1
    token = zimbra_auth.delegate_token(cfg, TARGET)
    zimbra_inject.inject_eml(cfg, TARGET, "Inbox", token, norm.eml_paths[0])
    # 人工确认:webmail Inbox 出现 "IT pax probe"
