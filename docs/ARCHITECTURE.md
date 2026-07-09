# 听风（Cortex）上线路线图 & 技术架构

> 分支：`feat/go-live` ｜ 最后更新：2026-07-09
>
> 这是"从单机工具到上线产品"的技术文档。
> 商业定位见 `docs/PRODUCT.md`，本文专注**实现路径、架构决策、分阶段任务**。

---

## 0. 原则

1. **技术栈不动**：Python(FastAPI) 后端 + React(TS) 前端。AI 写代码，两种语言不是负担，重写才是。
2. **公网化第一门槛 = 默认全锁**：上线第一步不是"能登录"，而是"所有非白名单 API 默认要求登录，重成本操作不裸奔"。
3. **API 权限靠"owner 反查路径"定义，不靠"group 当万能边界"**：每个接口必须写清怎么从入参 id 反查到 owner，查不到就拒。
4. **数据分三层**：全局原始素材、用户订阅关系、用户分析产物，边界必须明确。
5. **能假就假，不阻塞**：短信验证码写死 0000，支付先手动转账。先把闭环跑起来。

---

## 1. 现状基线

经前后端审计，现状是**单机工具，零多用户基础设施**。

| 上线必需 | 现状 | 缺口 |
|---------|------|------|
| 安全（默认锁死） | 🔴 全部 11 个 router 裸奔，`/api/config` 可读写密钥 | **红线，最先做** |
| 用户/认证 | ❌ 无 User 表、无登录 | 全无 |
| 多租户（数据隔离） | ❌ 所有表无 owner_id | 全无 |
| 访问控制 | ❌ 所有 API 无 Depends 校验 | 全无 |
| 落地页 | ❌ 访客直接掉进 Dashboard | 全无 |
| 订阅/计费 | ❌ 无 | 全无 |
| 管理员后台 | ❌ 无 | 全无 |

**关键事实（审计核实）**：
- `report.py:33` `get_report(report_id)` 直接按 id 查，无 owner 反查。
- `tasks.py:24` `list_tasks` 返回全局所有任务。
- `contents.py:30` `get_transcript(content_id)` 全局查转录，任何 content_id 都能读。
- `groups.py:157` `run_group` 裸奔触发 ingest，直接烧 TikHub/LLM。
- `schema.py:87` Source 是 `(group_id, platform, identifier)` 唯一；`schema.py:208` ContentItem 是 `(source_id, content_id)` 唯一。**当前模型各 group 各采各的，不存在跨用户共享采集。**

---

## 2. 关键技术决策（已锁定）

### 2.1 认证
**手机号 + 验证码登录，验证码开发期写死 `0000`；自助注册默认关闭。**

- 前端：注册/登录 UI 一次建成最终形态。
- 后端：验证码校验函数现在校验输入 == "0000"。
- 公网默认不开放任意手机号注册：必须显式 `ALLOW_PUBLIC_REGISTER=true`、`AUTH_DEV_MODE=true`，或配置 `REGISTER_INVITE_CODE`。
- 以后接真短信：只改后端发码+校验逻辑，前端不动。

### 2.2 会话管理
**JWT（无状态），放 localStorage。**

- 登录签 JWT，前端存 localStorage，请求带 `Authorization: Bearer <token>`。
- **风险与收口策略（必须写进代码注释）**：
  - 用**短 TTL**（如 7 天），不要长期 token。
  - 后续引入第三方内容渲染/Markdown 时，上 **CSP** 防 XSS。
  - 一旦产品里渲染用户提交或第三方 Markdown，localStorage 的 XSS 影响面是账户级，届时迁移到 **httpOnly cookie + refresh token**。
  - 当前阶段可接受，因为不渲染不受信内容。但这是已知债，记着。

### 2.3 多租户数据模型
**三层边界（修正评审指出的"全局共享不成立"问题）**：

> ⚠️ **架构前提修正**：之前文档把"多用户盯同一博主、内容只采一次"当成已成立的架构前提。**这是错的**——当前 Source 和 ContentItem 都是按 source（挂在 group 下）唯一，两个用户盯同一博主各采一份，没有共享。是否要做全局内容缓存，是一个独立的架构决策（见 2.6），不能默认它已成立。

