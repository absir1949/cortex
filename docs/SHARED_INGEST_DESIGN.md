# 共享采集详细设计（阶段 4）

> 分支：`feat/go-live` ｜ 最后更新：2026-07-09
>
> 这是 ARCHITECTURE.md 2.6（决策 X）的落地设计。
> 基于 `app/` 代码的完整链路调研，不是拍脑袋。

---

## 0. 为什么写这份文档

共享采集是上线前最大的单项工程，且和多租户（owner 反查）深度耦合——
共享采集把 ContentItem 变全局资产，多租户要在"订阅关系"上做 owner 隔离。
**两者必须统筹设计，否则返工。** 本文档把"怎么改"写到表结构、迁移、调度、存储的级别。

---

## 1. 核心思想：内容与订阅分离

### 现状：内容绑定订阅
```
Group (owner)
 └─ Source (group_id, platform, identifier)   ← 采集单元
     └─ ContentItem (source_id, content_id)    ← 内容绑死在 source 上
         └─ 媒体/转录/评论 文件在 data/{group.slug}/{source}/
```
两个用户盯同一博主 = 各自一条 Source + 各自一份 ContentItem + 各自采一遍转录一遍。**成本乘用户数。**

### 目标：内容全局共享，订阅只记录关系

```
User
 └─ Group (owner_id)
     └─ Source/Subscription (group_id, creator_id | keyword)   ← 订阅关系，不拥有内容
         └─ SourceContent (source_id, global_content_id)       ← "这个订阅发现了哪些内容"

GlobalContent (platform, content_id)                          ← 全局内容资产，采一份
 └─ 媒体/转录/评论 在全局存储
 └─ media/transcript/comments/signal/profile 状态（全局）

Signal (global_content_id)                                    ← 信号，全局，挂全局内容
Profile (creator_id)                                          ← 观点档案，已全局（不变）
```

**为什么需要 SourceContent（评审指出的核心漏洞）**：
`Subscription(group_id, creator_id)` 只记录"订阅了谁"，但 keyword 场景必须记录
"这个 keyword/订阅发现了哪些全局内容"。否则：
- 专题报告不知道该消费哪些 GlobalContent；
- 增量水位（AnalyzedContent）无处记；
- 作者页无法区分"我订阅发现的"vs"全局存在的"。

`SourceContent` 就是"订阅 × 内容"的多对多关系表——它替代了旧 ContentItem 的"归属"作用，
但不再承载采集状态（采集状态归 GlobalContent，全局采一份）。

100 个用户盯同一博主 = 1 份 GlobalContent + 100 条 Subscription（各记各的 SourceContent）。**内容成本固定。**

---

## 2. 好消息：三处已经是全局的先例

调研发现，系统里**已有三处全局化的设计**，共享采集不是从零开始，而是推广已有模式：

| 先例 | 位置 | 为什么重要 |
|------|------|-----------|
| **adapter 返回的 Content 不含 source_id** | `app/platforms/base.py`、`models/content.py` | 采集边界天然 source-free，`Content` 只有 platform+content_id |
| **Creator 是全局身份** | `schema.py:48`、`creator_aliases` | 博主跨组全局唯一，Profile 已按 creator_id 全局存 |
| **ContentCache 按 content_id 全局读** | `storage/cache.py`、`api/contents.py` | `GET /contents/{cid}/transcript` 已经全局，ContentCache 已经 `rglob` 全局扫 |

**结论：共享采集的本质，是把 ContentItem、文件存储、调度这三块也变成全局的——让它们和 adapter/Creator/ContentCache 对齐。**

---

## 3. 数据模型变更

### 3.1 新增表：GlobalContent（全局内容资产）

