# ZImport · Zimbra Web 集成(Zimlet)— 设计文档

> **⚠️ 本文档已被取代,作为历史记录保留。**
>
> 设计经过讨论后改为「独立姊妹项目」形态,见
> [`2026-05-23-zimport-tools-design.md`](./2026-05-23-zimport-tools-design.md)。
> 主要差异:不再在 standalone ZImport 上加 Zimlet 模式(双认证并存),
> 改为另起仓库 `ZImport-tools`,只走 Zimbra cookie 认证、无登录回退。

| 项目 | 内容 |
|---|---|
| 文档日期 | 2026-05-23 |
| 集成目标 | Zimbra 8.8.15 FOSS @ `mail.msauto.com.cn` |
| 当前 ZImport 版本 | v1.1.0(独立 Web 工具,内网部署) |
| 状态 | 设计已确认,待写实现计划 |

---

## 1. 背景与目标

ZImport 当前是独立 Web 工具:浏览器打开页面 → 用户用 Zimbra 账号在 ZImport 自己的登录框填一次账号密码 → 导入。两个痛点:

- **重复登录:** 用户已经在 Zimbra Web 里登录着,ZImport 还要再登一次
- **暴露面与暴露顾虑:** ZImport 作为独立 Web 服务对外暴露会增加攻击面;如果纳入 Zimbra Web,它就和 Zimbra webmail 共用入口和会话,不新增公网攻击面

本设计把 ZImport 做成 Zimbra Web 里的一个内置应用页签(经典 Zimlet),走 Plan A:
**Zimlet 加页签 + iframe 内嵌现有 ZImport 页面 + ZImport 后端信任 Zimbra 的会话 cookie。**

**目标**

- 用户在 Zimbra Web 顶部应用栏看到「数据导入」页签,点进去**无需再次登录**
- 现有 ZImport 前后端、Python 管线(队列/去重/重试/归一化/进度)**全部保留**,Zimlet 只换入口
- 保持现有的可靠性与质量保证("对任务/服务器/质量负责"具体落点见 §6)

**非目标(YAGNI)**

- 不做原生 Zimlet UI 重写(8.8.15 经典 Zimlet 框架已 legacy,投资 EOL 平台不划算)
- 不删除现有 `/api/login` 表单登录 —— 它作为 Zimbra Web 之外直接访问 ZImport 的回退方式继续保留
- 不为 Zimbra 9/10 或 Carbonio 的新 Zimlet 框架做兼容(那时再针对新框架重做)
- 不做核心导入功能的进一步加固或对真实 Zimbra 的端到端验证(独立的工作项,由运营方负责)

---

## 2. 总体架构

```
Zimbra Web (浏览器)
  └─ Zimlet:在应用栏注册「数据导入」页签
       └─ 页签内容 = <iframe src="/zimport/">
              │  (同域名,浏览器自动带 Zimbra 的 ZM_AUTH_TOKEN cookie)
              ▼
   nginx 反代 ──> ZImport web 进程 (127.0.0.1:8088)
                     └─ 读 ZM_AUTH_TOKEN cookie → 向 Zimbra 验一次 → 得知账户/管理员身份
                     └─ 之后:上传/入队/worker/进度 —— 与现状一致
```

**ZImport 与 Zimbra 同域名是关键** —— 浏览器只会把 `ZM_AUTH_TOKEN` cookie 自动带给同一 host,反代必须把 ZImport 挂在 Zimbra 自己的域名下(如 `https://mail.msauto.com.cn/zimport/`)。

## 3. 组件分解

新增 / 改动:

| 组件 | 性质 | 职责 |
|---|---|---|
| `zimlet/` 包 | 新增 | 经典 Zimbra 8.8.15 Zimlet。注册应用页签;页签内容是指向 `/zimport/` 的 iframe。本体很薄,几乎不含业务逻辑。可打包成 `zimport-zimlet.zip` 用 `zmzimletctl deploy` 部署 |
| `zimport/zimbra_session.py` | 新增 | 校验 `ZM_AUTH_TOKEN` cookie(向 Zimbra SOAP 发 `GetInfoRequest`),得出 `Identity(is_admin, account)`;带 TTL 内存缓存(成功 5 分钟、失败 30 秒) |
| `zimport/web.py` | 改动 | `login_required` 扩展:无表单 session 时改用 cookie 验证自动建立 session;新增 CSRF 防护(自定义 header + Origin 检查);Flask session cookie 加 `SameSite=Lax`、`Secure`、`HttpOnly` |
| `zimport/static/app.js` | 改动 | 每个 API 请求自动带 `X-Zimport-CSRF: 1` 头;401 时同现状显示登录框(在 iframe 内 fallback) |
| `deploy/setup-proxy.sh` | 改动 | 反代脚本支持 `--path /zimport` 把 ZImport 挂在 Zimbra 同域名下;原有 `--port` 选项保留 |

