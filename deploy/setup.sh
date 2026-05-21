#!/usr/bin/env bash
#
# 环境准备脚本 —— 在 CentOS 7 上为 Zimbra 导入工具自动准备运行环境。
#
# 它做这些(全部幂等,可重复运行):
#   1. 创建系统用户 zimbra-import
#   2. 创建 /opt /etc /var 目录
#   3. yum 安装编译依赖
#   4. 并行编译安装 Python 3.11(make altinstall,不覆盖系统 python3)
#   5. 复制代码到 /opt/zimbra-import,建 venv 并装 pip 依赖
#   6. 放置 config.ini 模板(已存在则保留不覆盖)
#
# 它【不】做(需要你的输入或属于环境相关决策):
#   - 创建 Zimbra 服务账号
#   - 填写 config.ini 里的 secret_key / 服务账号密码
#   - 启动 systemd 服务
#   - 配置 nginx 反向代理
# 这些在脚本结束时会以「后续步骤」打印出来。
#
# 用法:解包项目后,以 root 执行  bash deploy/setup.sh
#
set -euo pipefail

PYTHON_VERSION=3.11.9
APP_DIR=/opt/zimbra-import
ETC_DIR=/etc/zimbra-import
VAR_DIR=/var/lib/zimbra-import
RUN_USER=zimbra-import
PYBIN=/usr/local/bin/python3.11

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

[ "$(id -u)" -eq 0 ] || { err "请用 root 运行此脚本"; exit 1; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")

# --- 1. 系统用户 ---------------------------------------------------------
if id "$RUN_USER" >/dev/null 2>&1; then
    log "用户 $RUN_USER 已存在,跳过"
else
    log "创建系统用户 $RUN_USER"
    useradd -r -s /sbin/nologin "$RUN_USER"
fi

# --- 2. 目录 -------------------------------------------------------------
log "创建目录 $APP_DIR $ETC_DIR $VAR_DIR"
mkdir -p "$APP_DIR" "$ETC_DIR" "$VAR_DIR"
chown -R "$RUN_USER:" "$VAR_DIR"

# --- 3. 编译依赖 ---------------------------------------------------------
log "安装编译依赖 (yum)"
yum groupinstall -y "Development Tools"
yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel curl

# --- 4. Python 3.11(幂等:已存在则跳过)--------------------------------
if [ -x "$PYBIN" ]; then
    log "已检测到 $($PYBIN --version 2>&1),跳过编译"
else
    log "编译安装 Python $PYTHON_VERSION(altinstall,不影响系统 python3)"
    cd /usr/src
    curl -fLO "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
    tar xf "Python-${PYTHON_VERSION}.tgz"
    cd "Python-${PYTHON_VERSION}"
    ./configure
    make -j"$(nproc)"
    make altinstall
    log "Python 安装完成:$($PYBIN --version 2>&1)"
fi

# --- 5. 代码与 venv ------------------------------------------------------
if [ "$PROJECT_DIR" = "$APP_DIR" ]; then
    log "已在 $APP_DIR 内运行,跳过代码复制"
else
    log "复制代码到 $APP_DIR"
    cp -r "$PROJECT_DIR"/. "$APP_DIR"/
fi

log "创建 venv 并安装依赖"
"$PYBIN" -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
chown -R "$RUN_USER:" "$APP_DIR"

# --- 6. 配置模板(不覆盖已有)------------------------------------------
if [ -f "$ETC_DIR/config.ini" ]; then
    log "$ETC_DIR/config.ini 已存在,保留不覆盖"
else
    log "安装配置模板到 $ETC_DIR/config.ini"
    cp "$APP_DIR/config.example.ini" "$ETC_DIR/config.ini"
    chmod 600 "$ETC_DIR/config.ini"
    chown "$RUN_USER:" "$ETC_DIR/config.ini"
fi

# --- 自检:venv 能否导入应用 --------------------------------------------
log "自检:导入应用模块"
( cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -c "import zimbra_import.web, zimbra_import.worker; print('  模块导入 OK')" )

log "环境准备完成。"
cat <<EOF

================================================================
后续步骤(脚本不自动做,需要你的输入):

  1. 编辑配置:vi $ETC_DIR/config.ini
       - secret_key:换成一个随机串(如 \`openssl rand -hex 32\`)
       - [service_account] name / password:服务账号的账号密码

  2. 在 Zimbra 上创建服务账号(专用管理员):
       su - zimbra -c "zmprov ca importsvc@msauto.com.cn '<强密码>'"
       su - zimbra -c "zmprov ma importsvc@msauto.com.cn zimbraIsAdminAccount TRUE"

  3. 安装并启动服务:
       cp $APP_DIR/deploy/*.service /etc/systemd/system/
       systemctl daemon-reload
       systemctl enable --now zimbra-import-web zimbra-import-worker

  4. 在 Zimbra nginx 上加反向代理,把 127.0.0.1:8088 经 HTTPS 暴露出去。
================================================================
EOF