```python
class GlobalContent(SQLModel, table=True):
    """全局内容资产——一个 platform+content_id 全局唯一，采一份，所有订阅者共享。

    吸收现有 ContentItem 的全部字段：内容元数据 + 完整采集状态（含 signal/profile）。
    """
    __tablename__ = "global_content"
    __table_args__ = (UniqueConstraint("platform", "content_id", name="uq_global_content"),)

    id: Optional[int] = Field(default=None, primary_key=True)   # ← 全局内容主键
    platform: str = Field(index=True)
    content_id: str = Field(index=True)
    creator_id: Optional[int] = Field(default=None, foreign_key="creators.id", index=True)

    # 内容元数据（从 Content / 现有 ContentItem 迁移）
    content_type: str = ""
    title: str = ""
    author_id: str = ""
    author_name: str = ""
    url: str = ""
    create_time: str = Field(default="", index=True)

    first_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # 采集状态（全局，采一次）—— 完整五阶段，吸收 ContentItem 全部状态
    media_status: str = Field(default="pending", index=True)
    transcript_status: str = Field(default="pending", index=True)
    comments_status: str = Field(default="pending", index=True)
    signal_status: str = Field(default="pending", index=True)
    profile_status: str = Field(default="pending", index=True)

    media_error: Optional[str] = None
    transcript_error: Optional[str] = None
    comments_error: Optional[str] = None
    signal_error: Optional[str] = None
    profile_error: Optional[str] = None

    file_size: int = 0
    statistics: dict = Field(default_factory=dict, sa_column=Column(JSON))
```

### 3.2 新增表：SourceContent（订阅×内容关系表）

```python
class SourceContent(SQLModel, table=True):
    """订阅 × 全局内容 的多对多关系。

    记录"这个订阅发现了哪些全局内容"。不承载水位（水位在 GroupContent，见 3.5）。
    """
    __tablename__ = "source_content"
    __table_args__ = (UniqueConstraint("source_id", "global_content_id", name="uq_source_content"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    global_content_id: int = Field(foreign_key="global_content.id", index=True)
    ingest_target_id: Optional[int] = Field(default=None, foreign_key="ingest_targets.id", index=True)
    # ↑ 关键字回填精确匹配用：按 ingest_target_id 查"该 keyword target 采过的内容"，不靠字符串防串平台

    matched_query: str = ""          # creator 类型为空；keyword 类型记录关键词（仅记录展示用）

    first_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
```

**用途**：keyword 发现记录（按 `ingest_target_id` 精确回填）、作者页内容列表、creator 详情。
**不用于报告水位**（防止重复消费，见 3.5 GroupContent）。

### 3.3 改造表：Source（语义：采集单元 → 订阅关系）

```python
class Source(SQLModel, table=True):
    """订阅关系：某 group 订阅了某 creator/keyword。不再独占内容采集。

    唯一键 (group_id, platform, identifier) 不变。
    采集参数保留为"订阅偏好"，实际采集由 IngestTarget 合并（见 3.6）。
    去掉 directory（迁移期兼容见第 7 节）。
    去掉 last_check/last_error（采集状态归 IngestTarget，见 3.6）。
    """
    # 保留：id, group_id, creator_id, type, platform, identifier, display_name,
    #       enabled, interval_hours, days, content_limit, comment_top_n, created_at
    # 删除：directory, last_check, last_error
```

### 3.4 改造表：Signal（挂 global_content_id）

```python
class Signal(SQLModel, table=True):
    """观点信号——全局：直接挂 global_content_id。"""
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("global_content_id", name="uq_signal_content"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    global_content_id: int = Field(foreign_key="global_content.id", index=True)
    creator_id: Optional[int] = Field(default=None, index=True)  # 冗余加速

    is_new: bool = Field(default=False, index=True)
    summary: str = ""
    matched_points: list = Field(default_factory=list, sa_column=Column(JSON))
    new_points: list = Field(default_factory=list, sa_column=Column(JSON))

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
```

### 3.5 新增表：GroupContent（专题级水位，评审指出防重复消费）

> 🔴 评审第 2 条：水位放 SourceContent 会导致 group 订阅 author+keyword 时同一内容重复消费。

