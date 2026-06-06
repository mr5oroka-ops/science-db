-- =============================================================
--  ПРИЛОЖЕНИЕ: СЛОЖНЫЕ SELECT-ЗАПРОСЫ
--  Проект: Агрегатор научной информации для студентов
--  СУБД: PostgreSQL
--
--  Каждый запрос использует несколько таблиц, соединения (JOIN),
--  агрегацию (GROUP BY / HAVING), фильтрацию и сортировку.
-- =============================================================


-- -------------------------------------------------------------
-- Запрос 1. Статьи с высоким рейтингом автора (> 4.5),
-- имеющие AI-пересказ, отобранные по ключевому слову.
-- Соединяет 6 таблиц (articles, article_authors, authors, journals,
-- summaries, article_keywords, keywords), LEFT JOIN для пересказа.
-- -------------------------------------------------------------
SELECT a.title,
       s.summary_text,
       auth.full_name,
       auth.rating,
       j.name AS journal
FROM articles a
JOIN article_authors aa ON a.id = aa.article_id
JOIN authors auth       ON aa.author_id = auth.id
LEFT JOIN journals j     ON a.journal_id = j.id
LEFT JOIN summaries s    ON a.id = s.article_id AND s.language = 'ru'
JOIN article_keywords ak ON a.id = ak.article_id
JOIN keywords k          ON ak.keyword_id = k.id
WHERE k.word = 'RSA'
  AND auth.rating > 4.5
ORDER BY auth.rating DESC;


-- -------------------------------------------------------------
-- Запрос 2. Количество статей по предметным областям
-- с расчётом среднего импакт-фактора журналов.
-- Агрегация (COUNT, AVG) + GROUP BY + сортировка.
-- (реализован как эндпоинт GET /api/stats/areas)
-- -------------------------------------------------------------
SELECT sa.name AS area,
       COUNT(a.id) AS total,
       ROUND(AVG(j.impact_factor)::NUMERIC, 2) AS avg_if
FROM subject_areas sa
JOIN article_areas ar ON sa.id = ar.area_id
JOIN articles a       ON ar.article_id = a.id
LEFT JOIN journals j  ON a.journal_id = j.id
GROUP BY sa.name
ORDER BY total DESC;


-- -------------------------------------------------------------
-- Запрос 3. Топ авторов по количеству публикаций в Scopus
-- за последние 3 года. Агрегация + HAVING + множественная
-- сортировка. (реализован как GET /api/stats/top_authors)
-- -------------------------------------------------------------
SELECT auth.full_name,
       auth.h_index,
       COUNT(a.id) AS pubs,
       org.name AS organization
FROM authors auth
JOIN article_authors aa ON auth.id = aa.author_id
JOIN articles a         ON aa.article_id = a.id
JOIN journals j         ON a.journal_id = j.id
LEFT JOIN organizations org ON auth.org_id = org.id
WHERE j.is_scopus = TRUE
  AND a.year >= EXTRACT(YEAR FROM NOW()) - 3
GROUP BY auth.id, auth.full_name, auth.h_index, org.name
HAVING COUNT(a.id) >= 1
ORDER BY pubs DESC, auth.h_index DESC;


-- -------------------------------------------------------------
-- Запрос 4. Статьи с формулами, находящиеся в открытом
-- доступе, с конкатенацией списка ключевых слов.
-- STRING_AGG + GROUP BY + фильтры по булевым полям.
-- (реализован как GET /api/stats/formula_open)
-- -------------------------------------------------------------
SELECT a.title,
       a.year,
       a.doi,
       a.file_format,
       a.language,
       STRING_AGG(DISTINCT k.word, ', ') AS keywords
FROM articles a
JOIN article_keywords ak ON a.id = ak.article_id
JOIN keywords k          ON ak.keyword_id = k.id
WHERE a.has_formulas = TRUE
  AND a.is_open_access = TRUE
GROUP BY a.id, a.title, a.year, a.doi, a.file_format, a.language
ORDER BY a.year DESC;


-- -------------------------------------------------------------
-- Запрос 5. Полнотекстовый поиск по названию и аннотации
-- с ранжированием результатов (PostgreSQL Full-Text Search).
-- ts_vector / ts_query / ts_rank. (реализован как GET /api/stats/fts)
-- -------------------------------------------------------------
SELECT a.title,
       ts_rank(to_tsvector('russian', a.title || ' ' || COALESCE(a.abstract,'')),
               plainto_tsquery('russian', 'шифрование RSA')) AS rank
FROM articles a
WHERE to_tsvector('russian', a.title || ' ' || COALESCE(a.abstract,''))
      @@ plainto_tsquery('russian', 'шифрование RSA')
ORDER BY rank DESC;


-- -------------------------------------------------------------
-- Запрос 6 (дополнительный). Статистика по организациям:
-- число авторов и средний h-index по каждой организации,
-- только университеты. JOIN + GROUP BY + HAVING.
-- -------------------------------------------------------------
SELECT org.name AS organization,
       c.name   AS country,
       COUNT(auth.id)              AS authors_count,
       ROUND(AVG(auth.h_index), 1) AS avg_h_index
FROM organizations org
JOIN authors auth   ON auth.org_id = org.id
LEFT JOIN countries c ON org.country_id = c.id
WHERE org.type = 'university'
GROUP BY org.id, org.name, c.name
HAVING COUNT(auth.id) >= 1
ORDER BY avg_h_index DESC;
