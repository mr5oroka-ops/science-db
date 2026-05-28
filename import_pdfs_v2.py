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

# ── Функция извлечения ключевых слов ─────────────────────────
def extract_keywords(text):
    """Извлекает ключевые слова из текста"""
    keywords = []
    
    # Ищем секцию с ключевыми словами
    keywords_section = re.search(r'(Ключевые слова|Keywords|Ключевые слова:|Keywords:)\s*[:\.]?\s*(.*?)(?=\n\n|\n[A-ZА-ЯЁ]|\nВведение|\nAbstract|\nВведение|$)', text, re.IGNORECASE | re.DOTALL)
    
    if keywords_section:
        keywords_text = keywords_section.group(2)
        # Разделяем по запятым, точкам с запятой и т.д.
        keywords = re.split(r'[,;·•]\s*', keywords_text)
        keywords = [k.strip() for k in keywords if len(k.strip()) > 2]
    else:
        # Если не нашли секцию, пробуем найти слова в тексте
        # Ищем слова, которые часто встречаются и выглядят как термины
        words = re.findall(r'\b[А-Яа-яA-Za-z]{4,}\b', text)
        from collections import Counter
        word_counts = Counter(words)
        # Берем 5 самых частых слов (исключая стоп-слова)
        stop_words = {'и', 'в', 'на', 'с', 'для', 'по', 'из', 'к', 'от', 'that', 'this', 'with', 'from', 'for', 'the', 'and'}
        keywords = [w for w, c in word_counts.most_common(10) if w.lower() not in stop_words and c > 1][:5]
    
    return keywords[:10]  # Не более 10 ключевых слов

# ── Функция извлечения предметных областей ───────────────────
def extract_areas(text):
    """Извлекает предметные области из текста"""
    areas = []

    # Список предметных областей для поиска (расширенный)
    area_keywords = [
        'информатика', 'базы данных', 'системы управления', 'программирование',
        'информационная безопасность', 'криптография', 'защита информации',
        'машинное обучение', 'нейронные сети', 'искусственный интеллект',
        'математика', 'статистика', 'вероятность',
        'физика', 'квантовая физика', 'механика',
        'кибербезопасность', 'сетевая безопасность', 'антивирус',
        'алгоритмы', 'структуры данных', 'компьютерные сети',
        'программная инженерия', 'разработка ПО', 'тестирование',
        'большой данные', 'big data', 'аналитика данных',
        'киберпреступность', 'кроссчейн', 'блокчейн', 'криптовалюты',
        'картографирование', 'геоинформационные системы', 'гис',
        'риск-анализ', 'анализ рисков', 'управление рисками',
        'программно-техническое обеспечение', 'пто', 'софт',
        'киберугрозы', 'угрозы безопасности', 'защита от угроз',
        'граф', 'графовые структуры', 'графовые базы данных',
        'платформа', 'архитектура', 'системная архитектура',
        'автоматизация', 'цифровизация', 'трансформация',
        'моделирование', 'симуляция', 'эмуляция'
    ]

    text_lower = text.lower()
    for area in area_keywords:
        if area in text_lower:
            areas.append(area.capitalize())

    # Если не нашли областей, добавляем общую категорию
    if not areas:
        areas.append('Информатика и вычислительная техника')

    return areas[:5]  # Не более 5 областей

