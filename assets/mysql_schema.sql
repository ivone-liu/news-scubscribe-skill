CREATE TABLE IF NOT EXISTS subscriptions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL,
    normalized_keyword VARCHAR(255) NOT NULL,
    language VARCHAR(8) NULL,
    search_in VARCHAR(64) NULL,
    sort_by VARCHAR(32) NOT NULL DEFAULT 'publishedAt',
    active TINYINT(1) NOT NULL DEFAULT 1,
    last_fetched_at DATETIME NULL,
    last_fetch_status VARCHAR(32) NULL,
    last_fetch_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_normalized_keyword (normalized_keyword)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS articles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    article_hash CHAR(64) NOT NULL,
    source_id VARCHAR(255) NULL,
    source_name VARCHAR(255) NULL,
    author VARCHAR(512) NULL,
    title TEXT NOT NULL,
    description TEXT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    url_to_image TEXT NULL,
    published_at DATETIME NULL,
    content MEDIUMTEXT NULL,
    raw_json LONGTEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_article_hash (article_hash),
    KEY idx_articles_published_at (published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS article_subscriptions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    article_id BIGINT UNSIGNED NOT NULL,
    subscription_id BIGINT UNSIGNED NOT NULL,
    matched_keyword VARCHAR(255) NOT NULL,
    matched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_article_subscription (article_id, subscription_id),
    KEY idx_subscription_id (subscription_id),
    CONSTRAINT fk_article_subscriptions_article
        FOREIGN KEY (article_id) REFERENCES articles(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_article_subscriptions_subscription
        FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
