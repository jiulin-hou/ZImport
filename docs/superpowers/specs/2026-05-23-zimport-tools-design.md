# ZImport-tools — Zimbra 内置工具版 · 设计文档

| 项目 | 内容 |
|---|---|
| 文档日期 | 2026-05-23 |
| 项目名称 | **ZImport-tools** |
| GitHub 仓库 | `https://github.com/jiulin-hou/ZImport-tools`(待新建) |
| 与 ZImport 的关系 | 独立姊妹项目,**单独维护、单独版本线**;不替代现有 standalone ZImport,二者并行 |
| 目标平台 | Zimbra 8.8.15 FOSS @ `mail.msauto.com.cn`(经典 Zimlet 框架) |
| 起始版本 | v1.0.0(独立计版本号,**不与 ZImport 的版本绑定**) |
| 状态 | 设计待 review;待 user 在 GitHub 上手工创建空仓库后开始码代码并推送 |

> **本文档取代** `2026-05-23-zimlet-integration-design.md`(那份是把 Zimlet 作为 standalone ZImport 的扩展;
> 经过讨论决定改做独立姊妹项目,设计因此重组。)

---

## 1. 背景与目标

现有 ZImport(`jiulin-hou/ZImport`)是个独立 Web 工具:用户在 ZImport 自己的登录框填一次账号密码 → 上传 → 导入。优点是独立部署、可在 Zimbra Web 之外访问。

**ZImport-tools 的定位:Zimbra Web 内置的导入工具。**

- 只在 Zimbra Web 里使用,**没有独立访问形态**
- 通过 Zimbra 的 cookie 直接识别身份,**用户感知不到登录步骤**
- 仍是同样的 Python 后端管线(分片上传、SQLite 队列、worker、归一化、去重、重试),只是入口和认证方式不同
- 作为 Zimlet 在 Zimbra Web 应用栏注册一个「数据导入」页签

**为何另起仓库而不在 ZImport 里加分支?**

- 两个版本的运行形态差异够大:一个是独立 Web 服务、有自己的登录;另一个只活在 Zimbra Web 里、不登录。把两套形态揉进同一份代码会让每条路径都更复杂,测试矩阵翻倍。
- 独立仓库、独立版本线、独立 issue 跟踪,各自演进更干净。
- 代码上有重叠的部分(`archive.py`、`store.py`、`uploads.py`、`worker.py` 等核心管线)将以**初始复制**方式继承自 ZImport;**初始基线 = ZImport main HEAD**(撰文时 `df5ca13`,在 `v1.1.0` 标签之后包含若干尚未发版的提交)。复制之后两个项目**各自演进**(允许漂移)。可接受的代价 —— 项目还小,bug 修复手动同步两份成本可控。

## 2. 非目标(YAGNI)

- **不**做 standalone 形态 —— 没有 `/api/login` 表单端点、没有登录框前端、不响应 Zimbra Web 之外的访问
- **不**做原生 Zimlet UI 重写(Dwt 控件) —— 仍走 iframe 内嵌自家 HTML 页面,工作量与 EOL 风险考量见原 Plan A 讨论
- **不**做 Java Server Extension(后端不进 mailboxd JVM)
- **不**做对核心导入功能的进一步加固或对真实 Zimbra 的端到端验证 —— 由运营方独立负责
- **不**和 ZImport(姊妹项目)共享代码包 —— 接受初始复制 + 各自演进

## 3. 总体架构

```
Zimbra Web (浏览器)
  └─ Zimlet:在应用栏注册「数据导入」页签
       └─ 页签内容 = <iframe src="/zimport-tools/">
              │  (同域名,浏览器自动带 Zimbra 的 ZM_AUTH_TOKEN cookie)
              ▼
   nginx 反代 ──> ZImport-tools web 进程 (127.0.0.1:8088)
                     └─ 读 ZM_AUTH_TOKEN cookie → 向 Zimbra 验一次 → 得知账户/管理员
                     └─ 之后:上传/入队/worker/进度 —— 与 ZImport 现有管线一致
```

