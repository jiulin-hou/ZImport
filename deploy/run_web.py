import sys
from zimbra_import.config import Config
from zimbra_import.web import create_app

cfg = Config(sys.argv[1] if len(sys.argv) > 1 else "/etc/zimbra-import/config.ini")
app = create_app(cfg)

if __name__ == "__main__":
    app.run(host=cfg.listen_host, port=cfg.listen_port)
