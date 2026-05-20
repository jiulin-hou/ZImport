import pytest
from zimbra_import import zimbra_auth


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Cfg:
    soap_url = "https://h:8443/service/soap"
    admin_soap_url = "https://h:7071/service/admin/soap"
    verify_tls = False
    svc_name = "svc@d"
    svc_password = "svcpw"


def _fault():
    return {"Body": {"Fault": {"Reason": {"Text": "auth failed"}}}}


def _admin_ok():
    return {"Body": {"AuthResponse": {"authToken": [{"_content": "ADMTOK"}]}}}


def _account_ok():
    return {"Body": {"AuthResponse": {"authToken": [{"_content": "USRTOK"}]}}}


def test_login_admin(monkeypatch):
    def fake_post(url, **kw):
        return _Resp(_admin_ok())  # admin 端点直接成功
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    ident = zimbra_auth.login(_Cfg, "admin@d", "pw")
    assert ident.is_admin is True
    assert ident.account == "admin@d"


def test_login_normal_user(monkeypatch):
    def fake_post(url, **kw):
        if "7071" in url:
            return _Resp(_fault())      # admin 登录失败
        return _Resp(_account_ok())     # account 登录成功
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    ident = zimbra_auth.login(_Cfg, "user@d", "pw")
    assert ident.is_admin is False
    assert ident.account == "user@d"


def test_login_bad_credentials(monkeypatch):
    def fake_post(url, **kw):
        return _Resp(_fault())
    monkeypatch.setattr(zimbra_auth.requests, "post", fake_post)
    with pytest.raises(zimbra_auth.AuthError):
        zimbra_auth.login(_Cfg, "user@d", "wrong")