**ZImport-tools 与 Zimbra 同域名是关键。** 反代必须把 ZImport-tools 挂在 Zimbra 自己的域名下(默认路径 `/zimport-tools/`),`ZM_AUTH_TOKEN` cookie 才会被浏览器自动带过来。

## 4. 仓库结构

新仓库 `ZImport-tools/` 的顶层(对照 ZImport 仓库,**去掉**了 standalone 形态的部分):

```
ZImport-tools/
├── README.md                      新仓库自己的 README
├── CHANGELOG.md                   独立版本线
├── requirements.txt               Flask 3.x / Werkzeug 3.x / requests / pytest
├── config.example.ini             配置模板(无 server.secret_key 之外的登录相关项)
├── zimport_tools/                 Python 包(注意是 zimport_tools,不是 zimport)
│   ├── __init__.py                __version__ = "1.0.0"
│   ├── config.py                  从 ZImport 复制
│   ├── archive.py                 从 ZImport 复制
│   ├── store.py                   从 ZImport 复制
│   ├── uploads.py                 从 ZImport 复制
│   ├── worker.py                  从 ZImport 复制(import 路径改名)
│   ├── zimbra_inject.py           从 ZImport 复制
│   ├── zimbra_folders.py          从 ZImport 复制
│   ├── zimbra_search.py           从 ZImport 复制
│   ├── zimbra_session.py          ★ 新增:cookie 校验 + 缓存(详见 §6)
│   ├── web.py                     ★ 重写:无 /api/login;cookie 认证 + CSRF
│   └── static/
│       ├── index.html             ★ 重写:无登录表单,启动直接调 /api/me
│       ├── app.js                 ★ 重写:无登录逻辑,所有 fetch 带 X-Zimport-CSRF 头
│       └── style.css              复用/精简
├── zimlet/                        ★ 新增:经典 Zimlet 包
│   ├── com_msauto_zimport_tools.xml   Zimlet 定义
│   ├── com_msauto_zimport_tools.js    注册应用页签,渲染 iframe
│   ├── com_msauto_zimport_tools.css   样式(iframe 撑满 view)
│   └── build.sh                   打包成 com_msauto_zimport_tools.zip
├── tests/                         单元测试(从 ZImport 复制核心管线测试,新增 zimbra_session/CSRF 测试)
├── deploy/                        ★ 适配:setup.sh / setup-proxy.sh / release.sh / systemd 单元
└── docs/                          复制 design.md / implementation-plan.md(可选)
```

**注意 Python 包名是 `zimport_tools`(不是 `zimport`)** —— 让两个项目在同一台机器上可以共存(同时安装、不冲突)。

**`zimbra_auth.py` 简化:** ZImport 现有的 `zimbra_auth.py` 包含 `login()`(用账号密码登录)与 `delegate_token()`/`_admin_token()`(服务账号委托)。ZImport-tools **去掉 `login()`**,只保留 `delegate_token()`/`_admin_token()`(worker 仍需要它们做服务账号注入)。

## 5. 数据流(端到端)

```
1. 登录 Zimbra Web                  浏览器持有 ZM_AUTH_TOKEN cookie
2. 点「数据导入」页签               Zimlet 切到自己的 view,渲染 iframe src=/zimport-tools/
3. iframe 加载 ZImport-tools 页面    浏览器自动带 ZM_AUTH_TOKEN
4. 前端调 GET /api/me               后端读 cookie → zimbra_session.validate →
                                    缓存未命中时调 Zimbra GetInfoRequest → 写正缓存 →
                                    写 Flask session → 返回 {account, is_admin}
5. 前端直接显示导入界面             不出登录框(管理员看到目标账户选项,普通用户看不到)
6. 选文件/文件夹/账户 → 点开始     /api/upload/init → /api/upload/chunk×N → /api/import
                                    每个 POST 都带 X-Zimport-CSRF 头;
                                    后端校验 header + Origin + session
7. 入队 → 返回 task_id              store.create_task
8. worker 异步处理                  archive.normalize → zimbra_auth.delegate_token →
                                    inject_eml/inject_tgz → 持久化进度
9. 前端轮询 /api/tasks/<id>         看进度;关 iframe / 关 Zimbra Web,任务继续跑
```