```python
class GroupContent(SQLModel, table=True):
    """专题级：group × 全局内容 的水位。按 (group_id, global_content_id) 去重。

    解决：一个 group 订阅了同一 author 的 creator source + keyword source，
    同一 GlobalContent 会命中多条 SourceContent。报告水位必须按 group 去重，不能按 source。
    """
    __tablename__ = "group_content"
    __table_args__ = (UniqueConstraint("group_id", "global_content_id", name="uq_group_content"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="knowledge_groups.id", index=True)
    global_content_id: int = Field(foreign_key="global_content.id", index=True)

    first_seen_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    analyzed_at: Optional[str] = None  # NULL=未进报告；有值=已消费
```

**报告查询改为**：`GroupContent JOIN GlobalContent WHERE group_id=X AND analyzed_at IS NULL`
→ 天然按 (group_id, global_content_id) distinct，无论几个 source 发现的都只算一次。
**AnalyzedContent 删除**，被 GroupContent.analyzed_at 取代。

### 3.6 新增表：IngestTarget（采集目标，表化 + keyword 分离，评审指出）

> 🔴 评审第 1 条：keyword 不能并进 creator 级合并（两种 API 入口）。
> 🔴 评审第 3 条：没有持久化状态，调度无法去重和并发锁。

```python
class IngestTarget(SQLModel, table=True):
    """采集目标——调度的实际单元。creator 和 keyword 是两种 target。

    creator 订阅 → 按 creator 建一个 target。
    keyword 订阅 → 按 normalized query 建一个 target（同关键词多组订阅合并采一次）。
    """
    __tablename__ = "ingest_targets"
    __table_args__ = (
        UniqueConstraint("platform", "kind", "target_key", name="uq_ingest_target"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True)
    kind: str = Field(index=True)        # "creator" | "keyword"
    target_key: str = Field(index=True)  # creator: sec_uid；keyword: normalized query
    # ❌ 不设 creator_id 字段：keyword target 是 query，搜索返回多作者，没有单一 creator。
    #    creator 关联在 Source.creator_id 上；GlobalContent.creator_id 各条内容各自解析。

    enabled: bool = Field(default=True)  # 有无订阅：无订阅时置 False，scheduler 跳过；新订阅回来时重置 True

    # 合并后的采集参数（取所有订阅该 target 的 Source 的最激进值）
    interval_hours: int = 48
    days: int = 7
    content_limit: int = 50
    comment_top_n: int = 20

    # 持久化采集状态（调度依赖）
    last_check: Optional[str] = None       # 上次采集时间（判断 due）
    last_error: Optional[str] = None
    running_task_id: Optional[str] = None  # 并发锁：正在跑的任务
    locked_at: Optional[str] = None        # 加锁时间（防死锁超时清理）

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
```

**creator_id 归属（评审指出 keyword target 不能填 creator）**：
- creator target：通过 `target_key=sec_uid` → CreatorAlias → Creator 关联，不冗余存 creator_id。
- keyword target：**无 creator 关联**——它是一个 query，搜索返回多作者。
  搜索结果的每条内容各自解析 author_id → 写入各自的 `GlobalContent.creator_id`。
- IngestTarget 不需要 creator_id 字段，避免语义混乱。

**参数合并规则**（按 target 合并所有订阅 Source 的偏好）：

| 参数 | 合并规则 | 理由 |
|------|----------|------|
| `interval_hours` | **取最小值** | 最勤快的订阅者决定采集频率 |
| `days` | **取最大值** | 最长回看满足所有人 |
| `content_limit` | **取最大值** | 最多条数满足所有人 |
| `comment_top_n` | **取最大值** | 评论抓全了谁都能用 |

**keyword 与 creator 分离**（评审第 1 条）：
- creator target：`kind=creator, target_key=sec_uid`，调 `fetch_creator_content`。
- keyword target：`kind=keyword, target_key=query`，调 `search`。
- 搜索结果入库后，**每条内容各自**按 author 解析 creator_id 写入 GlobalContent + SourceContent。
- **两种 target 各自独立调度、各自合并参数，不混。**

**并发锁**：scheduler 采集前检查 `running_task_id`，非空则跳过（已被其他任务采）。超时（如 locked_at > 1 小时）自动释放（防死锁）。

