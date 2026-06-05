"""
Агрегатор научной информации — Backend (FastAPI + asyncpg/psycopg2)
Запуск: uvicorn main:app --reload --port 8000
Зависимости: pip install fastapi uvicorn psycopg2-binary python-dotenv anthropic
"""

import os
import json
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, RedirectResponse
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
    import urllib.parse
    database_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
    if database_url:
        conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    else:
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
    author: Optional[str],
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

    # Фильтр по автору
    if author:
        conditions.append("auth.full_name ILIKE %s"); params.append(f"%{author}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    full_sql = f"""
        {base_sql}
        {where_clause}
        GROUP BY a.id, a.title, a.abstract, a.year,
                 j.name, j.is_vak, j.is_scopus, j.quartile, j.impact_factor,
                 a.doi, a.file_url, a.file_format, a.language,
                 a.has_formulas, a.is_open_access
        ORDER BY a.year DESC NULLS LAST
        LIMIT 500
    """
    return full_sql, params


# ── Роуты ─────────────────────────────────────────────────────

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
    author: Optional[str] = Query(None, description="Поиск по автору"),
    db=Depends(get_db),
):
    sql, params = build_search_query(
        search, keyword, area_id, year_from, year_to,
        is_vak, is_scopus, quartile, language, file_format,
        has_formulas, is_open_access, min_author_rating, org_id, country_id, author
    )
    with db.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/articles/{article_id}")
def get_article(article_id: int, db=Depends(get_db)):
    sql = """
        SELECT a.id, a.title, a.abstract, a.year, a.doi, a.file_url, a.file_format, a.language, a.has_formulas, a.is_open_access,
               j.name AS journal_name, j.is_vak, j.is_scopus, j.quartile, j.impact_factor,
               STRING_AGG(DISTINCT auth.full_name, '; ') AS authors,
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
        GROUP BY a.id, a.title, a.abstract, a.year, a.doi, a.file_url, a.file_format, a.language, a.has_formulas, a.is_open_access,
                 j.name, j.is_vak, j.is_scopus, j.quartile, j.impact_factor
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
    if article is None:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    # Используем abstract если есть, иначе title
    text_to_summarize = article["abstract"] if article["abstract"] else article["title"]
    if not text_to_summarize:
        raise HTTPException(status_code=404, detail="Нет данных для пересказа")

    # Используем Google Gemini через REST API с retry
    if os.getenv("GEMINI_API_KEY"):
        import requests
        import time
        api_key = os.getenv("GEMINI_API_KEY")

        # Retry логика
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Сначала пробуем получить список доступных моделей
                list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                list_response = requests.get(list_url, timeout=10)
                list_response.raise_for_status()
                models_data = list_response.json()

                # Ищем доступную модель для генерации текста
                available_models = []
                if "models" in models_data:
                    for model in models_data["models"]:
                        if "generateContent" in model.get("supportedGenerationMethods", []):
                            available_models.append(model["name"])

                if not available_models:
                    raise Exception("Нет доступных моделей для генерации текста")

                # Используем первую доступную модель
                model_name = available_models[0].split("/")[-1]
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

                lang_prompt = "на русском языке" if language == "ru" else "in English"
                prompt_text = (
                    f"Сделай краткий пересказ (3-5 предложений) {lang_prompt} "
                    f"следующей научной статьи. Название: «{article['title']}». "
                    f"Текст: {text_to_summarize}"
                )

                payload = {
                    "contents": [{
                        "parts": [{
                            "text": prompt_text
                        }]
                    }]
                }

                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()

                if "candidates" in result and len(result["candidates"]) > 0:
                    summary_text = result["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    raise Exception("Нет ответа от модели")

                model_name = model_name
                break  # Успешно, выходим из retry цикла
            except Exception as e:
                print(f"Gemini error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Ждем перед retry
                else:
                    raise HTTPException(status_code=500, detail=f"Ошибка генерации пересказа: {str(e)}")
    else:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY не установлен")

    # 3. Сохраняем в БД
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO summaries (article_id, language, model_name, summary_text)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (article_id, language, model_name, summary_text)
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

from fastapi.responses import HTMLResponse, FileResponse

class ArticleCreate(BaseModel):
    title: str
    authors: Optional[str] = None
    abstract: Optional[str] = None
    year: Optional[int] = None
    language: Optional[str] = "ru"
    keywords: Optional[str] = None
    is_vak: Optional[bool] = False
    is_scopus: Optional[bool] = False
    is_open_access: Optional[bool] = True
    has_formulas: Optional[bool] = False

@app.post("/api/articles/add")
def add_article(data: ArticleCreate, db=Depends(get_db)):
    with db.cursor() as cur:
        # Находим или создаём журнал "Кафедральные публикации"
        cur.execute("SELECT id FROM journals WHERE name = 'Кафедральные публикации' LIMIT 1")
        j = cur.fetchone()
        journal_id = j['id'] if j else None

        cur.execute("""
            INSERT INTO articles (title, abstract, year, journal_id, language, file_format, is_open_access, has_formulas)
            VALUES (%s, %s, %s, %s, %s, 'pdf', %s, %s) RETURNING id
        """, (data.title, data.abstract, data.year, journal_id, data.language, data.is_open_access, data.has_formulas))
        article_id = cur.fetchone()['id']

        # Добавляем авторов
        if data.authors:
            for i, name in enumerate(data.authors.split(';')):
                name = name.strip()
                if not name: continue
                cur.execute("SELECT id FROM authors WHERE full_name = %s LIMIT 1", (name,))
                a = cur.fetchone()
                if a:
                    author_id = a['id']
                else:
                    cur.execute("INSERT INTO authors (full_name, country_id) VALUES (%s, 1) RETURNING id", (name,))
                    author_id = cur.fetchone()['id']
                cur.execute("INSERT INTO article_authors (article_id, author_id, author_order) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (article_id, author_id, i+1))

        # Добавляем ключевые слова
        if data.keywords:
            for word in data.keywords.split(','):
                word = word.strip().lower()
                if not word: continue
                cur.execute("SELECT id FROM keywords WHERE word = %s LIMIT 1", (word,))
                k = cur.fetchone()
                if k:
                    kw_id = k['id']
                else:
                    cur.execute("INSERT INTO keywords (word) VALUES (%s) RETURNING id", (word,))
                    kw_id = cur.fetchone()['id']
                cur.execute("INSERT INTO article_keywords (article_id, keyword_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (article_id, kw_id))

        db.commit()
    return {"status": "ok", "id": article_id}

@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM articles WHERE id = %s RETURNING id", (article_id,))
        deleted = cur.fetchone()
        if not deleted:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        db.commit()
    return {"status": "ok", "deleted_id": article_id}

@app.get("/", response_class=HTMLResponse)
def root():
    with open("index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/library/{filename}")
def download_pdf(filename: str):
    """Скачать PDF файл из папки library или через Google Drive прямую ссылку"""
    # Сначала пробуем локальные файлы
    library_paths = ["library", "/app/library", "/library"]
    for library_path in library_paths:
        if os.path.exists(library_path):
            for root, dirs, files in os.walk(library_path):
                if filename in files:
                    file_path = os.path.join(root, filename)
                    return FileResponse(file_path, media_type='application/pdf', filename=filename)

    # Если локально не найдено, пробуем Google Drive прямую ссылку
    # Формат: https://drive.google.com/file/d/FILE_ID/view?usp=sharing
    # Прямая ссылка: https://drive.google.com/uc?export=download&id=FILE_ID
    if os.getenv("GOOGLE_DRIVE_FOLDER_ID"):
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            import json

            # Загружаем credentials из переменной окружения
            creds_dict = json.loads(os.getenv("GOOGLE_DRIVE_CREDENTIALS"))
            credentials = Credentials.from_authorized_user_info(creds_dict)

            # Создаем Drive API клиент
            drive_service = build('drive', 'v3', credentials=credentials)

            # Ищем файл по имени в указанной папке
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            results = drive_service.files().list(q=f"name='{filename}' and '{folder_id}' in parents and mimeType='application/pdf'", fields="files(id, name)").execute()
            files = results.get('files', [])

            if not files:
                raise HTTPException(status_code=404, detail=f"Файл {filename} не найден на Google Drive")

            file_id = files[0]['id']

            # Перенаправляем на прямую ссылку Google Drive
            direct_link = f"https://drive.google.com/uc?export=download&id={file_id}"
            return RedirectResponse(url=direct_link)
        except Exception as e:
            print(f"Google Drive error: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка скачивания с Google Drive: {str(e)}")

    # Если ни один способ не сработал
    raise HTTPException(status_code=404, detail="Файл не найден. Настройте GOOGLE_DRIVE_FOLDER_ID в Railway.")

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Загрузить PDF файл в Railway volume"""
    try:
        # Создаем папку library если не существует
        library_path = "/app/library"
        if not os.path.exists(library_path):
            os.makedirs(library_path)

        # Сохраняем файл
        file_path = os.path.join(library_path, file.filename)
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        return {"status": "success", "filename": file.filename}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/import")
def import_data(db=Depends(get_db)):
    """Импортировать данные из PDF файлов"""
    try:
        import import_pdfs_v2
        result = import_pdfs_v2.main()
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