## 6. 认证(cookie-only)

### 6.1 单次请求决策

```
1. Flask before_request 钩子:
   a. session 已有 account 且 cookie token-hash 与 session 记录一致?  → 直通
   b. 否则,看请求有没有 ZM_AUTH_TOKEN cookie?
        无    → 401(对外这就是"未登录,请回 Zimbra Web 重登")
        有    → 走 cookie 验证
2. zimbra_session.validate(token):
   先查内存缓存(正缓存 5min、负缓存 30s,LRU 上限 1024)
   未命中 → 向 Zimbra SOAP 8443 发 GetInfoRequest,Header.context.authToken = 该 token
     响应给出账户名;zimbraIsAdminAccount 属性给出管理员身份
   成功   → 写正缓存,返回 Identity(is_admin, account)
   失败   → 写负缓存,抛 AuthError
   网络不可达 → 抛 ZimbraUnreachable(不写缓存)
3. 把 Identity 写入 Flask session(account, is_admin, token_hash)
```

### 6.2 三项关键决策

**(1) 验证缓存 —— 对服务器负责。**
分片上传可能高频(>5GB 按 10MB 分片即 500 次请求);不可能每片都问一次 Zimbra。
正缓存 5min + 负缓存 30s,既挡住 QPS 压力,也挡住攻击者用错误 token 反复试探拖垮 Zimbra。

**(2) `GetInfoRequest` 推导身份,不重新走密码认证。**
ZImport-tools 看不到也不该看到密码。`GetInfoRequest` 接受任意有效 Zimbra auth token,返回账户名与属性(含 `zimbraIsAdminAccount`)。

**关键澄清:** 用户的 `ZM_AUTH_TOKEN` 是从 Zimbra Web UI 登录拿到的**普通账户 token**,即使账户被标记为管理员,这个 token **不带 admin SOAP 权限**(只有走 admin 端口 7071 登录才会拿到 admin token)。所以 cookie 认证只用来**识别用户是谁、是不是 admin**;**所有真正需要管理员 SOAP 权限的操作**(`SearchDirectoryRequest`、`DelegateAuthRequest` 等)**统一走 ZImport-tools 自己的服务账号**(`cfg.svc_name`/`cfg.svc_password`,从 ZImport 配置继承)。**用户身份做授权决策、服务账号做 SOAP 调用**,两件事各司其职。

**(3) 账户切换串号防护 —— 对邮件导入质量负责。**
用户在 Zimbra Web 切到另一个账户后 `ZM_AUTH_TOKEN` 会变。
- session 里保存"建立此 session 时所用 cookie token 的 hash"(只存 hash,不存原 token)
- 每个请求比对 session token hash 与当前 cookie hash;不一致 → 静默清掉 session 重走验证
- 杜绝"以新账户身份点进来,却用了旧账户的会话权限"

## 7. CSRF 防护

ZImport-tools 完全靠 cookie 认证 —— 只要用户在 Zimbra Web 里登录着,任何打开恶意页面的浏览器都会自动把 `ZM_AUTH_TOKEN` 带到 ZImport-tools 同域名的请求里。这是必须严肃应对的 CSRF 场景。

### 两道闸(状态变更端点)

适用端点:`POST /api/import`、`POST /api/upload/*`、`POST /api/tasks/<id>/retry`、`POST /api/logout`。