### 3.7 保留表：KnowledgeGroup 加 owner_id（多租户，必须提前）

```python
class KnowledgeGroup:
    + owner_id: int (FK -> user.id)
    # slug: 全局唯一 → (owner_id, slug) 联合唯一
```

---

## 4. 存储层改造（最大改动面）

### 4.1 新的全局存储布局

```
data/{platform}/creators/{creator_id}/YYYY-MM-DD_{content_id}.mp4
data/{platform}/creators/{creator_id}/YYYY-MM-DD_{content_id}.txt      (转录)
data/{platform}/creators/{creator_id}/YYYY-MM-DD_{content_id}.json     (元数据)
data/{platform}/creators/{creator_id}/YYYY-MM-DD_{content_id}.comments.json
```

- 按 `platform/creator_id` 组织，一个博主的全部内容在一个目录，采一份。

**creator_id 为空时的兜底（评审第 4 条指出路径要求 creator_id 但它可空）**：
`Content.author_id` 可能为空（`content.py:45`），此时无法确定 creator_id。规则：
- **入库前必须解析出 Creator**：adapter 返回的 Content 若有 author_id，采集时立即创建/关联 Creator。
- **author_id 也为空的极端情况**：归档到 `data/{platform}/creators/_unknown/`，GlobalContent.creator_id 留空，存储路径用 `_unknown` 兜底。后续如果能补全 author（元数据更新），rehome 到正式 creator 目录。
- **统一路径规则**：`data/{platform}/creators/{owner_key}/`，其中 `owner_key = str(creator_id) if creator_id else "_unknown"`。只有一套路径，`_unknown` 作为 creators 下的特殊"虚拟博主"目录。

### 4.2 改造 paths.py

```python
def content_dir(platform: str, owner_key: str) -> Path:
    """owner_key = str(creator_id) 或 "_unknown"。统一用 str，避免 int/None 类型混乱。
    路径固定为 data/{platform}/creators/{owner_key}，_unknown 也在 creators 下，一套规则。"""
    return settings.data_dir / platform / "creators" / owner_key

def content_file(platform: str, owner_key: str, content_id: str, create_time: str, ext: str) -> Path:
    return content_dir(platform, owner_key) / content_filename(content_id, create_time, ext)

# knowledge 报告改为按 group_id
def knowledge_dir_for_group(group_id: int) -> Path:
    return settings.knowledge_dir / str(group_id)
```

> helper 统一用 `owner_key: str`（评审第 5 条指出 int 签名与 _unknown 冲突）。
> `_unknown` 和真实 creator_id 都在 `creators/` 下，一套路径规则，无特例。

### 4.3 改造 StorageManager → GlobalStorage

`StorageManager(source.directory)` → `GlobalStorage(platform, creator_id)`。

现有 `StorageManager` 的每个方法（exists/get_video/save_video/get_transcript/list_metadata...）
改成按 `(platform, creator_id)` 定位，而非 source.directory。

**API 层的连锁改造**（调研发现 API 全靠 `StorageManager(src.directory)` 读内容）：
- `api/sources.py:52` source summary → 改为查 GlobalContent by creator_id
- `api/groups.py:79` group summary → 同上
- `api/signals.py:52` 信号增强 → 从 GlobalContent 查 url/title
- `api/creators.py:60` 博主内容列表 → 查 GlobalContent by creator_id
- `knowledge_service.py:277,354` 报告/问答 → 查 GlobalContent

> **关键转变**：API 不再扫文件系统目录读内容，改为查 `global_content` 表。
> 这同时也消灭了"API 靠 glob 文件目录"的性能隐患——改成一个 SQL 查询。

### 4.4 ContentCache 改造

`ContentCache` 已经按 content_id 全局读（cache.py），只需加 platform 维度：
- 缓存键 `content_id` → `(platform, content_id)`
- glob 模式加 platform 前缀

---

## 5. 订阅生命周期：reconcile（评审指出，核心运行流程）

