# 更新日志

版本号遵循语义化版本(主.次.补丁)。每次迭代发布时:

1. 更新 `zimport/__init__.py` 的 `__version__`
2. 在本文件顶部加一条版本记录
3. 打对应的 git tag:`git tag -a vX.Y.Z -m "..."` 并 `git push origin vX.Y.Z`

## v1.0.0 — 2026-05-22

首个版本。

- 多 `.eml` 文件 / 大体积 `.tgz`(>5GB,分片上传 + 断点续传)导入 Zimbra
- 服务端解包归一化,从根本规避 Zimbra 导入器的 PaxHeader 故障
- 管理员批量导入 + 终端用户自助两种模式
- SQLite 任务队列,后台串行 worker,进度可追踪、服务重启可恢复
- 服务账号委托认证;越权防护;`upload_id` 校验;保留期自动清理
- systemd 部署 + 一键环境准备脚本 `deploy/setup.sh`
- 39 个单元测试 + 2 个集成测试
