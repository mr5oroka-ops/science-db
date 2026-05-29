-- =============================================================
-- Агрегатор научной информации для студентов
-- Логическая схема БД (PostgreSQL), нормализация до 3NF
-- Методология проектирования: IDEF1X
-- =============================================================

-- -------------------------
-- Справочник: Страны
-- -------------------------
CREATE TABLE countries (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    code        CHAR(2) NOT NULL UNIQUE    -- ISO 3166-1 alpha-2
);

-- -------------------------
-- Справочник: Предметные области (иерархия)
-- -------------------------
CREATE TABLE subject_areas (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    parent_id   INT REFERENCES subject_areas(id) ON DELETE SET NULL,
    -- Примеры: Информатика > СУБД > NoSQL
    CONSTRAINT uq_area_parent UNIQUE (name, parent_id)
);

-- -------------------------
-- Организации / Кафедры
-- -------------------------
CREATE TABLE organizations (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(300) NOT NULL,
    short_name  VARCHAR(100),
    country_id  INT NOT NULL REFERENCES countries(id),
    type        VARCHAR(50) CHECK (type IN ('university', 'institute', 'company', 'department', 'other')),
    city        VARCHAR(100)
);

-- -------------------------
-- Журналы / Издания
-- -------------------------
CREATE TABLE journals (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(300) NOT NULL,
    issn            CHAR(9),                    -- формат: XXXX-XXXX
    impact_factor   NUMERIC(6,3),
    quartile        CHAR(2) CHECK (quartile IN ('Q1','Q2','Q3','Q4')),
    is_vak          BOOLEAN NOT NULL DEFAULT FALSE,  -- входит ли в список ВАК
    is_scopus       BOOLEAN NOT NULL DEFAULT FALSE,
    is_wos          BOOLEAN NOT NULL DEFAULT FALSE,
    publisher       VARCHAR(200),
    country_id      INT REFERENCES countries(id)
);

-- -------------------------
-- Авторы
-- -------------------------
CREATE TABLE authors (
    id              SERIAL PRIMARY KEY,
    full_name       VARCHAR(200) NOT NULL,
    degree          VARCHAR(100),               -- к.т.н., д.т.н., PhD и т.п.
    h_index         SMALLINT CHECK (h_index >= 0),
    rating          NUMERIC(3,1) CHECK (rating BETWEEN 0 AND 5),
    org_id          INT REFERENCES organizations(id) ON DELETE SET NULL,
    country_id      INT REFERENCES countries(id),
    email           VARCHAR(150),
    orcid           VARCHAR(20)                 -- формат 0000-0000-0000-0000
);

-- -------------------------
-- Ключевые слова (тезаурус)
-- -------------------------
CREATE TABLE keywords (
    id      SERIAL PRIMARY KEY,
    word    VARCHAR(150) NOT NULL UNIQUE
);

-- -------------------------
-- ОСНОВНАЯ ТАБЛИЦА: Статьи / Публикации
-- -------------------------
CREATE TABLE articles (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    abstract        TEXT,
    year            SMALLINT CHECK (year BETWEEN 1900 AND 2100),
    journal_id      INT REFERENCES journals(id) ON DELETE SET NULL,
    doi             VARCHAR(100) UNIQUE,
    url             VARCHAR(500),
    file_url        VARCHAR(500),           -- прямая ссылка на PDF/DOCX
    file_format     VARCHAR(10) CHECK (file_format IN ('pdf','docx','tex','html','other')),
    language        VARCHAR(10) DEFAULT 'ru',
    has_formulas    BOOLEAN DEFAULT FALSE,  -- содержит ли LaTeX-формулы
    is_open_access  BOOLEAN DEFAULT FALSE,
    pages           VARCHAR(20),            -- например '15-28'
    volume          VARCHAR(20),
    issue           VARCHAR(20),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- Связь: Статья ↔ Авторы (M:N)
-- -------------------------
CREATE TABLE article_authors (
    article_id  INT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    author_id   INT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    author_order SMALLINT NOT NULL DEFAULT 1,  -- порядок авторов
    PRIMARY KEY (article_id, author_id)
);

-- -------------------------
-- Связь: Статья ↔ Ключевые слова (M:N)
-- -------------------------
CREATE TABLE article_keywords (
    article_id  INT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    keyword_id  INT NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, keyword_id)
);

