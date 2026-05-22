import requests


class InjectError(Exception):
    pass


def inject_eml(cfg, account, folder, token, eml_path):
    url = "%s/home/%s/%s" % (cfg.rest_base, account, folder.strip("/"))
    with open(eml_path, "rb") as fh:
        data = fh.read()
    r = requests.post(url, params={"fmt": "eml"}, data=data,
                      cookies={"ZM_AUTH_TOKEN": token},
                      headers={"Content-Type": "message/rfc822"},
                      verify=cfg.verify_tls, timeout=120)
    if r.status_code >= 300:
        raise InjectError("HTTP %s: %s" % (r.status_code, r.text[:200]))


def inject_tgz(cfg, account, token, tgz_path):
    url = "%s/home/%s/" % (cfg.rest_base, account)
    with open(tgz_path, "rb") as fh:
        r = requests.post(url, params={"fmt": "tgz", "resolve": "skip"},
                          data=fh, cookies={"ZM_AUTH_TOKEN": token},
                          verify=cfg.verify_tls, timeout=3600)
    if r.status_code >= 300:
        raise InjectError("HTTP %s: %s" % (r.status_code, r.text[:200]))
