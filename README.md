# News Keyword Ingest 使用说明

这是一个用于 **订阅多个新闻关键词、调用 NewsAPI 抓取新闻、并去重写入 MySQL** 的 skill 交付包。

你不需要先理解整个项目结构，只要按本文一步一步操作，就可以跑起来。

---

## 1. 这个包能做什么

它解决的是这几个实际问题：

- 订阅多个关键词，比如：`AI`、`养老`、`机器人`
- 从 NewsAPI 的 `/v2/everything` 接口抓新闻
- 把新闻存入 MySQL
- 同一篇新闻不重复存储
- 一篇新闻即使命中多个关键词，也只存一份正文，但会记录它命中了哪些订阅词
- 支持后续反复执行增量抓取，不会把库灌爆

适合的场景：

- 搭建自己的新闻数据库
- 做关键词订阅系统
- 给后续的 AI 分析、摘要、选题、脚本生成提供原始数据
- 在 OpenClaw / cron / worker 中定时拉取新闻

---

## 2. 包内目录说明

本压缩包包含两层内容：

```text
README.md                       # 你现在看的使用说明
example.env                     # 环境变量示例
news-keyword-ingest/            # 真正的 skill 包
├── SKILL.md
├── assets/
│   └── mysql_schema.sql
├── references/
│   └── schema-and-dedupe.md
└── scripts/
    ├── news_fetcher.py
    └── validate_env.py
```

注意：

- `news-keyword-ingest/` 是 skill 主体
- `README.md` 放在压缩包外层，是为了便于阅读和使用
- 我没有把 `README.md` 直接塞进 skill 目录，是为了避免影响 skill 包规范

---

## 3. 运行前你需要准备什么

你需要准备 4 样东西：

1. Python 3.10+
2. 一个可连接的 MySQL 数据库
3. 一个 NewsAPI API Key
4. 一个 MySQL Python 驱动

推荐环境：

- macOS / Linux / WSL
- Python 3.10 或更高
- MySQL 8.x

---

## 4. 第一步：申请 NewsAPI Key

### 4.1 注册账号

去 NewsAPI 官网注册账号并申请 API Key：

- 注册页：`https://newsapi.org/register`
- 文档页：`https://newsapi.org/docs`
- 鉴权说明：`https://newsapi.org/docs/authentication`

### 4.2 注册流程

按页面提示完成：

- 填写名字
- 填写邮箱
- 设置密码
- 选择个人或企业
- 验证邮箱
- 登录后查看 API Key

### 4.3 你需要知道的几个关键限制

如果你使用的是免费 Developer 计划，官方当前说明包括：

- 仅可用于开发和测试环境
- 每天 100 次请求
- 文章有 24 小时延迟
- 可搜索最近一个月的文章

如果你准备正式上线商用，通常需要升级付费计划。

---

## 5. 第二步：准备 MySQL 数据库

你需要有一个数据库和一个可登录账号。

如果你本地已经有 MySQL，可以直接执行类似 SQL：

```sql
CREATE DATABASE news_ingest CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER 'news_user'@'%' IDENTIFIED BY 'your_password_here';
GRANT ALL PRIVILEGES ON news_ingest.* TO 'news_user'@'%';
FLUSH PRIVILEGES;
```

如果你已经有数据库账号，就不用新建。

---

## 6. 第三步：安装 Python 依赖

这个项目没有把依赖写死在 requirements.txt 里，因为核心依赖很少。

你至少需要安装 **一个** MySQL 驱动，二选一：

### 方案 A：安装 PyMySQL

```bash
pip install pymysql
```

### 方案 B：安装 mysql-connector-python

```bash
pip install mysql-connector-python
```

如果你不知道装哪个，直接装 `pymysql` 就行。

---

## 7. 第四步：配置 .env

把压缩包里的 `example.env` 复制成 `.env`：

```bash
cp example.env .env
```

然后编辑 `.env`，填入你自己的配置：