-- -------------------------
-- Связь: Статья ↔ Предметная область (M:N)
-- -------------------------
CREATE TABLE article_areas (
    article_id  INT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    area_id     INT NOT NULL REFERENCES subject_areas(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, area_id)
);

-- -------------------------
-- AI-пересказы / переводы
-- -------------------------
CREATE TABLE summaries (
    id          SERIAL PRIMARY KEY,
    article_id  INT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    language    VARCHAR(10) NOT NULL DEFAULT 'ru',
    model_name  VARCHAR(100) NOT NULL,          -- например 'claude-3-5-sonnet'
    summary_text TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_summary UNIQUE (article_id, language, model_name)
);

-- -------------------------
-- Пользователи системы
-- -------------------------
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    role        VARCHAR(20) NOT NULL DEFAULT 'student'
                    CHECK (role IN ('student', 'admin', 'moderator')),
    org_id      INT REFERENCES organizations(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------
-- Избранное пользователя
-- -------------------------
CREATE TABLE favorites (
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id  INT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id)
);

-- =============================================================
-- ИНДЕКСЫ для ускорения поиска
-- =============================================================
CREATE INDEX idx_articles_year ON articles(year);
CREATE INDEX idx_articles_lang ON articles(language);
CREATE INDEX idx_articles_format ON articles(file_format);
CREATE INDEX idx_articles_open ON articles(is_open_access);
CREATE INDEX idx_articles_formulas ON articles(has_formulas);
CREATE INDEX idx_articles_title_ft ON articles USING gin(to_tsvector('russian', title));
CREATE INDEX idx_articles_abstract_ft ON articles USING gin(to_tsvector('russian', abstract));
CREATE INDEX idx_authors_rating ON authors(rating);
CREATE INDEX idx_authors_hindex ON authors(h_index);
CREATE INDEX idx_journals_vak ON journals(is_vak);
CREATE INDEX idx_journals_quartile ON journals(quartile);

-- =============================================================
-- ДЕМО-ДАННЫЕ
-- =============================================================
INSERT INTO countries (name, code) VALUES
    ('Россия', 'RU'), ('США', 'US'), ('Германия', 'DE'), ('Китай', 'CN');

INSERT INTO subject_areas (name, parent_id) VALUES
    ('Информатика', NULL),
    ('Математика', NULL),
    ('Физика', NULL);

INSERT INTO subject_areas (name, parent_id) VALUES
    ('Базы данных', 1),
    ('Информационная безопасность', 1),
    ('Машинное обучение', 1),
    ('Криптография', 5);

INSERT INTO organizations (name, short_name, country_id, type, city) VALUES
    ('Московский государственный университет', 'МГУ', 1, 'university', 'Москва'),
    ('Санкт-Петербургский политехнический университет', 'СПбПУ', 1, 'university', 'Санкт-Петербург'),
    ('Кафедра информационных систем', 'КИС', 1, 'department', 'Москва');

INSERT INTO journals (name, issn, impact_factor, quartile, is_vak, is_scopus) VALUES
    ('Проблемы информационной безопасности', '1817-5600', 1.23, 'Q2', TRUE, TRUE),
    ('Программная инженерия', '2220-3397', 0.89, 'Q3', TRUE, FALSE),
    ('Journal of Database Management', '1063-8016', 2.45, 'Q1', FALSE, TRUE);

INSERT INTO authors (full_name, degree, h_index, rating, org_id, country_id) VALUES
    ('Иванов Иван Иванович', 'д.т.н.', 12, 4.7, 1, 1),
    ('Петрова Анна Сергеевна', 'к.т.н.', 5, 4.2, 2, 1),
    ('Smith John', 'PhD', 20, 4.9, NULL, 2);

INSERT INTO keywords (word) VALUES
    ('SQL'), ('NoSQL'), ('нормализация'), ('индексирование'),
    ('шифрование'), ('RSA'), ('машинное обучение'), ('нейронные сети');