**保持不变(零改动):** `archive.py`、`store.py`、`uploads.py`、`worker.py`、`zimbra_inject.py`、`zimbra_auth.py`、`zimbra_folders.py`、`zimbra_search.py`、`zimbra_inject.py`、整个任务管线。

## 4. 认证流程

### 4.1 单次请求的认证决策

```
1. Flask before_request 钩子:
   a. session 已有 account 且 token 与 cookie 一致?  → 已认证,直通
   b. 否则,看请求里有没有 ZM_AUTH_TOKEN cookie?
        无    → 401(对外这就是"未登录")
        有    → 走 cookie 验证
2. cookie 验证 zimbra_session.validate(token):
   先查内存缓存(token → Identity,正缓存 TTL 5 分钟、负缓存 TTL 30 秒)
   未命中 → 向 https://localhost:8443/service/soap 发 GetInfoRequest,
            Header.context.authToken = 该 token
       响应给出账户名,zimbraIsAdminAccount 属性给出管理员身份
   成功   → 写入正缓存,返回 Identity
   失败   → 写入负缓存,抛 AuthError
   网络不可达 → 抛 ZimbraUnreachable(不写缓存)
3. 把 Identity 写入 Flask session(account + is_admin),
   后续请求按现有 session 机制处理
```

### 4.2 三个关键决策与理由

**(1) 缓存有效 token —— 对服务器负责。**
分片上传可能高频(>5GB 文件按 10MB 分片即 500 次请求);不能每次都问 Zimbra。
- 正缓存 5 分钟:平衡新鲜度与 QPS
- 负缓存 30 秒:防止攻击者用错误 token 把 Zimbra 拖到 QPS 上限
- 内存实现(进程级 dict + LRU 上限,典型上限 1024 条),够用且不引入新依赖

**(2) 用 `GetInfoRequest` 推导身份,不重新走密码认证。**
ZImport 看不到也不该看到密码。`GetInfoRequest` 接受任意有效 Zimbra auth token,返回账户名与属性(含 `zimbraIsAdminAccount`)。
- 这与现有 `/api/login` 用账号密码做 admin/account 双登录探测**不同**:那里有密码,可以试两个端口;这里只有 token,直接从属性看管理员身份
- **关键澄清:** 用户的 `ZM_AUTH_TOKEN` 是从 Zimbra Web UI 登录拿到的**普通账户 token**,即使账户被标记为管理员,这个 token **不带 admin SOAP 权限**(只有走 admin 端口 7071 登录才会拿到 admin token)。所以 cookie 认证只是用来**识别用户是谁、是不是 admin**,**所有真正需要管理员 SOAP 权限的操作**(`SearchDirectoryRequest`、`DelegateAuthRequest` 等)**统一走 ZImport 已有的服务账号**(`cfg.svc_name`/`cfg.svc_password`,v1.0 起就有)。服务账号本身是 Zimbra admin,有能力做这些操作。这样:用户身份用来做**授权决策**(你是不是 admin、能不能指定他人账户),服务账号用来做**SOAP 调用**。两件事各司其职

**(3) 账户切换的串号防护 —— 对邮件导入质量负责。**
用户在 Zimbra Web 切到另一个账户后 `ZM_AUTH_TOKEN` 会变。如果 ZImport 仍用旧 session,就可能把新账户的导入操作记到旧账户名下。
- session 里同时保存"建立此 session 时所用的 cookie token"(只存 token 的 hash,不存原 token)
- 每个请求**先比对** session 里的 token hash 与当前 cookie 的 hash;不一致 → 静默清掉 session 重走第 1 步
- 这就杜绝了"以新身份点进来、却用了旧身份的会话权限"

### 4.3 与现有 `/api/login` 表单登录的关系

两套机制并存,优先级 cookie → 表单 session:

| 场景 | 路径 |
|---|---|
| 在 Zimbra Web 的 iframe 里 | 始终有 cookie → 走 cookie,用户看不到登录框 |
| Zimbra Web 之外直接访问 ZImport | 无 cookie → 401 → 前端显示登录框 → 表单登录 → 写 session → 后续按现状 |
| Zimbra 会话过期(cookie 失效) | iframe 里下一次请求 401 → 前端在 iframe 内显示登录框 → 用户重登 Zimbra(或在 ZImport 登录框直接登) |

## 5. CSRF 防护

### 5.1 为何这次必须做

