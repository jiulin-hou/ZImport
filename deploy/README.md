# 部署说明

本工具需要 Python 3.8+。CentOS 7 自带的是 Python 3.6,所以要并行安装一个较新的
Python —— 不要替换系统 python3(yum 等系统工具依赖它)。venv 完全隔离,对 Zimbra 无影响。

## 1. 系统用户与目录
    useradd -r -s /sbin/nologin zimbra-import
    mkdir -p /opt/zimbra-import /etc/zimbra-import /var/lib/zimbra-import
    chown -R zimbra-import: /var/lib/zimbra-import

## 2. 并行安装较新的 Python (3.11)
    yum groupinstall -y "Development Tools"
    yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel
    cd /usr/src
    curl -LO https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
    tar xf Python-3.11.9.tgz && cd Python-3.11.9
    ./configure --enable-optimizations
    make -j"$(nproc)"
    make altinstall          # 生成 /usr/local/bin/python3.11,不覆盖系统 python3

## 3. 代码与依赖
    cp -r zimbra-import/* /opt/zimbra-import/
    cd /opt/zimbra-import
    /usr/local/bin/python3.11 -m venv venv
    venv/bin/pip install -r requirements.txt
    chown -R zimbra-import: /opt/zimbra-import

## 4. 配置
    cp config.example.ini /etc/zimbra-import/config.ini
    chmod 600 /etc/zimbra-import/config.ini
    chown zimbra-import: /etc/zimbra-import/config.ini
编辑 config.ini:填入 secret_key(随机串)、service_account 的账号密码。

## 5. 服务账号
在 Zimbra 上创建一个专用管理员账号作为服务账号:
    su - zimbra -c "zmprov ca importsvc@msauto.com.cn '<强密码>'"
    su - zimbra -c "zmprov ma importsvc@msauto.com.cn zimbraIsAdminAccount TRUE"
把账号密码写入 config.ini 的 [service_account]。

## 6. 启动
    cp deploy/*.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now zimbra-import-web zimbra-import-worker

## 7. 反向代理(经 Zimbra nginx 暴露 HTTPS)
web 进程只监听 127.0.0.1。在 Zimbra nginx 上加一个 location 反代到
127.0.0.1:8088,复用已有的 Let's Encrypt 证书,对外只走 HTTPS。

## 8. 服务账号凭据轮换
config.ini 含服务账号密码,文件权限须为 600;定期轮换该账号密码并同步更新。
