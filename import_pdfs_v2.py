"""
Улучшенный скрипт импорта PDF-файлов в базу данных
Запуск: py import_pdfs_v2.py
"""

import os
import re
import psycopg2
import psycopg2.extras
import fitz  # pymupdf
from dotenv import load_dotenv
from unidecode import unidecode

# Загружаем переменные окружения
load_dotenv()

# ── Настройки подключения к БД ──────────────────────────────────
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    conn_str = DATABASE_URL
else:
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'science_db')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    conn_str = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Папка с PDF ───────────────────────────────────────────────
BASE_DIR = os.path.join(os.path.dirname(__file__), 'library')

# ── Подключение ───────────────────────────────────────────────
try:
    conn = psycopg2.connect(conn_str, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    print("✅ Подключение к БД успешно")
except Exception as e:
    print(f"❌ Ошибка подключения к БД: {e}")
    exit(1)

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

# ── Функция извлечения текста с первых страниц ───────────────
def extract_first_pages(pdf_path, max_pages=2):
    """Извлекает текст с первых страниц PDF с правильной кодировкой"""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page_num in range(min(max_pages, len(doc))):
            # Используем разные методы извлечения текста для лучшей совместимости
            page = doc[page_num]
            # Пробуем сначала обычный метод
            page_text = page.get_text()
            # Если текст слишком короткий или содержит много спецсимволов, пробуем другой метод
            if len(page_text) < 100 or len([c for c in page_text if ord(c) > 127]) > len(page_text) * 0.3:
                page_text = page.get_text("text")  # Простой текст
            text += page_text
        doc.close()
        
        # Пытаемся исправить кодировку если нужно
        try:
            # Если есть проблемы с кодировкой, пробуем декодировать
            if text and len([c for c in text if ord(c) > 127]) > len(text) * 0.5:
                # Пробуем разные кодировки
                for encoding in ['utf-8', 'cp1251', 'latin-1']:
                    try:
                        decoded = text.encode('latin-1').decode(encoding)
                        if len([c for c in decoded if ord(c) > 127]) < len(decoded) * 0.3:
                            text = decoded
                            break
                    except:
                        continue
        except:
            pass
            
        return text.strip()
    except Exception as e:
        print(f"  Ошибка чтения {pdf_path}: {e}")
        return ""

# ── Функция очистки текста ───────────────────────────────────
def clean_text(text):
    """Очищает текст от лишних пробелов и спецсимволов"""
    # Заменяем множественные пробелы на один
    text = re.sub(r'\s+', ' ', text)
    # Удаляем управляющие символы кроме перевода строки
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()

# ── Функция извлечения названия журнала ─────────────────────
def extract_journal_name(text):
    """Извлекает название журнала из первых строк"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # Ищем строку, похожую на название журнала (обычно в первых 3 строках)
    for line in lines[:5]:
        # Пропускаем строки с DOI, УДК, годами
        if re.match(r'^(DOI|УДК|UDC|\d{4})', line, re.IGNORECASE):
            continue
        # Если строка содержит точки и выглядит как название журнала
        if len(line) > 10 and re.search(r'[А-Яа-яA-Za-z]', line):
            # Убираем информацию о годе, томе, выпуске
            journal = re.sub(r'\.\s*\d{4}', '', line)
            journal = re.sub(r'\.\s*Т\.\s*\d+', '', journal)
            journal = re.sub(r'\.\s*Вып\.\s*\d+', '', journal)
            journal = re.sub(r'\.\s*С\.\s*[\d-]+', '', journal)
            return journal.strip()
    
    return "Кафедральные публикации"

# ── Функция парсинга заголовка и авторов ──────────────────────
def parse_metadata(text, year):
    """Парсит заголовок, авторов и DOI из текста"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    title = ""
    authors_raw = ""
    doi = ""
    
    # Извлекаем DOI
    doi_match = re.search(r'DOI\s*(10\.[0-9]{4,}/[^\s]+)', text, re.IGNORECASE)
    if doi_match:
        doi = doi_match.group(1)
    
    # Ищем УДК
    udk_idx = -1
    for i, line in enumerate(lines[:30]):
        if re.match(r'УДК|UDC', line, re.IGNORECASE):
            udk_idx = i
            break
    
    # Извлекаем заголовок
    if udk_idx >= 0 and udk_idx + 1 < len(lines):
        # Заголовок идёт после УДК
        title_lines = []
        for line in lines[udk_idx + 1:udk_idx + 6]:
            # Пропускаем строки с авторами (инициалы)
            if re.match(r'^[А-ЯЁ]\.?[А-ЯЁ]\.?\s+[А-ЯЁ][а-яё]+', line):
                continue
            # Пропускаем очень короткие строки
            if len(line) < 10:
                continue
            # Если строка похожа на продолжение заголовка
            if re.search(r'[А-Яа-я]', line) and not re.match(r'^(DOI|УДК|UDC|Ключевые|Введение|Abstract|Keywords)', line, re.IGNORECASE):
                title_lines.append(line)
            else:
                # Если встретили ключевое слово или начало аннотации - останавливаемся
                if re.match(r'^(Ключевые|Введение|Abstract|Keywords|Аннотация)', line, re.IGNORECASE):
                    break
        
        if title_lines:
            title = ' '.join(title_lines)
    
    # Если заголовок не найден после УДК, ищем самую длинную строку
    if not title:
        candidates = []
        for line in lines[:20]:
            # Пропускаем строки с DOI, УДК, авторами
            if re.match(r'^(DOI|УДК|UDC)', line, re.IGNORECASE):
                continue
            if re.match(r'^[А-ЯЁ]\.?[А-ЯЁ]\.?\s+[А-ЯЁ][а-яё]+', line):
                continue
            if len(line) > 15 and re.search(r'[А-Яа-я]', line):
                candidates.append(line)
        
        if candidates:
            title = max(candidates, key=len)
    
    # Извлекаем авторов - улучшенный паттерн для кириллицы
    # Форматы: "Иванов И.И.", "И.И. Иванов", "В.А. Минаев"
    author_patterns = [
        r'([А-ЯЁ][а-яё]+)\s+([А-ЯЁ]\.)([А-ЯЁ]\.)',  # Иванов И.И.
        r'([А-ЯЁ]\.)([А-ЯЁ]\.)\s+([А-ЯЁ][а-яё]+)',  # И.И. Иванов
    ]
    
    found_authors = []
    for line in lines[:30]:
        # Пропускаем строки с DOI, УДК
        if re.match(r'^(DOI|УДК|UDC)', line, re.IGNORECASE):
            continue
        
        # Проверяем каждый паттерн
        for pattern in author_patterns:
            matches = re.finditer(pattern, line)
            for match in matches:
                if pattern == author_patterns[0]:  # Иванов И.И.
                    author = f"{match.group(1)} {match.group(2)}{match.group(3)}"
                else:  # И.И. Иванов
                    author = f"{match.group(1)}{match.group(2)} {match.group(3)}"
                
                author = author.strip()
                if author and author not in found_authors:
                    found_authors.append(author)
    
    # Если авторов не нашли, пробуем более простой паттерн
    if not found_authors:
        simple_pattern = r'([А-ЯЁ]\.[А-ЯЁ]\.?\s*[А-ЯЁ][а-яё]+|[А-ЯЁ][а-яё]+\s*[А-ЯЁ]\.[А-ЯЉ]\.?)'
        for line in lines[:30]:
            matches = re.findall(simple_pattern, line)
            for match in matches:
                author = match.strip()
                if author and author not in found_authors and len(author) > 3:
                    found_authors.append(author)
    
    authors_raw = '; '.join(found_authors) if found_authors else 'Автор не определён'
    
    # Чистим заголовок
    title = clean_text(title)
    if len(title) > 500:
        title = title[:497] + '...'
    if not title:
        title = "Без названия"
    
    return title, authors_raw, found_authors, doi

# ── Основной цикл по папкам ───────────────────────────────────
total = 0
skipped = 0
errors = 0

print(f"\n📁 Сканирую папку: {BASE_DIR}")

if not os.path.exists(BASE_DIR):
    print(f"❌ Папка {BASE_DIR} не существует")
    exit(1)

for folder_name in sorted(os.listdir(BASE_DIR)):
    folder_path = os.path.join(BASE_DIR, folder_name)
    if not os.path.isdir(folder_path):
        continue

    # Год из имени папки
    year_match = re.search(r'20\d{2}', folder_name)
    year = int(year_match.group()) if year_match else None

    print(f"\n📂 Папка: {folder_name} (год: {year})")

    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    print(f"   Файлов: {len(pdf_files)}")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(folder_path, pdf_file)

        # Проверяем не загружен ли уже этот файл
        cur.execute("SELECT id FROM articles WHERE file_url = %s", (pdf_file,))
        if cur.fetchone():
            print(f"   ⏭  Пропущен (уже в БД): {pdf_file[:40]}...")
            skipped += 1
            continue

        text = extract_first_pages(pdf_path, max_pages=2)
        if not text:
            print(f"   ❌ Не удалось извлечь текст: {pdf_file[:40]}...")
            errors += 1
            continue

        # Проверка на кракозябры
        def is_corrupted_text(text):
            if not text:
                return True
            # Проверяем на наличие специфических кракозябр
            corrupted_patterns = [
                r'[^\w\sА-Яа-яЁё0-9\.,;:\-\(\)]{4,}',  # 4+ спецсимволов подряд
                r'[А-Яа-яЁё]{1,2}[^А-Яа-яЁё\s\w]{3,}',  # 1-2 кириллических символа + 3+ спецсимволов
                r'[^А-Яа-яЁё\s]{10,}',  # 10+ не-кириллических символов подряд
            ]
            for pattern in corrupted_patterns:
                if re.search(pattern, text):
                    return True
            # Проверяем на отсутствие нормальных слов
            words = re.findall(r'[А-Яа-яЁёA-Za-z]{3,}', text)
            if len(words) < 2 and len(text) > 10:
                return True
            return False

        if is_corrupted_text(text):
            print(f"   ⏭  Пропущен (кракозябры): {pdf_file[:40]}...")
            skipped += 1
            continue

        title, authors_raw, author_list, doi = parse_metadata(text, year)

        print(f"   ✓ {pdf_file[:40]}...")
        print(f"     Заголовок: {title[:60]}...")
        print(f"     Авторы: {authors_raw[:60]}...")
        if doi:
            print(f"     DOI: {doi}")

        try:
            # Вставляем статью
            cur.execute("""
                INSERT INTO articles
                    (title, year, journal_id, file_url, file_format, language, is_open_access, doi)
                VALUES (%s, %s, %s, %s, 'pdf', 'ru', TRUE, %s)
                RETURNING id
            """, (title, year, journal_id, pdf_file, doi))
            article_id = cur.fetchone()['id']

            # Вставляем авторов
            for idx, author_name in enumerate(author_list[:5]):  # не более 5 авторов
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
                """, (article_id, author_id, idx + 1))

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