> 🔴 评审第 2、3 条：用户随时增删改订阅（`source_service.py:23/88/99`），
> 共享采集后这些操作必须触发 IngestTarget 重算、SourceContent/GroupContent 生成。
> 新订阅必须立即看到历史内容，不能等下次采集。

### 5.1 创建订阅 → `reconcile_new_subscription(source_id)`

用户新增一个 source（订阅某 creator 或 keyword），必须立即：

1. **关联/创建 IngestTarget，并确保 enabled**：
   - creator 订阅 → 找 `IngestTarget(kind=creator, platform, target_key=sec_uid)`，没有则建。
   - keyword 订阅 → 找 `IngestTarget(kind=keyword, platform, target_key=query)`，没有则建。
   - **若 target 已存在且 enabled=False（之前无订阅被停采），重置为 True**——重新激活采集。
2. **从已有 GlobalContent 回填历史**（评审第 3 条，关键体验）：
   - creator 订阅 → 查 `GlobalContent WHERE creator_id=X AND platform=Y`，为每条建 SourceContent（记 `ingest_target_id`）+ GroupContent。
   - keyword 订阅 → 查 `SourceContent WHERE ingest_target_id=该target.id`（精确匹配，不靠 matched_query 字符串，防串平台——评审指出），关联的 GlobalContent 回填到新 source。
   - **效果**：B 订阅一个已经被 A 采过的 creator，立即在专题里看到全部历史内容，不等采集。
3. **重算 IngestTarget 参数**：合并所有 enabled 订阅该 target 的 Source 偏好（取最激进值）。
4. **标记 GroupContent.analyzed_at = NULL**：回填的历史内容如果还没进过报告，下次报告会纳入。

> 这一步是"新订阅秒看到内容"的关键。没有它，用户订阅后会面对空专题，体验崩塌。

### 5.2 修改订阅参数 → `reconcile_target_params(target_id)`

用户改了某个 source 的 interval/days/comment_top_n：
- 重算该 source 所属 IngestTarget 的合并参数（取所有订阅 Source 的最激进值）。
- 不动 SourceContent/GroupContent（内容关系不变）。

### 5.3 删除/停用订阅 → `reconcile_target_after_unsubscribe(source_id)`

用户删了一个 source：
1. 删除该 source 的 SourceContent 记录。
2. **清理 GroupContent（评审指出不能无条件保留）**：对该 source 发现过的每条 global_content，检查该 group 下是否还有**其他** SourceContent 指向它。
   - 有其他 source 也发现了 → 保留 GroupContent（水位保持）。
   - 无其他 source 指向 → **删除该 GroupContent**（这条内容不再属于该专题，报告不会再纳入）。
3. 重算 IngestTarget 参数。如果该 target **已无任何 enabled 订阅**：
   - 置 `enabled=False`（不物理删，保留采集历史）。
   - scheduler 跳过（停采）。
   - 若之后有新订阅回来（5.1），重新 enable。

### 5.4 入口集成

`SourceService.create/update/delete`（现有入口）在原有逻辑后调用对应的 reconcile 函数。
reconcile 是轻量 DB 操作（建关系记录、重算参数），同步执行即可，不阻塞用户。

---

## 6. 采集调度改造（IngestTarget 级去重）

### 6.1 现状：per-group 调度
```
scheduler → 每 group 一个 job → IngestService.run_group → 遍历 sources → 逐个 refresh_source → 采集
```

### 6.2 目标：IngestTarget 级去重调度

核心改变：**同一个 target（creator 或 keyword），不管被几个 group 订阅，只采一次。**

```
scheduler 触发
  → 查所有 enabled IngestTarget WHERE due（now - last_check >= interval_hours）
  → 对每个 due target（并发锁检查 running_task_id）：
      → creator target: fetch_creator_content(target_key)
      → keyword target: search(target_key)
      → 对返回的 Content，按 (platform, content_id) 查 GlobalContent：
          已存在 → 跳过采集，补 SourceContent（若有新订阅）
          不存在 → 采集：下载/转录/评论 → 写 GlobalContent
      → 为每个订阅该 target 的 source 建/更新 SourceContent + GroupContent
  → 各 group 的分析/报告各自跑（消费全局内容 via GroupContent）
```