```env
NEWSAPI_KEY=你的_newsapi_key
MYSQL_URL=mysql://news_user:your_password_here@127.0.0.1:3306/news_ingest
```

### 7.1 MYSQL_URL 格式

格式如下：

```text
mysql://用户名:密码@主机:端口/数据库名
```

例如：

```text
mysql://news_user:123456@127.0.0.1:3306/news_ingest
```

### 7.2 .env 放哪里

推荐把 `.env` 放在 **README 所在目录**，也就是压缩包解压后的外层目录。

因为脚本会优先读取：

1. 当前运行目录下的 `.env`
2. skill 根目录附近的 `.env`

最稳妥的做法就是：

- 在外层目录放 `.env`
- 从外层目录执行命令

---

## 8. 第五步：先检查环境

在压缩包解压后的外层目录执行：

```bash
python news-keyword-ingest/scripts/validate_env.py
```

如果看到类似输出：

```text
Environment check
------------------------------------------------------------
NEWSAPI_KEY: OK
MYSQL_URL : OK
Driver     : OK
Detected   : pymysql
```

说明你的环境已经就绪。

如果报错，优先检查这几件事：

- `.env` 有没有写错
- MySQL 是否可连接
- 驱动是否安装
- Python 版本是否太旧

---

## 9. 第六步：初始化数据库表

首次使用必须先建表：

```bash
python news-keyword-ingest/scripts/news_fetcher.py init-db
```

执行成功后会输出：

```json
{
  "status": "ok",
  "message": "database initialized"
}
```

这一步会创建：

- 订阅表
- 新闻文章表
- 文章与订阅关系表

---

## 10. 第七步：添加关键词订阅

### 添加一个关键词

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "养老"
```

### 添加中文关键词并指定语言

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "人工智能" --language zh
```

### 添加英文关键词

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "elder care" --language en
```

### 限制搜索字段

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "robotics" --language en --search-in title,description
```

### 指定排序方式

可选值：

- `publishedAt`
- `relevancy`
- `popularity`

示例：

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "AI agent" --language en --sort-by publishedAt
```

---

## 11. 查看、停用、启用、删除订阅

### 查看所有订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py list-subscriptions
```

### 停用某个订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py deactivate-subscription --keyword "养老"
```

### 重新启用某个订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py activate-subscription --keyword "养老"
```

### 删除某个订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py remove-subscription --keyword "养老"
```

---

## 12. 第八步：开始抓新闻

### 抓取所有启用中的订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-all
```

### 只抓最近 24 小时

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-all --from-hours 24
```

### 控制抓取页数

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-all --from-hours 24 --max-pages 3
```

### 控制每页数量

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-all --from-hours 24 --page-size 100 --max-pages 3
```

### 只抓一个关键词

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-keyword --keyword "养老" --from-hours 48
```

---

## 13. 程序输出怎么看

抓取结束后，会输出结构化 JSON 摘要，类似：

```json
{
  "status": "ok",
  "subscription_count": 2,
  "results": [
    {
      "subscription_id": 1,
      "keyword": "养老",
      "from": "2026-03-26T00:00:00Z",
      "pages_requested": 1,
      "total_results": 23,
      "new_articles": 8,
      "existing_articles": 10,
      "new_links": 8,
      "errors": []
    }
  ],
  "totals": {
    "pages_requested": 2,
    "new_articles": 15,
    "existing_articles": 17,
    "new_links": 16,
    "error_count": 0
  }
}
```

你主要看这几个字段：

- `new_articles`：新增文章数
- `existing_articles`：已存在文章数
- `new_links`：新增关键词命中关系数
- `error_count`：错误数

---

## 14. 为什么不会重复存储

这是这个 skill 的核心。

### 14.1 订阅去重

订阅表会把关键词做标准化，例如：

- `AI`
- ` ai `
- `Ai`

会尽量视为同一个关键词，不会重复插入多条订阅。

### 14.2 文章去重

文章去重不是只看标题，而是优先处理 URL：