**(1) 自定义 header —— 主防线**
- 端点要求 `X-Zimport-CSRF: 1` 头;缺则 403
- 浏览器**简单跨站请求**(普通 `<form>`、`<img>`、不带自定义头的 fetch)发不出自定义头
- 能发自定义头的跨站 `fetch`/XHR 触发 CORS 预检 → ZImport-tools 不配 CORS、不响应预检 → 浏览器拦下
- 自家 `app.js` 给所有 fetch 加这个头

**(2) `Origin` 头校验 —— 兜底闸**
- 状态变更请求要求 `Origin` 等于 ZImport-tools 自己的 host(允许列表来自配置)
- 不匹配返 403。`Origin` 是浏览器写的,网页改不了

只读端点(`GET /api/tasks`、`/api/me`)不强制此两闸:即便绕过,攻击者只能"看",不能"触发"动作。

### Flask session cookie 加固

显式 `SameSite=Lax`、`Secure`、`HttpOnly`。

## 8. "对任务/服务器/质量负责"

**对任务负责** —— 同 ZImport 现有管线一致,可恢复、可重试、进度持久化。Zimbra 会话过期不影响后台任务(worker 不依赖 web 端会话)。

**对服务器负责** —— token 验证缓存挡 QPS;CSRF 双闸挡滥用;账户切换防串号;现有的上传大小、队列长度、单任务上限继续生效。

**对邮件导入质量负责** —— 归一化、Message-ID 双层去重、文件夹保真,所有质量机制都从 ZImport 现有管线继承。账户绑定以 token 为准、不信任前端:管理员若指定目标账户,后端仍按属性校验当前用户是 admin,否则强制改写为本人。**验收准绳:** 实测从 Zimlet 内导入一封 eml,登目标账户 Zimbra Web 看到邮件、主题与文件夹正确。

## 9. 错误处理

| 场景 | 状态码 | 行为 |
|---|---|---|
| 无 cookie | 401 | 前端显示"请回到 Zimbra Web 登录"提示 + 重试按钮(没有 fallback 登录框) |
| cookie 已过期 / 已吊销 | 401(负缓存 30s) | 同上 |
| Zimbra 不可达 | 503 | 前端显示"Zimbra 暂不可达,请稍后",**不**显示"请登录"提示 |
| CSRF 头缺失 | 403 | 不暴露细节;前端报"非法请求来源"并刷新页面 |
| Origin 不匹配 | 403 | 同上 |
| 账户切换(token-hash 不一致) | (无错误) | 静默清 session 重新验证,前端透明 |
| token 验证缓存满 | (无错误) | LRU 淘汰最旧 |

**原则:** 错误信息对用户友好、对攻击者吝啬;不返回 Zimbra 内部错误细节;不区分"用户不存在"和"密码错"。

## 10. 测试策略

| 层级 | 用例 |
|---|---|
| 单元 · `zimbra_session.validate` | 有效 token → Identity(account 正确,is_admin 正确读自属性);无效 token → AuthError;Zimbra 不可达 → ZimbraUnreachable(区别于 AuthError) |
| 单元 · 缓存 | 二次相同 token 不打 Zimbra;TTL 到期重新打;负缓存 30s 内不重复打;LRU 满淘汰最旧 |
| 单元 · 账户切换 | session=A 的 token-hash + 请求带 B 的 token → session 被清并重建为 B;A 不残留 |
| 单元 · CSRF | 缺 X-Zimport-CSRF → 403;Origin 不匹配 → 403;只读端点不强制;两条满足 → 通过 |
| 单元 · 端点路径 | `/api/me` 返回 `{account, is_admin}`;`/api/login` 端点**不存在**(确认被显式移除) |
| 单元 · 复制自 ZImport 的管线 | `archive`、`store`、`uploads`、`worker`、`zimbra_inject` 的现有测试全部继承并通过 |
| 集成 · 真实 Zimbra(`ZIMBRA_IT=1` 跳过开关) | 用真实 ZM_AUTH_TOKEN 给 ZImport-tools 发请求 → 能识别身份;管理员 token → `is_admin=true` |
| 手工验收 | 部署 Zimlet → 登 Zimbra Web → 点页签 → iframe 加载且**不出任何登录界面** → 导一封 eml → 登目标账户 webmail 看到邮件,主题/文件夹正确 |

