# 更新日志

版本号遵循语义化版本(主.次.补丁)。发版流程:

1. 在本文件顶部加一条新版本记录(`## vX.Y.Z — 日期` 加改动条目)
2. 运行 `bash deploy/release.sh X.Y.Z` —— 自动跑测试、写版本号、提交、
   打 tag、推送 main 与 tag、生成 `dist/zimport-X.Y.Z.tar.gz`

## v1.1.0 — 2026-05-22

UI 与可部署性大版本。

**前端 / 后端**

- 目标文件夹改为按账户实际拉取的下拉(`/api/folders`,委托认证调
  `GetFolderRequest`)。管理员切目标账户后自动刷新
- 管理员目标账户改为 datalist autocomplete,输入 2+ 字符触发
  `/api/admin/accounts/search`(SOAP `SearchDirectoryRequest`,limit 20)
- 修跨账户残留 bug:登录/登出时 reset 前端状态(文件选择、任务表、轮询
  定时器、错误提示等),不再泄露到下一个账户
- UI 重写:CSS 变量、卡片阴影、status chip、toast 错误提示、上传进度条、
  暗色模式

**eml 去重**

- 单封 eml 注入前按 `Message-ID` 双层去重:同一批 eml 内部用 set 去重(零网络
  开销);邮箱内已存在则 SOAP `SearchRequest` 查到后跳过
- 任务新增 `skipped` 计数列(老 DB 用 ALTER TABLE 自动升级);任务表多一列「跳过」
- `[scheduler] dedupe = true/false` 配置开关,默认 true。tgz 路径不受影响,
  仍走 Zimbra 原生 `resolve=skip`
- Zimbra 查询用 `msgid:` 操作符并剥掉 Message-ID 头的 `<>`(`messageid:` 是
  无效操作符,`msgid:"<id>"` 也命不中,均会静默 0 hit)

**失败处理与重试**

- 单封 eml 失败时自动 retry 最多 2 次,仅对 transient(`network:`、`HTTP 5xx`、
  `HTTP 429`、`HTTP 408`)生效,业务错(如 4xx)立即抛出;退避 1.5s / 2.25s
- 修隐藏 bug:`zimbra_inject.inject_eml/tgz` 现在把 `requests.RequestException`
  wrap 成 `InjectError`,网络抖不再让整任务变 `failed`(此前会丢已注入进度)
- 新增 `POST /api/tasks/<id>/retry`:对 `failed`/`interrupted` 任务一键重新
  入队(复用原 `temp_dir`)。`requester` 或 admin 可调用;`temp_dir` 已被
  purge 时返回 410
- worker 处理任务时先清 `work/` 目录,确保 retry 任务的 `archive.normalize`
  在干净环境跑
- 前端任务行点击可展开,显示 `error`(任务级)+ `failures`(单封 name/reason
  列表)+ 失败/中断任务的「重试」按钮

**部署**

- `setup.sh` 处理 CentOS/RHEL 7 OpenSSL 1.0.2 太旧的问题(自动装 EPEL +
  openssl11,让 Python 3.11 编出 `_ssl`)
- `setup.sh` yum 依赖补全:sqlite/readline/ncurses/libuuid/gdbm-devel
- `setup.sh` 自动化:`secret_key` 随机生成;同机 Zimbra 时探测域名 + 自动
  `zmprov ca` 创建服务账号
- `zimport-web.service` 加 `Environment=PYTHONPATH=/opt/zimport`(没这行时
  `python deploy/run_web.py` 的 sys.path 找不到 zimport 包,启动失败)
- 新增 `deploy/setup-proxy.sh`:Zimbra 同机 nginx 反代脚本化(改 template +
  zmproxyctl restart,`--port` 可配)
- 新增 `deploy/update.sh`:从开发机推代码 + 重启服务的升级路径

## v1.0.1 — 2026-05-22

- 新增一键发版脚本 `deploy/release.sh`
- 新增项目 `README.md`,含新机器下载与部署指引
- `.gitignore` 忽略 `dist/`(发版生成的交付包目录)

## v1.0.0 — 2026-05-22

首个版本。

- 多 `.eml` 文件 / 大体积 `.tgz`(>5GB,分片上传 + 断点续传)导入 Zimbra
- 服务端解包归一化,从根本规避 Zimbra 导入器的 PaxHeader 故障
- 管理员批量导入 + 终端用户自助两种模式
- SQLite 任务队列,后台串行 worker,进度可追踪、服务重启可恢复
- 服务账号委托认证;越权防护;`upload_id` 校验;保留期自动清理
- systemd 部署 + 一键环境准备脚本 `deploy/setup.sh`
- 39 个单元测试 + 2 个集成测试