引入 cookie 认证后,只要用户在 Zimbra Web 里登录着,任何打开恶意页面的浏览器都会自动把 `ZM_AUTH_TOKEN` 带到 ZImport 同域名的请求里(包括恶意页面里的 `<form action="https://mail.msauto.com.cn/zimport/api/import">` 自动提交)。

### 5.2 两道闸(状态变更端点)

适用端点:`POST /api/import`、`POST /api/upload/*`、`POST /api/tasks/<id>/retry`、`POST /api/logout`。

**(1) 自定义 header —— 主防线**
- 端点要求 `X-Zimport-CSRF: 1` 头;缺则 403。
- 浏览器**简单跨站请求**(普通 `<form>`、`<img>`、不带自定义头的 fetch)发不出自定义头
- 能发自定义头的跨站 `fetch`/XHR 会触发 CORS 预检 → 我们不配 CORS、不响应预检 → 浏览器拦下
- 自己的 `app.js` 给所有 fetch 加这个头(一行 `headers["X-Zimport-CSRF"]="1"`)

**(2) `Origin` 头校验 —— 兜底闸**
- 状态变更请求要求 `Origin` 等于 ZImport 自己的 host(允许列表来自配置,默认从 `cfg.rest_base` 推导)
- `Origin` 是浏览器写的,网页改不了

只读端点(`GET /api/tasks`、`GET /api/me`)不强制此两闸:即便绕过,攻击者只能"看"任务列表(认证仍要 token 有效),不能"触发"动作。

### 5.3 Flask session cookie 加固

显式设置:`SameSite=Lax`、`Secure`、`HttpOnly`。把表单登录路径上的同类风险也封住。

## 6. "对任务/服务器/质量负责" 的具体落点

**对任务负责(任务不丢、可追)**
- Zimlet 不引入新的任务路径 —— 仍走 `/api/import` → SQLite 队列 → worker,与现状一致
- 任务可恢复、可重试、进度持久化 —— 一行不动,直接继承
- iframe 内会话过期时,前端兜底回登录框,**不影响**正在跑的后台任务(worker 不依赖 web 端会话)

**对服务器负责(不压垮 Zimbra、不被滥用)**
- token 验证缓存(§4.2 (1))把高频上传分片可能造成的 Zimbra QPS 压力压到极低
- CSRF 双闸(§5.2)杜绝"任何 Zimbra 登录用户被诱导后变成代理写入通道"
- 账户切换串号防护(§4.2 (3))杜绝跨账户操作错位
- 现有的上传大小、队列长度、单任务上限护栏继续生效,Zimlet 不绕开任何一道

**对邮件导入质量负责(导进去的邮件是对的、不重复、不缺)**
- 归一化(`archive.normalize`)、去重(`Message-ID` 双层)、文件夹保真,**Zimlet 完全继承同一管线**
- 账户绑定以 token 为准、不信任前端:管理员若指定目标账户,后端仍按现有逻辑校验当前用户是管理员;不是则强制改写为本人
- **验收准绳:** 实测从 Zimlet 内导入一封 eml,登录目标账户的 Zimbra Web 看到那封邮件、主题与文件夹正确 —— "质量"以最终在 webmail 里能看到对的邮件为准,不只看任务表

## 7. 数据流

```
1. 登录 Zimbra Web                  浏览器持有 ZM_AUTH_TOKEN cookie
2. 点「数据导入」页签               Zimlet 切到自己的 view,渲染 iframe src=/zimport/
3. iframe 加载 ZImport 页面         浏览器自动带 ZM_AUTH_TOKEN 给 /zimport/
4. 前端调 GET /api/me               后端读 cookie → zimbra_session.validate → 缓存未命中 →
                                    GetInfoRequest → 写正缓存 → 写 Flask session → 返回身份
5. 前端显示导入界面(管理员看到目标账户输入,普通用户看不到)
6. 用户选文件 / 选目标文件夹 / 点开始导入
7. 前端走 /api/upload/init → /api/upload/chunk×N → /api/import
   每个 POST 都带 X-Zimport-CSRF 头;后端校验 header + Origin + session
8. 后端 store.create_task 入队,返回 task_id
9. worker 异步处理:archive.normalize → zimbra_auth.delegate_token → 注入 → 进度持久化
10. 前端轮询 /api/tasks/<id> 看进度;关 iframe / 关 Zimbra Web,任务继续跑
```

## 8. 错误处理

