"""
Агрегатор научной информации — Backend (FastAPI + asyncpg/psycopg2)
Запуск: uvicorn main:app --reload --port 8000
Зависимости: pip install fastapi uvicorn psycopg2-binary python-dotenv anthropic
"""

import os
import json
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Агрегатор научной информации", version="1.0.0")

# CORS — разрешить запросы от фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Подключение к БД ──────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "science_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    try:
        yield conn
    finally:
        conn.close()


# ── Pydantic-схемы ────────────────────────────────────────────
class ArticleOut(BaseModel):
    id: int
    title: str
    abstract: Optional[str]
    year: Optional[int]
    journal_name: Optional[str]
    is_vak: Optional[bool]
    is_scopus: Optional[bool]
    quartile: Optional[str]
    impact_factor: Optional[float]
    doi: Optional[str]
    file_url: Optional[str]
    file_format: Optional[str]
    language: Optional[str]
    has_formulas: Optional[bool]
    is_open_access: Optional[bool]
    authors: Optional[str]       # конкатенированные авторы
    keywords: Optional[str]      # конкатенированные теги
    areas: Optional[str]         # конкатенированные области


class SummaryRequest(BaseModel):
    article_id: int
    language: str = "ru"


class SummaryOut(BaseModel):
    article_id: int
    language: str
    model_name: str
    summary_text: str


# ── Утилита: строим WHERE-условие динамически ─────────────────
def build_search_query(
    search: Optional[str],
    keyword: Optional[str],
    area_id: Optional[int],
    year_from: Optional[int],
    year_to: Optional[int],
    is_vak: Optional[bool],
    is_scopus: Optional[bool],
    quartile: Optional[str],
    language: Optional[str],
    file_format: Optional[str],
    has_formulas: Optional[bool],
    is_open_access: Optional[bool],
    min_author_rating: Optional[float],
    org_id: Optional[int],
    country_id: Optional[int],
):
    """Собирает SQL-запрос с динамическими фильтрами."""
    conditions = []
    params = []

    base_sql = """
        SELECT
            a.id, a.title, a.abstract, a.year,
            j.name         AS journal_name,
            j.is_vak, j.is_scopus, j.quartile, j.impact_factor,
            a.doi, a.file_url, a.file_format, a.language,
            a.has_formulas, a.is_open_access,
            STRING_AGG(DISTINCT auth.full_name, '; ') AS authors,
            STRING_AGG(DISTINCT k.word, ', ')          AS keywords,
            STRING_AGG(DISTINCT sa.name, ', ')         AS areas
        FROM articles a
        LEFT JOIN journals j          ON a.journal_id    = j.id
        LEFT JOIN article_authors aa  ON a.id            = aa.article_id
        LEFT JOIN authors auth        ON aa.author_id    = auth.id
        LEFT JOIN organizations org   ON auth.org_id     = org.id
        LEFT JOIN article_keywords ak ON a.id            = ak.article_id
        LEFT JOIN keywords k          ON ak.keyword_id   = k.id
        LEFT JOIN article_areas ar    ON a.id            = ar.article_id
        LEFT JOIN subject_areas sa    ON ar.area_id      = sa.id
    """

    # Полнотекстовый поиск по названию и аннотации (PostgreSQL FTS)
    if search:
        conditions.append(
            "to_tsvector('russian', a.title || ' ' || COALESCE(a.abstract,'')) "
            "@@ plainto_tsquery('russian', %s)"
        )
        params.append(search)

    # Фильтр по ключевому слову
    if keyword:
        conditions.append("EXISTS (SELECT 1 FROM article_keywords ak2 "
                          "JOIN keywords k2 ON ak2.keyword_id=k2.id "
                          "WHERE ak2.article_id=a.id AND LOWER(k2.word) LIKE LOWER(%s))")
        params.append(f"%{keyword}%")

    # Фильтр по предметной области
    if area_id:
        conditions.append("EXISTS (SELECT 1 FROM article_areas ar2 "
                          "WHERE ar2.article_id=a.id AND ar2.area_id=%s)")
        params.append(area_id)

    if year_from:
        conditions.append("a.year >= %s"); params.append(year_from)
    if year_to:
        conditions.append("a.year <= %s"); params.append(year_to)
    if is_vak is not None:
        conditions.append("j.is_vak = %s"); params.append(is_vak)
    if is_scopus is not None:
        conditions.append("j.is_scopus = %s"); params.append(is_scopus)
    if quartile:
        conditions.append("j.quartile = %s"); params.append(quartile)
    if language:
        conditions.append("a.language = %s"); params.append(language)
    if file_format:
        conditions.append("a.file_format = %s"); params.append(file_format)
    if has_formulas is not None:
        conditions.append("a.has_formulas = %s"); params.append(has_formulas)
    if is_open_access is not None:
        conditions.append("a.is_open_access = %s"); params.append(is_open_access)

    # Фильтр по рейтингу автора
    if min_author_rating:
        conditions.append("auth.rating >= %s"); params.append(min_author_rating)

    # Фильтр по организации
    if org_id:
        conditions.append("auth.org_id = %s"); params.append(org_id)

    # Фильтр по стране автора
    if country_id:
        conditions.append("auth.country_id = %s"); params.append(country_id)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    full_sql = f"""
        {base_sql}
        {where_clause}
        GROUP BY a.id, a.title, a.abstract, a.year,
                 j.name, j.is_vak, j.is_scopus, j.quartile, j.impact_factor,
                 a.doi, a.file_url, a.file_format, a.language,
                 a.has_formulas, a.is_open_access
        ORDER BY a.year DESC NULLS LAST
        LIMIT 100
    """
    return full_sql, params


# ── Роуты ─────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "Агрегатор научной информации API v1.0"}