### 6.3 调度逻辑重构（cron.py + ingest_service）

- **scheduler**：从"per-group job"改为"全局 IngestTarget 扫描 + per-group 分析"。
  - 采集：一个全局采集器，按 IngestTarget 的 due + 并发锁去重采集。
  - 分析：保留 per-group job 触发报告生成（基于 GroupContent 水位）。
- **IngestService** 拆分：
  - `ingest_target(target_id)`：全局采集某 target 的最新内容（去重，采一次）。
  - `analyze_group(group_id)`：基于 GroupContent + 该 group 的订阅，生成报告。

### 6.4 watermark（去重）改造
- **现状**：`ContentRepo.known_ids(source.id)` + 文件目录扫描，per-source。
- **目标**：`GlobalContentRepo.exists(platform, content_id)`，全局。
  - "新内容" = adapter 返回的 content_id 不在 GlobalContent 表里。
  - 不再扫文件系统判断（改为查表，更准更快）。

---

## 7. 迁移策略

### 7.1 数据迁移（一次性脚本）
1. **建默认 admin 用户**，所有现有 group 的 owner_id 回填给它（历史数据归你）。
2. **GlobalContent 回填**：遍历现有 ContentItem，按 `(platform, content_id)` 去重写入 GlobalContent（含五阶段采集状态）。
3. **SourceContent 回填**：现有 ContentItem 的 `(source_id, content_id)` → `(source_id, global_content_id, ingest_target_id=NULL)`。
4. **GroupContent 回填（评审指出遗漏）**：从 SourceContent → Source.group_id 聚合，按 `(group_id, global_content_id)` 去重生成 GroupContent。analyzed_at 从旧 AnalyzedContent 映射（有记录则填，否则 NULL）。
5. **IngestTarget 回填（评审指出遗漏）**：从现有 enabled Source 聚合——
   - creator source → `IngestTarget(kind=creator, platform, target_key=identifier)`，按 target 合并所有订阅该 sec_uid 的 Source 的参数（取最激进值），填 last_check/last_error 从 Source 迁移。
   - keyword source → `IngestTarget(kind=keyword, platform, target_key=identifier)`，同样合并。
   - 回填 SourceContent.ingest_target_id（关联到对应 target）。
6. **Signal 回填**：按 `global_content_id` 去重，取最新一条。
7. **文件迁移**（copy + manifest 策略）：
   - 先写 manifest（记录每个旧路径 → 新路径的映射）。
   - `cp` 到新路径 `data/{platform}/creators/{creator_id or '_unknown'}/`。
   - 校验文件数和大小一致。
   - 校验通过后切换代码读新路径。
   - 旧目录保留一段时间，确认稳定后清理。
8. **报告路径**：`knowledge/{group.slug}/` → `knowledge/{group_id}/`（同样 copy+校验）。
9. 旧 ContentItem/AnalyzedContent 表保留（备份），新代码只读写新表。

### 7.2 回滚
- 迁移脚本配套回滚脚本（参照现有 `migrations/002_rollback.py` 模式）。
- DB 迁移可回滚（旧表保留）。
- 文件迁移用 copy 而非 mv，旧文件不删 → 回滚只需改代码指回旧路径，不需"mv 回来"。

---

## 8. 改动影响面（来自调研，按 blast radius 排序）