| 场景 | 状态码 | 行为 |
|---|---|---|
| 无 cookie 且无 session | 401 | 前端显示登录框 |
| cookie 已过期 / 已吊销 | 401(负缓存 30s) | 前端显示登录框 |
| Zimbra 不可达 | 503 | 前端显示"Zimbra 暂不可达,请稍后",**不显示登录框**(避免误导用户重输密码) |
| CSRF 头缺失 | 403 | 不暴露细节;前端报"非法请求来源"并刷新 |
| Origin 不匹配 | 403 | 同上 |
| 账户切换(token 与 session 不一致) | (无错误) | 静默清 session 重新验证,前端透明 |
| token 验证缓存满 | (无错误) | LRU 淘汰最旧 |

**原则:** 错误信息对用户友好、对攻击者吝啬;不返回 Zimbra 内部错误细节;不区分"用户不存在"和"密码错"。

## 9. 测试策略

| 层级 | 用例 |
|---|---|
| 单元 · `zimbra_session.validate` | 有效 token → Identity(account 正确,is_admin 正确读自属性);无效 token → AuthError;Zimbra 不可达 → ZimbraUnreachable(区别于 AuthError) |
| 单元 · 缓存 | 二次相同 token 不打 Zimbra;正缓存 TTL 到期后重新打;负缓存 30s 内不重复打;LRU 上限 |
| 单元 · 账户切换 | session=A 的 token-hash + 请求带 B 的 token → session 被清空并重建为 B;A 不残留 |
| 单元 · CSRF | 缺自定义 header → 403;Origin 不匹配 → 403;只读端点不强制;两条满足 → 通过 |
| 单元 · 端点路径 | `/api/me` 新端点行为;`login_required` 装饰器走 cookie 路径 |
| 集成 · 真实 Zimbra(`ZIMBRA_IT=1` 跳过开关) | 用真实 Zimbra 的 ZM_AUTH_TOKEN 给 ZImport 发请求 → 能识别身份;管理员账户的 token 应识别为 `is_admin=true` |
| 手工验收 | 部署 Zimlet → 登 Zimbra Web → 点页签 → iframe 加载且**不出登录框** → 导入一封 eml → 任务跑完 → 登目标账户 webmail 看到那封邮件、主题文件夹正确 |

预期新增单元测试 ~10 个,加在 `tests/test_zimbra_session.py` 与 `tests/test_web.py` 的 CSRF/account-switch 用例里。

## 10. 部署与回滚

### 10.1 部署顺序(顺序敏感)

1. **后端升级**(发新版本,含 `zimbra_session.py`、`web.py` 改动)。对 Zimbra Web 之外的现有用户无影响 —— `/api/login` 表单登录照常工作。
2. **反代调整**:`setup-proxy.sh --path /zimport`,把 ZImport 挂在 Zimbra 同域名下 `/zimport/`(`ZM_AUTH_TOKEN` 才会被自动带过来)。
3. **部署 Zimlet**:zimbra 用户执行 `zmzimletctl deploy zimport-zimlet.zip`。Zimbra Web 自动刷新出新页签。
4. **验收**:管理员账户点页签 → 进入 + 导入成功;普通账户点页签 → 进入 + 只能导自己。

### 10.2 回滚(每层独立)

| 出问题层 | 回滚 | 副作用 |
|---|---|---|
| Zimlet | `zmzimletctl undeploy com_msauto_zimport` | 页签消失,ZImport 独立站点仍可用 |
| 反代路径 | 撤掉 `/zimport/` location(`setup-proxy.sh --undeploy` 或手工) | 回到仅监听 127.0.0.1 + 表单登录 |
| 后端 | `git checkout v1.1.0 && systemctl restart zimport-*` | 退回上一版本,表单登录不变 |

**灰度可拆是这套设计的安全网。** 三层各自独立、每层都可单独回滚,任意一层出问题不影响另两层。

## 11. 待实现计划阶段细化

- 经典 Zimbra 8.8.15 Zimlet 注册应用页签的具体 API(`ZmApp` / `ZmZimletApp` / 顶级 tab 注册的确切调用方式),依实际框架文档定型
- `GetInfoRequest` 响应中 `zimbraIsAdminAccount` 属性的实际存在性与字段路径,以真实 Zimbra 响应为准
- nginx 反代 ZImport 在 Zimbra 同域名下时,Zimbra 自身的 `/service/*`、`/zimbra/*` 路径与 ZImport 的 `/zimport/*` 不冲突的具体配置形式
- iframe 内的 ZImport 页面是否需要额外的 `X-Frame-Options`/`Content-Security-Policy` 调整以允许被 Zimbra Web 嵌入(同域名嵌入默认应允许,需实测)
- token 验证缓存的具体 LRU 容量上限(默认建议 1024,可配)
- `/api/me` 端点的精确返回字段(目前 `{account, is_admin}`)