## 11. 部署与回滚

### 11.1 部署顺序

1. **新建 GitHub 仓库** `jiulin-hou/ZImport-tools`(user 手工建空仓,加 deploy key)
2. **本地构造初始代码 + push** `v1.0.0` 与第一个 release 包
3. **在 Zimbra 服务器上部署**:
   - `bash deploy/setup.sh` —— 复用 ZImport 的环境准备脚本(Python 3.11 + venv + 服务账号 + systemd)
   - `bash deploy/setup-proxy.sh --path /zimport-tools` —— Zimbra nginx 把 `/zimport-tools/` 反代到 127.0.0.1:8088
4. **部署 Zimlet**:zimbra 用户执行 `zmzimletctl deploy com_msauto_zimport_tools.zip`,Zimbra Web 自动出现新页签
5. **验收**:管理员账户点页签 → 进 + 导;普通账户点页签 → 进 + 只导自己

### 11.2 回滚(每层独立)

| 出问题层 | 回滚 | 副作用 |
|---|---|---|
| Zimlet | `zmzimletctl undeploy com_msauto_zimport_tools` | 页签消失,后端服务还在跑(但不再有正常入口);姊妹项目 ZImport(若已部署)不受影响 |
| 反代路径 | 撤掉 `/zimport-tools/` location | 后端仍跑,但浏览器进不来 |
| 后端 | `git checkout <上一 tag> && systemctl restart zimport-tools-*` | 退回上一版本;ZImport(若已部署)不受影响 |

**三层独立可回滚是这套设计的安全网。**

## 12. 版本与发布

- ZImport-tools 有**自己的版本号**,从 `v1.0.0` 起;**不**与 ZImport 同步
- 在 `zimport_tools/__init__.py` 维护 `__version__`
- 在 `CHANGELOG.md` 顶部维护版本记录
- `deploy/release.sh` 从 ZImport 复制并适配(改 tag 前缀、改包路径、改包名 `zimport-tools-X.Y.Z.tar.gz`)
- 发版流程:编辑 CHANGELOG → `bash deploy/release.sh X.Y.Z` → 自动跑测试、写版本号、提交、打 tag、推送、生成交付包

## 13. 待实现计划阶段细化

- 经典 Zimbra 8.8.15 Zimlet 注册顶层应用页签的具体 API(`ZmApp` / `ZmZimletApp` / `ZmAppChooser`)与依赖项,以实际框架文档与一次最小可跑 demo 为准
- `GetInfoRequest` 响应中 `zimbraIsAdminAccount` 的实际字段路径,以真实 Zimbra 响应为准
- iframe 被 Zimbra Web 嵌入时是否需要 `X-Frame-Options: SAMEORIGIN` / `Content-Security-Policy: frame-ancestors` 的具体配置
- nginx 把 `/zimport-tools/` 反代到 127.0.0.1:8088 时的具体 location 块、与 Zimbra 自身 `/service/*`、`/zimbra/*` 不冲突的写法
- token 验证缓存的具体 LRU 容量上限(建议 1024 可配)
- `setup.sh` 在 ZImport-tools 仓库里如何识别自己的目录名 / 服务名(避免和 ZImport 装在同台机器时冲突)

## 14. 后续(超出本次范围)

- 平台升级到 Zimbra 9 / 10 或 Carbonio 后,经典 Zimlet 框架不再适用;届时基于新版 Zimlet 框架重做 UI 入口(后端逻辑可继续沿用)
- 与 ZImport 之间的代码差异管理:若两边出现共同的核心 bug 修复,人工同步;若长期差异加大,考虑抽取共享核心包