| # | 改动 | 文件 | 范围 |
|---|------|------|------|
| 1 | 存储层全局化 | `storage/fs.py`、`storage/paths.py`、`storage/cache.py` | 最大，4 service + 4 API 依赖 |
| 2 | ContentItem → GlobalContent | `schema.py`、`db/repos/content_repo.py`（重写）、`ingest_service.py` | 核心，重写采集状态机 |
| 3 | SourceContent + GroupContent 新增 | `schema.py`、新 repo、`knowledge_service.py`（报告水位）、`creators.py` | 核心，订阅关系 + 水位 |
| 4 | IngestTarget 表化 | `schema.py`、新 repo、`scheduler/cron.py`、`ingest_service.py`（creator/keyword 分离） | 核心，调度去重 |
| 5 | Signal 重新建键 | `schema.py`、`signal_repo.py`、`signal_service.py`、`insight_service.py` | 中等 |
| 6 | API 改查表 + 鉴权 | `api/sources.py`、`groups.py`、`signals.py`、`creators.py`、`knowledge_service.py` | 中等，glob→SQL + owner 校验 |
| 7 | Source 去掉 directory/last_check | `source_service.py`、`api/schemas.py` | 小 |
| 8 | cascade delete 重写 | `group_repo.py` | 小 |
| 9 | 迁移脚本 | `migrations/` | 独立 |

---

## 9. 实现顺序建议（多租户提前，评审指出）

> 🔴 评审第 4 条：API 改查全局内容后 owner 边界还没成型 = 裸奔。
> owner_id + Source 归属必须和数据模型第一步同步，不能排到第 6 步。

建议顺序（每步可独立验证）：

1. **数据模型 + 多租户基础（同步做）**：
   - User 表 + KnowledgeGroup.owner_id + slug 联合唯一。
   - GlobalContent、SourceContent、GroupContent、IngestTarget 表骨架。
   - Signal 重新建键在采集层切换时同步做，避免半迁移导致旧报告链路断裂。
   - 迁移脚本骨架（建默认 admin、回填 owner_id）。
   - **此时 owner 边界成型**：Source/Subscription 已有 group→owner 归属。
2. **存储层**：GlobalStorage + paths 改造（copy 迁移，新旧兼容期，creator_id 空值兜底）。
3. **采集层**：IngestService 改写为按 IngestTarget 全局采集（creator/keyword 分离 + 参数合并）。
4. **调度层**：IngestTarget 级去重调度（持久化 last_check/并发锁）。
5. **API 层 + 访问控制（同步做，评审指出不能分）**：
   - API 改查 GlobalContent/GroupContent 表 + owner 反查。
   - 全局 get_current_user + owner 校验（默认锁死）。
   - **两件事同时做**：改查全局内容的同一时刻就把鉴权上好，不留裸奔窗口。
6. **迁移**：跑历史数据迁移脚本（copy + manifest）。

> 第 1 步是地基：多租户身份（owner_id）和数据模型一起建。
> 第 5 步 API 改造和访问控制必须同步——全局内容能查的同一时刻就锁定谁能查。

---

## 10. 已确认决策（含本轮评审修订）

- [x] **Signal 全局化**：挂 `global_content_id`（信号是内容客观属性，全局判定一次）。
- [x] **增量水位 group 级**：`GroupContent(group_id, global_content_id, analyzed_at)`，**不**放 SourceContent（防 author+keyword 订阅重复消费）。
- [x] **SourceContent**：只记订阅×内容关系（发现记录），不记水位。
- [x] **IngestTarget 表化**：持久化采集目标 + 状态 + 并发锁。**无 creator_id 字段**（keyword target 是 query 无单一 creator，评审指出）。
- [x] **keyword 与 creator 分离**：IngestTarget 分 kind=creator/keyword，各自合并参数、各自调度。
- [x] **keyword 内容按 author 解析归档**到 Creator，author 空时 `_unknown` 兜底（helper 用 `owner_key: str` 统一签名）。
- [x] **订阅生命周期 reconcile**（评审第 2、3 条）：创建回填历史内容 + 重算 target 参数；删除重算 target、无订阅则停采。
- [x] **多租户 + 访问控制提前**：第 1 步建 owner_id，第 5 步 API 和鉴权同步。
- [x] **参数合并**：取最激进值（见 3.6）。
- [x] **回滚策略**：copy + manifest，非 mv。

---

*本文档基于 app/ 代码完整调研。实现时如发现设计偏差，更新本文档而非绕过。*
