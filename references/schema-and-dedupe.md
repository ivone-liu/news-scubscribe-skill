# Schema and Dedupe Strategy

## Why three tables

### 1. `subscriptions`
保存关键词订阅配置。

关键字段：
- `keyword`: 用户原始关键词
- `normalized_keyword`: 归一化关键词，用于唯一约束
- `language`, `search_in`, `sort_by`: NewsAPI 查询参数
- `last_fetched_at`: 上次抓取时间
- `last_fetch_status`, `last_fetch_error`: 最近一次抓取状态

### 2. `articles`
一篇新闻只存一份。

关键字段：
- `article_hash`: 去重核心键
- `canonical_url`: 清洗后的 URL
- `raw_json`: 原始返回结果，便于后续分析和回放

### 3. `article_subscriptions`
记录“某篇文章命中了哪个关键词订阅”。

这样做的好处：
- 同一篇新闻命中多个关键词，不会重复存文章正文
- 但仍然能追踪每个关键词对应了哪些新闻

## Deduplication layers

### Layer 1: keyword dedupe
`subscriptions.normalized_keyword` 唯一。

### Layer 2: article dedupe
优先使用规范化 URL 生成哈希：
- 去 fragment
- 去常见追踪参数
- 域名小写
- 参数排序

### Layer 3: relation dedupe
`article_subscriptions(article_id, subscription_id)` 唯一。

## Incremental fetching
脚本默认按下面逻辑增量抓取：
- 若用户显式传入 `--from-hours`，按这个时间窗口拉取
- 否则用 `last_fetched_at - 10 分钟` 作为起点，保留少量重叠，避免边界时间丢数据

## Recommended scheduling
Skill 内部不做定时器。
建议外部调度器执行：

```bash
python scripts/news_fetcher.py fetch-all --from-hours 24
```

或更频繁地：

```bash
python scripts/news_fetcher.py fetch-all --from-hours 2
```
