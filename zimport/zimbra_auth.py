import collections
import requests

Identity = collections.namedtuple("Identity", ["is_admin", "account"])


class AuthError(Exception):
    pass


def _soap(url, body, verify, header=None):
    payload = {"Body": body}
    if header:
        payload["Header"] = header
    r = requests.post(url, json=payload, verify=verify, timeout=30)
    data = r.json()
    inner = data.get("Body", {})
    if "Fault" in inner:
        raise AuthError(inner["Fault"]["Reason"]["Text"])
    return inner


def login(cfg, username, password):
    """admin 端口能登录成功即视为管理员;否则尝试普通账户登录。"""
    admin_body = {"AuthRequest": {"_jsns": "urn:zimbraAdmin",
                                  "name": username, "password": password}}
    try:
        _soap(cfg.admin_soap_url, admin_body, cfg.verify_tls)
        return Identity(is_admin=True, account=username)
    except AuthError:
        pass
    acct_body = {"AuthRequest": {
        "_jsns": "urn:zimbraAccount",
        "account": {"by": "name", "_content": username},
        "password": {"_content": password}}}
    try:
        _soap(cfg.soap_url, acct_body, cfg.verify_tls)
    except AuthError:
        raise AuthError("登录失败:账号或密码错误")
    return Identity(is_admin=False, account=username)


def admin_token(cfg):
    """以服务账号取得 admin authToken,供其它需要管理员凭据的模块复用。"""
    body = {"AuthRequest": {"_jsns": "urn:zimbraAdmin",
                            "name": cfg.svc_name,
                            "password": cfg.svc_password}}
    resp = _soap(cfg.admin_soap_url, body, cfg.verify_tls)
    return resp["AuthResponse"]["authToken"][0]["_content"]


_admin_token = admin_token  # 兼容旧引用


def delegate_token(cfg, target_account):
    """用服务账号取得目标账户的委托 token。worker 注入前即时调用。"""
    admin_tok = admin_token(cfg)
    header = {"context": {"_jsns": "urn:zimbra",
                          "authToken": {"_content": admin_tok}}}
    body = {"DelegateAuthRequest": {
        "_jsns": "urn:zimbraAdmin",
        "account": {"by": "name", "_content": target_account}}}
    resp = _soap(cfg.admin_soap_url, body, cfg.verify_tls, header=header)
    return resp["DelegateAuthResponse"]["authToken"][0]["_content"]
