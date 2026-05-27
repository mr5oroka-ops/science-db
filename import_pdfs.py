"""
Скрипт импорта PDF-файлов кафедры в базу данных Railway
Запуск: py import_pdfs.py
"""

import os
import re
import psycopg2
import psycopg2.extras
import fitz  # pymupdf

# ── Настройки подключения к Railway ──────────────────────────
DATABASE_URL = "postgresql://postgres:YCSCulfKQPFFuzkvmFxLkGaTmpGYgNNW@autorack.proxy.rlwy.net:41049/railway"

# ── Папка с PDF ───────────────────────────────────────────────
BASE_DIR = r"E:\библиотека"

# ── Подключение ───────────────────────────────────────────────
conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

# Получаем или создаём журнал для кафедральных работ
cur.execute("""
    INSERT INTO journals (name, is_vak, is_scopus)
    VALUES ('Кафедральные публикации', FALSE, FALSE)
    ON CONFLICT DO NOTHING
    RETURNING id
""")
row = cur.fetchone()
if row:
    journal_id = row['id']
else:
    cur.execute("SELECT id FROM journals WHERE name = 'Кафедральные публикации'")
    journal_id = cur.fetchone()['id']
conn.commit()

# ── Функция извлечения текста с первой страницы ───────────────
def extract_first_page(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = doc[0].get_text()
        doc.close()
        return text.strip()
    except Exception as e:
        print(f"  Ошибка чтения {pdf_path}: {e}")
        return ""

# ── Функция парсинга заголовка и авторов ──────────────────────
def parse_title_authors(text, year):
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    title = ""
    authors_raw = ""

    # Заголовок — обычно самая длинная строка в первых 15 строках
    # или строка после "УДК"
    udk_idx = -1
    for i, line in enumerate(lines[:20]):
        if re.match(r'УДК|UDC', line, re.IGNORECASE):
            udk_idx = i
            break

    if udk_idx >= 0 and udk_idx + 1 < len(lines):
        # Заголовок идёт после УДК
        title_lines = []
        for line in lines[udk_idx + 1:udk_idx + 5]:
            if len(line) > 10 and not re.match(r'^[А-ЯA-Z]\.\s?[А-ЯA-Z]', line):
                title_lines.append(line)
            else:
                break
        title = ' '.join(title_lines)
    
    if not title:
        # Берём самую длинную строку из первых 10
        candidates = [l for l in lines[:15] if len(l) > 15]
        if candidates:
            title = max(candidates, key=len)

    # Авторы — строки с инициалами вида "Иванов И.И." или "И.И. Иванов"
    author_pattern = re.compile(
        r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)|([А-ЯЁ]\.[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]+)'
    )
    found_authors = []
    for line in lines[:25]:
        matches = author_pattern.findall(line)
        for m in matches:
            author = m[0] or m[1]
            if author and author not in found_authors:
                found_authors.append(author.strip())

    authors_raw = '; '.join(found_authors) if found_authors else 'Автор не определён'

    # Чистим заголовок
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 500:
        title = title[:497] + '...'
    if not title:
        title = os.path.basename(pdf_path).replace('.pdf', '')

    return title, authors_raw, found_authors

# ── Основной цикл по папкам ───────────────────────────────────
total = 0
skipped = 0
errors = 0

for folder_name in sorted(os.listdir(BASE_DIR)):
    folder_path = os.path.join(BASE_DIR, folder_name)
    if not os.path.isdir(folder_path):
        continue

    # Год из имени папки
    year_match = re.search(r'20\d{2}', folder_name)
    year = int(year_match.group()) if year_match else None

    print(f"\n📁 Папка: {folder_name} (год: {year})")

    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    print(f"   Файлов: {len(pdf_files)}")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(folder_path, pdf_file)

        # Проверяем не загружен ли уже этот файл
        cur.execute("SELECT id FROM articles WHERE file_url = %s", (pdf_file,))
        if cur.fetchone():
            skipped += 1
            continue

        text = extract_first_page(pdf_path)
        if not text:
            errors += 1
            continue

        title, authors_raw, author_list = parse_title_authors(text, year)

        print(f"   ✓ {pdf_file[:40]}... → {title[:50]}...")

        try:
            # Вставляем статью
            cur.execute("""
                INSERT INTO articles
                    (title, year, journal_id, file_url, file_format, language, is_open_access)
                VALUES (%s, %s, %s, %s, 'pdf', 'ru', TRUE)
                RETURNING id
            """, (title, year, journal_id, pdf_file))
            article_id = cur.fetchone()['id']

            # Вставляем авторов
            for author_name in author_list[:5]:  # не более 5 авторов
                # Ищем или создаём автора
                cur.execute(
                    "SELECT id FROM authors WHERE full_name = %s", (author_name,)
                )
                author_row = cur.fetchone()
                if author_row:
                    author_id = author_row['id']
                else:
                    # Нужна страна — берём Россию (id=1)
                    cur.execute(
                        "INSERT INTO authors (full_name, country_id) VALUES (%s, 1) RETURNING id",
                        (author_name,)
                    )
                    author_id = cur.fetchone()['id']

                cur.execute("""
                    INSERT INTO article_authors (article_id, author_id, author_order)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (article_id, author_id, author_list.index(author_name) + 1))

            conn.commit()
            total += 1

        except Exception as e:
            conn.rollback()
            print(f"   ✗ Ошибка вставки {pdf_file}: {e}")
            errors += 1

print(f"\n{'='*50}")
print(f"✅ Загружено:  {total}")
print(f"⏭  Пропущено: {skipped} (уже были в БД)")
print(f"❌ Ошибок:    {errors}")

cur.close()
conn.close()