# ── Функция парсинга заголовка и авторов ──────────────────────
def parse_metadata(text, year):
    """Парсит заголовок, авторов, описание и DOI из текста"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    title = ""
    abstract = ""
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
        # Собираем все строки после УДК до авторов или ключевых слов
        all_lines = []
        for line in lines[udk_idx + 1:udk_idx + 15]:
            # Пропускаем строки с авторами (инициалы)
            if re.match(r'^[А-ЯЁ]\.?[А-ЯЁ]\.?\s+[А-ЯЁ][а-яё]+', line):
                break
            # Пропускаем очень короткие строки
            if len(line) < 5:
                continue
            # Если встретили ключевое слово - останавливаемся
            if re.match(r'^(Ключевые|Введение|Abstract|Keywords|Аннотация|DOI|УДК|UDC)', line, re.IGNORECASE):
                break
            all_lines.append(line)
        
        # Объединяем все строки в один текст
        full_text = ' '.join(all_lines)
        
        # Разделяем на название и описание
        # Паттерны для начала описания
        abstract_patterns = [
            r'(Целью работы|В статье|В работе|Статья посвящена|Работа посвящена|В данной статье|В статье рассматривается|В работе рассматривается|Современные системы|В данной работе|В статье рассматриваются|В работе рассматриваются|В статье анализируется|В работе анализируется|В данной статье рассматривается|В данной работе рассматривается)',
        ]
        
        abstract_start_idx = -1
        for pattern in abstract_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                abstract_start_idx = match.start()
                break
        
        if abstract_start_idx > 0:
            # Разделяем название и описание
            title = full_text[:abstract_start_idx].strip()
            abstract = full_text[abstract_start_idx:].strip()
            
            # Очищаем название от лишних знаков препинания в конце
            title = re.sub(r'[.,:;]+$', '', title).strip()
        else:
            # Если не нашли паттерн описания - весь текст это название
            title = full_text.strip()
            abstract = ""
    
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
    
    # Чистим описание
    abstract = clean_text(abstract)
    if len(abstract) > 2000:
        abstract = abstract[:1997] + '...'
    
    # Извлекаем ключевые слова и предметные области
    keywords = extract_keywords(text)
    areas = extract_areas(text)
    
    return title, authors_raw, found_authors, doi, abstract, keywords, areas

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

        title, authors_raw, author_list, doi, abstract, keywords, areas = parse_metadata(text, year)

        # Проверяем DOI на кракозябры (пропускаем проблемные выпуски)
        corrupted_doi_patterns = [
            r'10\.36622/VSTU\.2022\.25\.4\.',  # 2022, выпуск 4
            r'10\.36622/VSTU\.2023\.26\.',     # 2023, выпуск 1-3
            r'10\.36622/VSTU\.2023\.4\.26\.',  # 2023, выпуск 4
        ]
        skip_article = False
        if doi:
            for pattern in corrupted_doi_patterns:
                if re.search(pattern, doi):
                    print(f"   ⏭  Пропущен (кракозябры): {pdf_file[:40]}...")
                    print(f"     DOI: {doi}")
                    skipped += 1
                    skip_article = True
                    break
        
        if skip_article:
            continue

        print(f"   ✓ {pdf_file[:40]}...")
        print(f"     Заголовок: {title[:60]}...")
        print(f"     Авторы: {authors_raw[:60]}...")
        if doi:
            print(f"     DOI: {doi}")

        try:
            # Вставляем статью
            cur.execute("""
                INSERT INTO articles
                    (title, abstract, year, journal_id, file_url, file_format, language, is_open_access, doi)
                VALUES (%s, %s, %s, %s, %s, 'pdf', 'ru', TRUE, %s)
                RETURNING id
            """, (title, abstract, year, journal_id, pdf_file, doi))
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

            # Вставляем ключевые слова
            for keyword in keywords:
                # Ищем или создаём ключевое слово
                cur.execute(
                    "SELECT id FROM keywords WHERE word = %s", (keyword,)
                )
                keyword_row = cur.fetchone()
                if keyword_row:
                    keyword_id = keyword_row['id']
                else:
                    cur.execute(
                        "INSERT INTO keywords (word) VALUES (%s) RETURNING id",
                        (keyword,)
                    )
                    keyword_id = cur.fetchone()['id']

                cur.execute("""
                    INSERT INTO article_keywords (article_id, keyword_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (article_id, keyword_id))

            # Вставляем предметные области
            for area in areas:
                # Ищем или создаём предметную область
                cur.execute(
                    "SELECT id FROM subject_areas WHERE name = %s", (area,)
                )
                area_row = cur.fetchone()
                if area_row:
                    area_id = area_row['id']
                else:
                    cur.execute(
                        "INSERT INTO subject_areas (name) VALUES (%s) RETURNING id",
                        (area,)
                    )
                    area_id = cur.fetchone()['id']

                cur.execute("""
                    INSERT INTO article_areas (article_id, area_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (article_id, area_id))

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
