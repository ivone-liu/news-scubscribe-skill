---
name: news-keyword-ingest
description: 订阅多个新闻关键词，调用 NewsAPI 的 /v2/everything 接口抓取新闻并写入 MySQL，自动去重，避免重复存储同一篇文章，并保留文章与关键词的匹配关系。Use when user asks to 订阅新闻关键词、抓取关键词新闻、更新新闻库、把新闻存到 MySQL、同步 NewsAPI 新闻、批量抓取多个关键词新闻.
license: MIT
compatibility: Requires Python 3.10 or later, outbound HTTPS access to newsapi.org, MySQL connectivity, and environment variables NEWSAPI_KEY and MYSQL_URL available from the runtime or .env.
metadata:
  author: OpenAI
  version: 1.0.0
  category: workflow-automation
  tags:
    - newsapi
    - mysql
    - ingestion
    - subscription
    - deduplication
---
# News Keyword Ingest

## 作用
这个 skill 用于把多个关键词的新闻订阅持久化到 MySQL，并基于 NewsAPI `/v2/everything` 抓取新闻。

它解决 4 个问题：
1. 支持多个关键词长期订阅
2. 抓取结果写入 MySQL
3. 同一篇新闻不重复存储
4. 即使一篇新闻命中多个关键词，也只存一份正文，并在关联表里记录命中的关键词

## 运行前提
优先从运行环境读取以下变量；如果运行目录存在 `.env`，脚本也会尝试读取：

- `NEWSAPI_KEY`
- `MYSQL_URL`

`MYSQL_URL` 示例：

```bash
mysql://username:password@127.0.0.1:3306/news_ingest?charset=utf8mb4
```

支持的驱动：
- `pymysql`
- `mysql-connector-python`

如果两者都没有安装，先安装其中一个。

## 目录说明
- `scripts/news_fetcher.py` 主执行脚本
- `scripts/validate_env.py` 环境检查脚本
- `references/schema-and-dedupe.md` 表结构与去重策略说明
- `assets/mysql_schema.sql` MySQL 建表语句

## 什么时候使用
当用户提出以下类型的需求时使用本 skill：
- “帮我订阅这些关键词的新闻”
- “抓取 AI、养老、机器人相关新闻并存到 MySQL”
- “更新一下关键词订阅的新闻库”
- “不要重复存储新闻，重复的跳过”
- “把 NewsAPI 的新闻定时拉进数据库”

## 工作流
### Step 1: 初始化数据库
首次使用先建表：

```bash
python scripts/news_fetcher.py init-db
```

也可先验证环境：

```bash
python scripts/validate_env.py
```

### Step 2: 添加关键词订阅
每个关键词对应一条订阅记录。

```bash
python scripts/news_fetcher.py add-subscription --keyword "养老"
python scripts/news_fetcher.py add-subscription --keyword "人工智能" --language zh
python scripts/news_fetcher.py add-subscription --keyword "elder care" --language en --search-in title,description
```

### Step 3: 查看订阅

```bash
python scripts/news_fetcher.py list-subscriptions
```

### Step 4: 抓取全部启用中的订阅

```bash
python scripts/news_fetcher.py fetch-all
```

可指定最近时间窗口：

```bash
python scripts/news_fetcher.py fetch-all --from-hours 24 --max-pages 3
```

### Step 5: 只抓取单个关键词

```bash
python scripts/news_fetcher.py fetch-keyword --keyword "养老" --from-hours 48
```

### Step 6: 停用或删除订阅

```bash
python scripts/news_fetcher.py deactivate-subscription --keyword "养老"
python scripts/news_fetcher.py activate-subscription --keyword "养老"
python scripts/news_fetcher.py remove-subscription --keyword "养老"
```

## 去重规则
务必遵守以下规则：

1. **订阅去重**
   - 基于 `normalized_keyword` 唯一约束
   - 同一个关键词重复添加时只更新订阅配置，不重复插入

2. **文章去重**
   - 对文章 URL 做规范化处理：
     - 去掉 fragment
     - 去掉常见追踪参数，如 `utm_*`、`fbclid`、`gclid`
     - 域名小写
     - 查询参数排序
   - 优先对规范化后的 URL 计算 SHA-256 作为 `article_hash`
   - 如果 URL 缺失，则回退到 `title + source + publishedAt` 的组合哈希

3. **关键词命中关系去重**
   - 同一篇文章命中同一个订阅，只保留一条关系记录
   - 同一篇文章命中不同订阅，在关联表中分别记录

## 输出要求
执行抓取后，必须给出结构化摘要，包括：
- 本次抓取的订阅数
- 每个订阅请求的页数
- 新增文章数
- 已存在文章数
- 新增关键词关联数
- 错误信息

## 错误处理
### NewsAPI 请求失败
- 如果返回 429 或 5xx，脚本会自动重试
- 多次失败后写入 `last_fetch_error`

### MySQL 连接失败
- 检查 `MYSQL_URL` 是否正确
- 确认数据库可访问
- 确认已安装 MySQL Python 驱动

### 没有抓到文章
- 这不算错误
- 仍然更新 `last_fetched_at` 和状态

## 示例
### Example 1: 初始化并订阅多个关键词
User says: “帮我订阅 AI、养老、机器人这几个关键词的新闻，并存到 MySQL。”

Actions:
1. 运行 `python scripts/news_fetcher.py init-db`
2. 逐个添加订阅
3. 运行 `python scripts/news_fetcher.py fetch-all --from-hours 24`
4. 返回抓取摘要

Result:
- MySQL 中生成订阅表、文章表、关系表
- 新闻去重入库
- 每篇新闻与命中的关键词建立关联

### Example 2: 更新已有新闻库
User says: “把现有订阅再同步一遍，重复的不要存。”

Actions:
1. 运行 `python scripts/news_fetcher.py fetch-all`
2. 让脚本基于 `last_fetched_at` 自动增量抓取
3. 跳过已存在文章，仅补充新的命中关系

Result:
- 文章表不重复膨胀
- 新匹配关系正常落库

## 执行注意事项
- 首次部署时先运行 `init-db`
- 不要把 API Key 或数据库密码写死在脚本中
- 优先使用环境变量和 `.env`
- 如果需要定时抓取，请由外部调度器触发 `fetch-all`，不要在 skill 内部做死循环