- 去掉 `utm_*` 等追踪参数
- 去掉 fragment
- 统一域名大小写
- 对查询参数排序
- 再计算哈希

这样很多“同一篇文章的不同分享链接”会被视为同一篇。

如果某篇文章没有 URL，才退回使用：

- `title + source + publishedAt`

做哈希去重。

### 14.3 一篇文章命中多个关键词怎么办

不会存多份文章。

设计方式是：

- `articles` 表只存一份文章
- `article_subscriptions` 表记录“这篇文章命中了哪个关键词订阅”

所以后续你既能避免重复，又能保留命中关系。

---

## 15. 推荐的首次完整操作流程

如果你是第一次用，直接照着执行：

### 1）检查环境

```bash
python news-keyword-ingest/scripts/validate_env.py
```

### 2）建表

```bash
python news-keyword-ingest/scripts/news_fetcher.py init-db
```

### 3）添加订阅

```bash
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "养老" --language zh
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "人工智能" --language zh
python news-keyword-ingest/scripts/news_fetcher.py add-subscription --keyword "AI agent" --language en
```

### 4）抓取

```bash
python news-keyword-ingest/scripts/news_fetcher.py fetch-all --from-hours 24 --max-pages 3
```

到这里，这套东西就已经能工作了。

---

## 16. 如何做定时抓取

这个 skill 本身不做死循环，也不内置 scheduler。

这是刻意设计的。

原因是：

- skill 负责“能力”
- OpenClaw / cron / worker 负责“定时触发”

### 16.1 Linux / macOS 下用 cron

例如每小时抓一次：

```cron
0 * * * * cd /your/path/news_ingest_work && /usr/bin/python3 news-keyword-ingest/scripts/news_fetcher.py fetch-all --from-hours 2 >> news_fetch.log 2>&1
```

### 16.2 OpenClaw 中怎么用

如果你在 OpenClaw 中调用这个 skill，推荐工作流是：

1. 初始化一次数据库
2. 通过命令添加订阅
3. 定时触发 `fetch-all`
4. 再由后续流程读取 MySQL 做摘要、分类、分析、写稿

---

## 17. 常见问题

### Q1：为什么抓不到新闻？

先检查：

- 关键词是不是太冷门
- `--language` 是否设置过窄
- 免费计划是否有延迟
- `--from-hours` 时间窗是否太短

### Q2：为什么重复执行后新增文章不多？

这通常不是 bug，而是去重在生效。

### Q3：为什么文章命中了两个关键词，但文章表只有一条？

这是预期行为。

正文只保留一份，关系放在关联表里。

### Q4：可以直接拿去生产吗？

代码层面可以作为基础版本使用，但你最好根据自己的场景补：

- 更严格的日志
- 更严格的监控
- 更细的字段清洗
- 更完善的错误告警
- 更明确的调度策略

### Q5：需要安装哪些第三方库？

最少只要一个 MySQL 驱动：

- `pymysql` 或
- `mysql-connector-python`

其余主要用的是 Python 标准库。

---

## 18. 你最容易踩的坑

这里直接说结论：

### 坑 1：把 `.env` 放错位置

建议你就在压缩包外层目录放 `.env`，不要乱放。

### 坑 2：MySQL_URL 写错

最常见的问题是：

- 少了数据库名
- 密码里有特殊字符但没处理
- 主机端口写错

### 坑 3：没先执行 `init-db`

第一次一定要先建表。

### 坑 4：把免费计划当正式生产计划用

这最危险。

开发能跑，不代表上线能撑住。

---

## 19. 给你的建议

如果你后面准备继续扩展，这个 skill 最值得补的方向有 4 个：

1. 增加 source/domain 白名单和黑名单
2. 增加正文二次抓取与清洗
3. 增加新闻去重后的聚类 / 相似事件合并
4. 增加 AI 摘要、打标签、脚本生成等后处理链路

现在这版已经够你把“关键词订阅新闻入库”这件事先做通。

先跑通，再扩。别一上来就搞成一艘会沉的航空母舰。