INSERT INTO articles (title, abstract, year, journal_id, doi, file_format, language, has_formulas, is_open_access) VALUES
    ('Методы оптимизации запросов в реляционных СУБД',
     'В статье рассматриваются алгоритмы оптимизации SQL-запросов с использованием индексов.',
     2023, 2, '10.1234/db.2023.001', 'pdf', 'ru', FALSE, TRUE),

    ('Применение RSA-шифрования в распределённых системах',
     'Анализируется применение асимметричного шифрования RSA в микросервисных архитектурах. Используется формула: $$C = M^e \mod n$$.',
     2022, 1, '10.5678/sec.2022.042', 'pdf', 'ru', TRUE, TRUE),

    ('Deep Learning for Database Query Optimization',
     'We propose a neural network approach to predict optimal query execution plans.',
     2024, 3, '10.9999/jdm.2024.007', 'pdf', 'en', FALSE, FALSE);

INSERT INTO article_authors (article_id, author_id, author_order) VALUES
    (1, 1, 1), (1, 2, 2),
    (2, 1, 1),
    (3, 3, 1);

INSERT INTO article_keywords (article_id, keyword_id) VALUES
    (1, 1), (1, 3), (1, 4),
    (2, 5), (2, 6),
    (3, 7), (3, 8);

INSERT INTO article_areas (article_id, area_id) VALUES
    (1, 4), (2, 5), (2, 7), (3, 4), (3, 6);

-- =============================================================
-- СЛОЖНЫЕ SELECT-ЗАПРОСЫ (для курсовой, раздел 2.2.2)
-- =============================================================

-- Запрос 1: Статьи с рейтингом автора > 4.5, с AI-пересказом, по ключевому слову
-- SELECT a.title, s.summary_text, auth.full_name, auth.rating, j.name AS journal
-- FROM articles a
-- JOIN article_authors aa ON a.id = aa.article_id
-- JOIN authors auth ON aa.author_id = auth.id
-- JOIN journals j ON a.journal_id = j.id
-- LEFT JOIN summaries s ON a.id = s.article_id AND s.language = 'ru'
-- JOIN article_keywords ak ON a.id = ak.article_id
-- JOIN keywords k ON ak.keyword_id = k.id
-- WHERE k.word = 'RSA' AND auth.rating > 4.5
-- ORDER BY auth.rating DESC;

-- Запрос 2: Количество статей по предметным областям с ВАК-журналами
-- SELECT sa.name AS area, COUNT(a.id) AS total, AVG(j.impact_factor) AS avg_if
-- FROM subject_areas sa
-- JOIN article_areas ar ON sa.id = ar.area_id
-- JOIN articles a ON ar.article_id = a.id
-- JOIN journals j ON a.journal_id = j.id
-- WHERE j.is_vak = TRUE
-- GROUP BY sa.name
-- ORDER BY total DESC;

-- Запрос 3: Топ авторов по количеству публикаций в Scopus за последние 3 года
-- SELECT auth.full_name, auth.h_index, COUNT(a.id) AS pubs, org.name AS org
-- FROM authors auth
-- JOIN article_authors aa ON auth.id = aa.author_id
-- JOIN articles a ON aa.article_id = a.id
-- JOIN journals j ON a.journal_id = j.id
-- LEFT JOIN organizations org ON auth.org_id = org.id
-- WHERE j.is_scopus = TRUE AND a.year >= EXTRACT(YEAR FROM NOW()) - 3
-- GROUP BY auth.id, auth.full_name, auth.h_index, org.name
-- HAVING COUNT(a.id) >= 1
-- ORDER BY pubs DESC, auth.h_index DESC;

-- Запрос 4: Статьи с формулами, открытого доступа, с фильтром по языку и формату
-- SELECT a.title, a.year, a.doi, a.file_format, a.language,
--        STRING_AGG(k.word, ', ') AS keywords
-- FROM articles a
-- JOIN article_keywords ak ON a.id = ak.article_id
-- JOIN keywords k ON ak.keyword_id = k.id
-- WHERE a.has_formulas = TRUE AND a.is_open_access = TRUE
-- GROUP BY a.id, a.title, a.year, a.doi, a.file_format, a.language
-- ORDER BY a.year DESC;

-- Запрос 5: Полнотекстовый поиск по названию и аннотации (PostgreSQL FTS)
-- SELECT a.title, ts_rank(to_tsvector('russian', a.title || ' ' || COALESCE(a.abstract,'')),
--        plainto_tsquery('russian', 'шифрование RSA')) AS rank
-- FROM articles a
-- WHERE to_tsvector('russian', a.title || ' ' || COALESCE(a.abstract,''))
--       @@ plainto_tsquery('russian', 'шифрование RSA')
-- ORDER BY rank DESC;
