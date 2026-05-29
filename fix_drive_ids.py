"""
Получает ID файлов с Google Drive через gdown и обновляет file_url в БД
Запуск: py fix_drive_ids.py
"""

import psycopg2
import psycopg2.extras
import gdown
import os

DATABASE_URL = "postgresql://postgres:YCSCulfKQPFFuzkvmFxLkGaTmpGYgNNW@autorack.proxy.rlwy.net:41049/railway"
ROOT_FOLDER_ID = "1KhLMMrCClkkKAd8qUrLfwGSplozrjSie"

# ── Подключение к БД ──────────────────────────────────────
conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

# Получаем все статьи с PDF именами
cur.execute("SELECT id, file_url FROM articles WHERE file_url IS NOT NULL AND file_url LIKE '%.pdf'")
articles = cur.fetchall()
print(f"Статей в БД: {len(articles)}")

# Строим словарь filename -> article_id
filename_to_article = {a['file_url']: a['id'] for a in articles}

# ── Получаем список файлов через gdown ───────────────────
print("\nПолучаем список файлов с Google Drive...")
url = f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}"

# gdown возвращает список путей — нам нужно только получить ID без скачивания
# Используем внутренний метод для получения метаданных
try:
    from gdown.download_folder import _get_directory_structure
    files_info = _get_directory_structure(ROOT_FOLDER_ID, use_cookies=False)
    print(f"Структура получена")
    print(f"Тип данных: {type(files_info)}")
    print(f"Пример: {str(files_info)[:500]}")
except Exception as e:
    print(f"Внутренний метод не сработал: {e}")
    files_info = None

if files_info is None:
    # Альтернатива — парсим вывод gdown
    import subprocess
    import re
    
    print("\nПробуем через subprocess...")
    result = subprocess.run(
        ["py", "-m", "gdown", "--folder", url, "--skip-download", "-O", "temp_list"],
        capture_output=True, text=True, encoding='utf-8'
    )
    output = result.stdout + result.stderr
    
    # Парсим вывод — ищем строки "Processing file ID filename"
    pattern = r'Processing file ([A-Za-z0-9_-]+)\s+(\S+\.pdf)'
    matches = re.findall(pattern, output)
    
    print(f"Найдено совпадений: {len(matches)}")
    
    updated = 0
    not_found = 0
    
    for file_id, filename in matches:
        if filename in filename_to_article:
            article_id = filename_to_article[filename]
            drive_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            cur.execute(
                "UPDATE articles SET file_url = %s WHERE id = %s",
                (drive_url, article_id)
            )
            updated += 1
        else:
            not_found += 1
            print(f"  Не найдено в БД: {filename}")
    
    conn.commit()
    print(f"\n✅ Обновлено в БД: {updated}")
    print(f"⚠️  Не найдено в БД: {not_found}")
    print(f"📊 Всего на Drive: {len(matches)}")

cur.close()
conn.close()