**当前阶段（最小改动，先上线）**：
- 给 `knowledge_groups` 加 `owner_id` → 所有 group 相关接口注入 current_user。
- **slug 唯一性必须改**（见下）。
- 所有非 group 入口接口（reports/tasks/contents/signals），通过其关联的 group_id 反查 owner。
- **当前不做全局内容共享**，承认各 group 各采各的。成本结构按"不共享"算。

#### slug 唯一性问题（评审指出）
当前 `KnowledgeGroup.slug` 是**全局唯一**（`schema.py:34`）。上线后 A 创建 `wechat-shop`，B 不能建同名，且冲突会暴露别人用过什么 slug。

**解决**：slug 改为 `(owner_id, slug)` 联合唯一。**目录命名改用 group_id 而非 slug**（见 2.7），彻底解耦目录唯一性和 slug 显示用途。

### 2.4 计费
**先手动转账，人工开通。100 人以内不接支付。**
- User 表预留 `plan` + `expires_at`。
- 用户转账 → 管理员后台改 `expires_at` → 开通。

### 2.5 默认锁死策略（公网化第一门槛）
**先做全局保护白名单，再做精细授权。**
- 公开只留：`/api/auth/*`、`/api/health`、静态资源。
- 其他**默认要求登录**（全局 `get_current_user` 依赖）。
- 登录之上再分：owner 校验（只能操作自己的）、admin（/config、/admin/*）、system（scheduler）。

### 2.6 共享采集（决策 A：已定 X，进上线前范围）

> ✅ **已决策：共享采集进入上线前范围。**
> 理由：电商垂类信源高度重叠，前 100 人大概率盯同一批博主。
> 各采各的会导致 ASR/采集成本乘以用户数，¥399 毛利撑不住，商业模型不成立。

**改造方向：两层模型——全局内容资产 + 用户订阅关系。**

当前：`Source(group_id, platform, identifier)` 各 group 各采各，`ContentItem(source_id, content_id)` 按 source 隔离。

改造后：
- **全局内容层**（采一次、转录一次、谁都能读）：
  - 博主账号（Creator + CreatorAlias）：已是全局，✅ 不用改。
  - 内容条目（视频元数据 + 转录 + 评论 + 媒体文件）：从"按 source 隔离"改为"全局唯一，按 `(platform, content_id)`"。采一次，所有订阅该博主的人共享。
- **用户订阅层**（谁订了谁，各用户独立）：
  - `Source` 从"采集单元"变为"订阅关系"——用户 A 订阅博主 X = 一条订阅记录，不再独占一份采集。
  - 分析产物（Signal、Report、AskConversation）：保持 group 级，各用户各自的。

**核心改动清单**：
1. `ContentItem` 去掉 `source_id` 唯一约束，改为 `(platform, content_id)` 全局唯一。source_id 降级为"哪些 source 发现了它"的多对多关系（或去掉，因为采集不绑 source 了）。
2. 采集调度去重：scheduler 发现博主 X 已在近 N 小时内采过，跳过重复采集，直接复用全局内容。
3. `ContentCache` 改为 `(platform, content_id)` 键（配合 3.2 的修正）。
4. 转录/评论/媒体文件：从 `data/{group}/{source}/` 改为全局存储 `data/{platform}/{creator_or_content}/`，采一份。
5. 采集成本真正摊薄：100 个用户盯同一个博主 = 采 1 次转录 1 次。

**这是上线前最大的单项工程**，但它直接决定单位经济能否成立。在认证/多租户之前或之后做均可（逻辑独立），但必须在上线前完成。

### 2.7 slug 目录迁移（路线①已定）

> ✅ **已决策：路线①，目录改用 group_id。**

slug 渗透的路径（全部依赖 `group.slug` 做目录名）：
- `data/{group.slug}/{source_slug}/` — 采集产物（paths.py:4）
- `knowledge/{group.slug}/` — 报告（paths.py:5, knowledge_service.py:104,538）
- `source_service.py:60` `directory = f"{group.slug}/..."` — source 创建时写入
- CLI 按 slug 查 group（commands.py）

**改造**：
- 目录从 `data/{group.slug}/...` 改为 `data/{group.id}/...`，`knowledge/{group.slug}/` 改为 `knowledge/{group.id}/`。
- slug 退化为纯显示/URL 字段，仅做 `(owner_id, slug)` 联合唯一校验。
- 一次性 migration 脚本：遍历所有 source，把 `Source.directory` 字段里的 slug 前缀换成 group_id 前缀，并 mv 对应物理目录。
- CLI 按 slug 查 group（`get_by_slug`）改为按 id 查，或保留 slug 查但加 owner 限定。

> **注意与 2.6 的联动**：如果共享采集（2.6）落地，采集产物从 `data/{group}/{source}/` 变成全局存储，则 slug 目录迁移只影响"报告"路径（`knowledge/{group.id}/`），采集侧的目录迁移被 2.6 吸收了。两个改动有重叠，实现时统筹。

### 2.7 slug 目录迁移（评审指出，改动面比想象大）

> ⚠️ slug 不是个字段问题，是**文件系统目录地基**。

slug 渗透的路径（全部依赖 `group.slug` 做目录名）：
- `data/{group.slug}/{source_slug}/` — 采集产物（paths.py:4）
- `knowledge/{group.slug}/` — 报告（paths.py:5, knowledge_service.py:104,538）
- `source_service.py:60` `directory = f"{group.slug}/..."` — source 创建时写入
- CLI 按 slug 查 group（commands.py）

**改 `(owner_id, slug)` 联合唯一，有两条路：**

- **路线 ①：目录改用 group_id，不用 slug。**
  - `data/{group.id}/{source.id}/`、`knowledge/{group.id}/`。
  - 彻底消除 slug 目录唯一性问题，slug 退化为纯显示字段（仅做 `(owner_id, slug)` 唯一校验）。
  - **代价**：历史数据要迁移（rename 目录：`data/{old_slug}/` → `data/{group_id}/`），或保留旧路径靠 Source.directory 字段兼容（该字段已存在，记录相对路径）。
- **路线 ②：目录拼 `owner_id/slug`。**
  - `data/{owner_id}/{slug}/`。
  - 代价：同样要迁移历史目录；且 owner_id 变了（用户删号迁移）目录又要动。

**建议选路线 ①**：目录用 group_id（稳定、不变），slug 只管显示和 URL。Source.directory 字段已存在，迁移时只需批量更新该字段的值（把 slug 前缀换成 group_id 前缀），并 mv 对应目录。这是一次性 migration 脚本的事。

---

## 3. 核心架构：三张矩阵（评审建议采纳）

### 3.1 API 权限矩阵

每个接口写明：**层级 + owner 反查路径**。

| 层级 | 含义 |
|------|------|
| public | 无需登录 |
| user | 需登录，不涉及特定 owner 资源（如 /api/me） |
| owner | 需登录 + 证明资源属于自己 |
| admin | 需管理员 |
| system | 系统任务（scheduler），非用户请求 |

#### 现有接口归类（owner 反查路径）

| 接口 | 层级 | owner 反查路径 |
|------|------|----------------|
| `POST /api/auth/code` | public | — |
| `POST /api/auth/register` | public | —（默认未开放注册，需开发模式/公开注册/邀请码） |
| `POST /api/auth/login` | public | — |
| `GET /api/health` | public | — |
| `GET /api/me` | user | — |
| `GET /api/groups` | owner | list 过滤 owner_id = current |
| `GET /api/groups/summary` | owner | 同上 |
| `POST /api/groups` | owner | 创建时填 owner_id = current |
| `GET/PATCH/DELETE /api/groups/{gid}` | owner | group.owner_id == current |
| `POST /api/groups/{gid}/run` | owner | group.owner_id == current **+ 订阅未过期** |
| `POST /api/groups/{gid}/analyze` | owner | group.owner_id == current **+ 订阅未过期** |
| `.../sources` CRUD | owner | source→group.owner_id == current |
| `.../sources/{sid}/run` | owner | source→group.owner_id == current **+ 订阅未过期** |
| `POST .../research` | owner | group.owner_id == current **+ 订阅未过期** |
| `GET .../reports` (by group) | owner | group.owner_id == current |
| `GET /api/reports/recent` | owner | **必须改为按 current 的 group 过滤**（当前返回全局，是漏洞） |
| `GET /api/reports/{id}` | owner | report→group.owner_id == current |
| `GET /api/reports/{id}/download` | owner | report→group.owner_id == current |
| `GET /api/tasks` | owner | **必须改为按 current 的 group 过滤**（当前返回全局） |
| `GET /api/tasks/{id}` | owner | task→group.owner_id == current |
| `POST /api/tasks/{id}/cancel` | owner | task→group.owner_id == current |
| `GET /api/contents/{cid}/transcript` | owner | **需加归属校验**：content_item→source→group.owner_id == current。当前裸查，需改 |
| `GET /api/signals/recent` | owner | **必须改为按 current 的 group 过滤** |
| `GET .../signals` (by group) | owner | group.owner_id == current |
| `GET .../insights` | owner | group.owner_id == current |
| `GET .../creators` 系列 | owner | 经 source/group 反查 |
| `.../ask` 系列 | owner | conversation→group.owner_id == current |
| `GET /api/platforms` | user | 只读元数据，登录即可 |
| `GET /api/config` | admin | 非 admin → 403 |
| `PATCH /api/config` | admin | 非 admin → 403 |
| `GET /api/config/prompts` | admin | 非 admin → 403 |
| `PATCH /api/config/prompts/{name}` | admin | 非 admin → 403 |
| `POST /api/scheduler/reload` | admin | 非 admin → 403 |
| `GET /api/scheduler/jobs` | admin | 非 admin → 403 |

> **标记"必须改"的 4 个接口是当前的安全漏洞**：它们返回全局数据或裸查，上线前必须加 owner 过滤/反查。

#### owner 反查的实现方式
- **group 直接接口**：`GroupRepo` 加 `owner_id` 字段，所有 list/get 校验 owner。
- **group 下挂资源（source/report/signal/task/ask）**：通过 `group_id` FK → `group.owner_id` 反查。封装一个 `assert_group_owner(gid, user)` 辅助函数。
- **content_item**：通过 `source_id` → `source.group_id` → `group.owner_id`。`get_transcript` 需改造。
- **非 group 入口（reports/recent、tasks、signals/recent）**：list 查询必须 join 到 current user 的 group 集合。
- **空值失败关闭（评审指出）**：`report.group_id`、`task.group_id` 当前可空（`schema.py:136`、`schema.py:156`）。**无 group 归属的 task/report，普通用户不可见**——反查到 group_id 为 null 时，直接拒绝（403/404）。仅 admin 或迁移清理路径可访问。

### 3.2 数据边界矩阵

| 数据层 | 归属 | 隔离方式 | 当前状态 |
|--------|------|----------|---------|
| **全局内容资产**（媒体、转录、评论、ContentItem） | **系统级**（决策 A/X） | 按 `(platform, content_id)` 全局唯一，采一份共享 | ❌ 当前按 source 隔离，需改造（见 2.6） |
| **博主身份**（Creator、CreatorAlias） | 系统级 | 全局唯一，跨平台聚合 | ✅ 已是 |
| **用户订阅关系**（Group、Source） | **用户级** | owner_id；Source 从"采集单元"变"订阅记录" | ❌ 需加 owner_id + 重构 Source 语义 |
| **用户分析产物**（Report、Signal、AskConversation） | group 级（间接用户级） | group_id → owner_id | ⚠️ 表里有 group_id，但 owner 反查未实现 |
| **作者观点档案**（creator profile） | 系统级公共资产 | 全局 creator_id 共用一份（见下） | ✅ 已是，接口需校验 source 归属 |

#### ContentCache 必须加 platform 维度（评审指出）
当前 `ContentCache` 只按 `content_id` 全局扫（`cache.py:8` 注释明写"platform 目前不参与去重"，`cache.py:31` `rglob(f"*_{content_id}.txt")`）。现在已有抖音+视频号，多平台后不同平台可能 content_id 撞车，返回错误转录。

**解决**：缓存键改为 `(platform, content_id)`，文件路径加 platform 前缀。`GET /api/contents/{cid}/transcript` 也要带 platform 参数，且校验归属（见 3.1）。

#### 作者观点档案的边界必须明确（评审指出）
当前 `Creator` 是全局身份，profile 按 `creator_id` 全局存（`schema.py:48-52` 注释"同一博主多个组共用一份档案"，`creators.py:134` `paths.profile_path(src.creator_id)`）。多用户盯同一博主会**互相覆盖档案**。

**两个选项**：
- **A：档案是全局公共资产**——所有用户看同一份。理由：同一个博主的观点是客观事实，不需要每人一份。简单，但要接受"你生成的档案别人也能看到"。
- **B：档案改 group/source 级**——每个订阅关系独立维护档案。隔离干净，但同一博主生成多次，成本翻倍。

**建议选 A**（全局公共资产）：符合"事实只有一个"的逻辑，成本低。但 `GET .../profile` 接口仍需校验"这个 source 属于我"，只是档案内容本身全局共享。

### 3.3 上线阶段门槛（含共享采集，重新排序）

**两个并行前提必须在上线前完成：默认锁死（安全）+ 共享采集（单位经济）。**

| 阶段 | 收口标准（端到端真实路径） |
|------|---------------------------|
| **阶段 1：默认锁死** | 未登录访问任意非白名单接口 → 401；`/api/config` 非 admin → 403；`/api/groups/1/run` 未登录 → 401 |
| **阶段 2：认证** | 张三注册→登录→拿 token→GET /api/me 返回自己 |
| **阶段 3：多租户** | A 建专题 X；B 登录后 list 不到 X；B 直访 X 的任意接口（含 report/task/content）→ 403 |
| **阶段 4：共享采集（单位经济前提）** | A、B 各自订阅同一博主 X；scheduler 只采一次、转录一次；A 和 B 都能看到 X 的内容；成本不翻倍 |
| **阶段 5：落地页+转化** | 未登录看落地页→注册→引导建第一个专题 |
| **阶段 6：管理员后台** | 你能看用户列表、开通续费、全局概览 |
| **阶段 7：信号检测** | 见 PRODUCT.md 4.1 |

> **阶段 1-3（安全+多租户）和阶段 4（共享采集）逻辑独立，可并行。**
> 但都必须在"对外上线"前完成——阶段 1-3 防事故，阶段 4 防亏钱。

---

## 4. 身份模型（含 system actor）

评审指出：scheduler 是系统任务，不是用户请求，没有 current_user。必须定义 system actor。

### 4.1 Actor 类型

| Actor | 触发方 | 权限 |
|-------|--------|------|
| **user** | HTTP 请求（带 JWT） | 只能操作自己的 group 资源 |
| **admin** | HTTP 请求（带 JWT，role=admin） | 同 user + /config、/config/prompts、/scheduler、/admin/* |
| **system** | scheduler / 后台任务 | 能跑任何 enabled 的 group 的刷新；**不受订阅过期限制**（或按策略受）；任务结果归属该 group 的 owner |

### 4.2 scheduler 身份处理
- scheduler 触发的 ingest/research，不经过 HTTP `get_current_user`。
- 任务记录的 `owner` 归属：通过 task.group_id → group.owner_id 推断。
- **订阅过期 → 停止采集（已决策）**：scheduler 跳过所有 `owner` 订阅已过期的 group，不触发 ingest/research。理由：小生意不为过期用户白烧 TikHub/ASR/LLM 成本，成本控制优先于"续费后立刻有数据"的体验。
  - 判断依据：group → owner_id → user.expires_at（未过期才采）。
  - 续费后：用户下次手动触发或等下一次调度，从当前往前回采配置的 `days` 天（按现有 lookback 机制），不需要特殊处理。
  - 对付费用户公平：算力不被过期用户占用。

---

## 5. 数据模型变更

### 新增表
```python
class User:
    id: int (PK)
    phone: str (unique)
    nickname: str
    role: str  # "user" | "admin"
    plan: str  # "none" | "pro"
    expires_at: datetime | None
    created_at: datetime
```

### 修改表
```python
class KnowledgeGroup:
    + owner_id: int (FK -> user.id)
    # slug: 从全局唯一 → (owner_id, slug) 联合唯一
```

### Migration 回填方案（评审指出必须有）
- 现有 group/source/report/task 仍存在，`owner_id` 不能是非空 FK（否则迁移失败）。
- **方案**：migration 时创建一个默认 admin 用户（phone 由你在首次启动时配置），所有现存 group 的 `owner_id` 回填为该 admin。你的历史数据不会丢，且都归你。
- `owner_id` 字段设为 nullable，migration 先回填再考虑加 NOT NULL 约束。

---

## 6. 接口新增清单

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | /api/auth/code | public | 发验证码（桩，恒成功） |
| POST | /api/auth/register | public | 手机号+验证码注册（默认关闭，需开发模式/公开注册/邀请码） |
| POST | /api/auth/login | public | 手机号+验证码登录，返 JWT |
| GET | /api/me | user | 当前用户信息 |
| GET | /api/admin/users | admin | 用户列表 |
| PATCH | /api/admin/users/{id} | admin | 改 plan/expires_at |

### 现有接口改造（必做）
- 全部 11 router 加 `get_current_user` 依赖。
- 4 个"标记必须改"的接口加 owner 过滤（见 3.1）。
- `/api/contents/{cid}/transcript` 加归属校验 + 带 platform 参数。
- `/api/config`、`/api/config/prompts/*`、`/api/scheduler/*` 加 admin 校验。
- `KnowledgeGroup.slug` 从全局唯一改为 `(owner_id, slug)` 联合唯一。
- `ContentCache` 缓存键从 content_id 改为 `(platform, content_id)`。
- 作者档案（creator profile）边界：定为全局公共资产，但接口仍校验 source 归属。

---

## 7. 前端新增清单

| 文件 | 说明 |
|------|------|
| `src/pages/Login.tsx` | 注册/登录（合一） |
| `src/auth/AuthContext.tsx` | 登录态管理 |
| `src/auth/RequireAuth.tsx` | 路由守卫 |
| `src/api/client.ts` (改) | 加 Authorization header + 401 清 token 跳登录 |
| `src/pages/Landing.tsx` | 未登录首页（阶段 4） |
| `src/pages/Account.tsx` | 我的账户（阶段 4） |

---

## 8. 部署

当前：本地（FastAPI + Vite dev proxy）。
上线：
- 后端：FastAPI(uvicorn) + SQLite，VPS/云服务器。
- 前端：build 静态文件，FastAPI 或 Nginx 托管。
- 域名：aitingfeng.cn。
- **HTTPS 必上**（无 HTTPS，JWT 明文传=裸奔）。

---

## 9. 上线前必须拍板的决策

### 决策 A（最关键）：共享采集进不进上线前范围？（见 2.6）
- ✅ **已定：X，共享采集进上线前范围。** 毛利正常是商业模型的底线。

### 决策 B：slug 目录迁移走哪条路线？（见 2.7）
- ✅ **已定：路线①，目录改用 group_id。** slug 退化为显示字段。

## 10. 不阻塞上线，但记住

- [ ] 跑真实单位经济（决策 A 的输入：不管共享与否，都要先算出单用户月成本）
- [ ] 信号检测产品定义（A 主 B 辅，待确认）
- [ ] 接真短信服务时机
- [ ] JWT 迁 httpOnly cookie 的时机（2.2 已知债）

---

*本文档随实现进度更新。每完成一阶段，在 3.3 对应行标注 ✅ 和收口结果。*
