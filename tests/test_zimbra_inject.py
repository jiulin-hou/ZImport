import pytest
from zimport import zimbra_inject


class _Cfg:
    rest_base = "https://h:8443"
    soap_url = "https://h:8443/service/soap"
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


def test_read_message_id(tmp_path):
    eml = tmp_path / "m.eml"
    eml.write_bytes(
        b"From: a@b\r\n"
        b"To: c@d\r\n"
        b"Message-ID: <abc.123@example.com>\r\n"
        b"\r\nhello body")
    assert zimbra_inject.read_message_id(str(eml)) == "<abc.123@example.com>"


def test_read_message_id_missing(tmp_path):
    eml = tmp_path / "m.eml"
    eml.write_bytes(b"From: a@b\r\n\r\nbody")
    assert zimbra_inject.read_message_id(str(eml)) == ""


class _SoapResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_message_exists_hit(monkeypatch):
    monkeypatch.setattr(zimbra_inject.requests, "post",
                        lambda *a, **kw: _SoapResp({"Body": {
                            "SearchResponse": {"m": [{"id": "1"}]}}}))
    assert zimbra_inject.message_exists(_Cfg, "TOK", "<id@x>") is True


def test_message_exists_miss(monkeypatch):
    monkeypatch.setattr(zimbra_inject.requests, "post",
                        lambda *a, **kw: _SoapResp({"Body": {
                            "SearchResponse": {}}}))
    assert zimbra_inject.message_exists(_Cfg, "TOK", "<id@x>") is False


def test_message_exists_empty_id_skips_call(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("network must not be called for empty id")
    monkeypatch.setattr(zimbra_inject.requests, "post", boom)
    assert zimbra_inject.message_exists(_Cfg, "TOK", "") is False


def test_message_exists_fault_returns_false(monkeypatch):
    # SOAP 失败时不阻塞,默认 False(让 inject 继续走 — 重复了再让 Zimbra 拒)
    monkeypatch.setattr(zimbra_inject.requests, "post",
                        lambda *a, **kw: _SoapResp({"Body": {"Fault": {
                            "Reason": {"Text": "boom"}}}}))
    assert zimbra_inject.message_exists(_Cfg, "TOK", "<id@x>") is False


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
