# ZImport

给 Zimbra 账户批量导入邮件数据的 Web 工具 —— 支持多 `.eml` 文件和大体积 `.tgz`
(>5GB),从根本上规避 Zimbra 自带导入器的 PaxHeader 故障。

## 它解决什么问题

Zimbra 自带的「导入/导出」在导入 tgz 时,如果包是用非标准工具(如 macOS tar)打的、
且含超长或非 ASCII 文件名,tar 会写入 pax 扩展头,产生 `PaxHeader` 伪条目,Zimbra 导入器
不识别而失败(报「文件夹 /PaxHeader/ 中不能包括 document 项目类型」)。

ZImport 在服务端用标准方式解包再规整,Zimbra 永远只收到干净的包。

## 功能

- 一次上传多个 `.eml`,或一个大 `.tgz`(分片上传 + 断点续传,>5GB 无压力)
- 两种 tgz 都支持:纯 eml 打包、Zimbra 完整账户导出(还原文件夹/联系人/日历)
- 管理员批量导入(可指定任意账户)+ 终端用户自助(只能导自己)
- 后台任务队列,进度可追踪,关页面或服务重启都不丢任务
- 串行 worker,多人同时发起也不会压垮 Zimbra

## 架构

双进程:web 进程(Flask)处理登录 / 分片上传 / 入队;worker 进程消费 SQLite 任务队列、
解包归一化、经 Zimbra REST 注入邮件。详见 [`docs/design.md`](docs/design.md)。

## 环境要求

- 目标机:运行 Zimbra 的服务器,或同网络可访问 Zimbra 的内网机器
- 操作系统:CentOS 7(其它 Linux 亦可,部署脚本针对 CentOS 7 编写)
- Python 3.8+(`setup.sh` 会并行安装 3.11,不动系统 python3)

## 在新机器上下载与部署

### 1. 获取代码

**方式 A —— git 克隆**(仓库公开则免认证):

    git clone https://github.com/jiulin-hou/ZImport.git
    cd ZImport

**方式 B —— 下载指定版本的发布包**:

    curl -LO https://github.com/jiulin-hou/ZImport/archive/refs/tags/v1.0.0.tar.gz
    tar xf v1.0.0.tar.gz
    cd ZImport-1.0.0

### 2. 一键环境准备

以 root 运行环境准备脚本(建系统用户、并行装 Python 3.11、建 venv、装依赖、
放配置模板):

    sudo bash deploy/setup.sh

脚本幂等,可重复运行;它**不替换系统 python3**,对 Zimbra 无影响。

### 3. 完成手工步骤

`setup.sh` 跑完会打印剩下的步骤 —— 填配置、在 Zimbra 上建服务账号、启动 systemd
服务、配 nginx 反向代理。完整说明见 [`deploy/README.md`](deploy/README.md)。

### 4. 访问

部署完成后,经 Zimbra nginx 反代以 HTTPS 访问导入页面,用 Zimbra 账号登录即可使用。

## 使用

1. 浏览器打开导入页面,用 Zimbra 账号登录
2. (管理员)填目标账户,或留空导入到自己;选目标文件夹
3. 选多个 `.eml` 或一个 `.tgz`,点「开始导入」
4. 上传完成后任务转入后台;在「我的任务」看进度,可关页面稍后再看

## 开发

    python3 -m venv venv          # 需要 Python 3.8+
    venv/bin/pip install -r requirements.txt
    venv/bin/python -m pytest tests/ -q

集成测试(需真实 Zimbra)默认跳过,见 [`tests/test_integration.py`](tests/test_integration.py)。

## 发版

编辑 `CHANGELOG.md` 加好新版本段落,然后一条命令完成发版:

    bash deploy/release.sh X.Y.Z

详见 [`CHANGELOG.md`](CHANGELOG.md)。

## 目录结构

    zimport/        后端模块 + 前端 static/
    tests/          单元与集成测试
    deploy/         setup.sh / release.sh / systemd 单元 / 部署说明
    docs/           设计文档与实现计划

## 文档

- [`docs/design.md`](docs/design.md) —— 设计文档
- [`docs/implementation-plan.md`](docs/implementation-plan.md) —— 实现计划
- [`deploy/README.md`](deploy/README.md) —— 部署详细步骤
- [`CHANGELOG.md`](CHANGELOG.md) —— 版本历史
