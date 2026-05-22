import pytest
from zimport import zimbra_inject


class _Cfg:
    rest_base = "https://h:8443"
    verify_tls = False


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.text = "err" if status >= 300 else "ok"


def test_inject_eml_builds_correct_request(tmp_path, monkeypatch):
    eml = tmp_path / "m.eml"
    eml.write_bytes(b"From: a@b\r\n\r\nhello")
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        captured["cookies"] = kw.get("cookies")
        captured["data"] = kw.get("data")
        return _Resp(200)

    monkeypatch.setattr(zimbra_inject.requests, "post", fake_post)
    zimbra_inject.inject_eml(_Cfg, "u@d", "Inbox", "TOK", str(eml))
    assert captured["url"] == "https://h:8443/home/u@d/Inbox"
    assert captured["params"]["fmt"] == "eml"
    assert captured["cookies"]["ZM_AUTH_TOKEN"] == "TOK"
    assert captured["data"] == b"From: a@b\r\n\r\nhello"


def test_inject_eml_raises_on_http_error(tmp_path, monkeypatch):
    eml = tmp_path / "m.eml"
    eml.write_bytes(b"x")
    monkeypatch.setattr(zimbra_inject.requests, "post",
                        lambda url, **kw: _Resp(500))
    with pytest.raises(zimbra_inject.InjectError):
        zimbra_inject.inject_eml(_Cfg, "u@d", "Inbox", "TOK", str(eml))


def test_inject_tgz_builds_correct_request(tmp_path, monkeypatch):
    tgz = tmp_path / "a.tgz"
    tgz.write_bytes(b"TGZDATA")
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        return _Resp(200)

    monkeypatch.setattr(zimbra_inject.requests, "post", fake_post)
    zimbra_inject.inject_tgz(_Cfg, "u@d", "TOK", str(tgz))
    assert captured["url"] == "https://h:8443/home/u@d/"
    assert captured["params"]["fmt"] == "tgz"