@app.get("/api/articles", response_model=List[dict])
def search_articles(
    search: Optional[str] = Query(None, description="Полнотекстовый поиск"),
    keyword: Optional[str] = Query(None, description="Ключевое слово"),
    area_id: Optional[int] = Query(None, description="ID предметной области"),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    is_vak: Optional[bool] = Query(None, description="Только ВАК журналы"),
    is_scopus: Optional[bool] = Query(None),
    quartile: Optional[str] = Query(None, description="Q1/Q2/Q3/Q4"),
    language: Optional[str] = Query(None, description="ru / en"),
    file_format: Optional[str] = Query(None, description="pdf/docx/tex"),
    has_formulas: Optional[bool] = Query(None, description="Содержит LaTeX формулы"),
    is_open_access: Optional[bool] = Query(None),
    min_author_rating: Optional[float] = Query(None, description="Мин. рейтинг автора (0-5)"),
    org_id: Optional[int] = Query(None, description="ID организации"),
    country_id: Optional[int] = Query(None, description="ID страны"),
    db=Depends(get_db),
):
    sql, params = build_search_query(
        search, keyword, area_id, year_from, year_to,
        is_vak, is_scopus, quartile, language, file_format,
        has_formulas, is_open_access, min_author_rating, org_id, country_id
    )
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/articles/{article_id}")
def get_article(article_id: int, db=Depends(get_db)):
    sql = """
        SELECT a.*, j.name AS journal_name, j.is_vak, j.is_scopus,
               j.quartile, j.impact_factor,
               STRING_AGG(DISTINCT auth.full_name || ' (' || COALESCE(auth.degree,'') || ')', '; ') AS authors,
               STRING_AGG(DISTINCT k.word, ', ') AS keywords,
               STRING_AGG(DISTINCT sa.name, ', ') AS areas
        FROM articles a
        LEFT JOIN journals j          ON a.journal_id   = j.id
        LEFT JOIN article_authors aa  ON a.id           = aa.article_id
        LEFT JOIN authors auth        ON aa.author_id   = auth.id
        LEFT JOIN article_keywords ak ON a.id           = ak.article_id
        LEFT JOIN keywords k          ON ak.keyword_id  = k.id
        LEFT JOIN article_areas ar    ON a.id           = ar.article_id
        LEFT JOIN subject_areas sa    ON ar.area_id     = sa.id
        WHERE a.id = %s
        GROUP BY a.id, j.name, j.is_vak, j.is_scopus, j.quartile, j.impact_factor
    """
    with db.cursor() as cur:
        cur.execute(sql, (article_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return dict(row)


@app.get("/api/articles/{article_id}/summary")
def get_summary(article_id: int, language: str = "ru", db=Depends(get_db)):
    """Получить уже сохранённый пересказ или запустить генерацию через AI."""
    # 1. Проверяем кэш в БД
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM summaries WHERE article_id=%s AND language=%s LIMIT 1",
            (article_id, language)
        )
        cached = cur.fetchone()
    if cached:
        return dict(cached)

    # 2. Если нет — берём аннотацию и генерируем
    with db.cursor() as cur:
        cur.execute("SELECT title, abstract FROM articles WHERE id=%s", (article_id,))
        article = cur.fetchone()
    if not article or not article["abstract"]:
        raise HTTPException(status_code=404, detail="Нет аннотации для пересказа")

    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    lang_prompt = "на русском языке" if language == "ru" else "in English"
    prompt = (
        f"Сделай краткий пересказ (3-5 предложений) {lang_prompt} "
        f"следующей научной статьи. Название: «{article['title']}». "
        f"Аннотация: {article['abstract']}"
    )

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    summary_text = message.content[0].text

    # 3. Сохраняем в БД
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO summaries (article_id, language, model_name, summary_text)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (article_id, language, "claude-sonnet-4-20250514", summary_text)
        )
        saved = cur.fetchone()
        db.commit()

    return dict(saved)


@app.get("/api/subject_areas")
def get_areas(db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM subject_areas ORDER BY parent_id NULLS FIRST, name")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/organizations")
def get_orgs(db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT o.*, c.name AS country_name FROM organizations o LEFT JOIN countries c ON o.country_id=c.id ORDER BY o.name")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/countries")
def get_countries(db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM countries ORDER BY name")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# Запрос 2 из курсовой — статистика по областям
@app.get("/api/stats/areas")
def stats_areas(db=Depends(get_db)):
    sql = """
        SELECT sa.name AS area, COUNT(a.id) AS total,
               ROUND(AVG(j.impact_factor)::NUMERIC, 2) AS avg_impact_factor
        FROM subject_areas sa
        JOIN article_areas ar ON sa.id = ar.area_id
        JOIN articles a       ON ar.article_id = a.id
        LEFT JOIN journals j  ON a.journal_id = j.id
        GROUP BY sa.name
        ORDER BY total DESC
    """
    with db.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# Запрос 3 — топ авторов по Scopus
@app.get("/api/stats/top_authors")
def top_authors(db=Depends(get_db)):
    sql = """
        SELECT auth.full_name, auth.h_index, auth.rating,
               COUNT(a.id) AS scopus_pubs,
               org.name AS organization
        FROM authors auth
        JOIN article_authors aa ON auth.id = aa.author_id
        JOIN articles a         ON aa.article_id = a.id
        JOIN journals j         ON a.journal_id = j.id
        LEFT JOIN organizations org ON auth.org_id = org.id
        WHERE j.is_scopus = TRUE
        GROUP BY auth.id, auth.full_name, auth.h_index, auth.rating, org.name
        ORDER BY scopus_pubs DESC, auth.h_index DESC
        LIMIT 20
    """
    with db.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [dict(r) for r in rows]
