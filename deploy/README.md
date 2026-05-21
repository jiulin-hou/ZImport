# 部署说明

本工具需要 Python 3.8+。CentOS 7 自带的是 Python 3.6,所以要并行安装一个较新的
Python —— 不要替换系统 python3(yum 等系统工具依赖它)。venv 完全隔离,对 Zimbra 无影响。

## 快速部署:用 setup.sh

环境准备(系统用户、目录、编译依赖、Python 3.11、venv、依赖、配置模板)已全部
脚本化。解包项目后,以 root 执行:

    bash deploy/setup.sh

脚本是幂等的,可重复运行。它完成后会打印剩下的手工步骤(下面第 1–4 节)。

`setup.sh` 自动做:
- 创建系统用户 `zimbra-import`
- 创建 `/opt/zimbra-import`、`/etc/zimbra-import`、`/var/lib/zimbra-import`
- yum 安装编译依赖
- 并行编译安装 Python 3.11(`make altinstall`,不覆盖系统 python3)
- 复制代码到 `/opt/zimbra-import`,建 venv 并安装 pip 依赖
- 放置 `/etc/zimbra-import/config.ini` 模板(已存在则保留不覆盖)

`setup.sh` 不做(需要你的输入,见下文):填写配置、创建 Zimbra 服务账号、启动服务、配反代。

---

## setup.sh 之后的手工步骤

### 1. 填写配置
    vi /etc/zimbra-import/config.ini
- `secret_key`:换成随机串,如 `openssl rand -hex 32`
- `[service_account]` 的 `name` / `password`:服务账号的账号密码

### 2. 创建 Zimbra 服务账号
专用管理员账号,供 worker 做委托认证:

    su - zimbra -c "zmprov ca importsvc@msauto.com.cn '<强密码>'"
    su - zimbra -c "zmprov ma importsvc@msauto.com.cn zimbraIsAdminAccount TRUE"

把账号密码写入 `config.ini` 的 `[service_account]`。

### 3. 启动服务
    cp /opt/zimbra-import/deploy/*.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now zimbra-import-web zimbra-import-worker

### 4. 反向代理(经 Zimbra nginx 暴露 HTTPS)
web 进程只监听 127.0.0.1。在 Zimbra nginx 上加一个 location 反代到
`127.0.0.1:8088`,复用已有的 Let's Encrypt 证书,对外只走 HTTPS。

---

## 维护

- **服务账号凭据轮换**:`config.ini` 含服务账号密码,文件权限须为 `600`;
  定期轮换该账号密码并同步更新 `config.ini`。
- **手工运行环境准备**:若不想用 `setup.sh`,可参照其内容逐步手工执行。

---

## 手工部署(不使用 setup.sh)

如需逐步手工操作,等价步骤:

    # 1. 系统用户与目录
    useradd -r -s /sbin/nologin zimbra-import
    mkdir -p /opt/zimbra-import /etc/zimbra-import /var/lib/zimbra-import
    chown -R zimbra-import: /var/lib/zimbra-import

    # 2. 并行安装 Python 3.11
    yum groupinstall -y "Development Tools"
    yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel curl
    cd /usr/src
    curl -fLO https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
    tar xf Python-3.11.9.tgz && cd Python-3.11.9
    ./configure && make -j"$(nproc)" && make altinstall

    # 3. 代码与依赖
    cp -r zimbra-import/. /opt/zimbra-import/
    cd /opt/zimbra-import
    /usr/local/bin/python3.11 -m venv venv
    venv/bin/pip install -r requirements.txt
    chown -R zimbra-import: /opt/zimbra-import

    # 4. 配置模板
    cp config.example.ini /etc/zimbra-import/config.ini
    chmod 600 /etc/zimbra-import/config.ini
    chown zimbra-import: /etc/zimbra-import/config.ini

然后照上面的「手工步骤 1–4」继续。
