"""
Получает ID файлов с Google Drive и обновляет file_url в БД
Запуск: py get_drive_ids.py
Зависимости: py -m pip install requests psycopg2-binary
"""

import requests
import psycopg2
import psycopg2.extras
import re
import time

DATABASE_URL = "postgresql://postgres:YCSCulfKQPFFuzkvmFxLkGaTmpGYgNNW@autorack.proxy.rlwy.net:41049/railway"

# ID корневой папки science-db-pdfs
ROOT_FOLDER_ID = "1KhLMMrCClkkKAd8qUrLfwGSplozrjSie"

def get_folder_contents(folder_id):
    """Получает список файлов и папок через публичный Drive API без ключа"""
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Используем Drive API v3 без ключа для публичных папок
    api_url = f"https://www.googleapis.com/drive/v3/files"
    params = {
        "q": f"'{folder_id}' in parents",
        "fields": "files(id,name,mimeType)",
        "key": "AIzaSyC_-X2h2cPtzxVQzNaR-9kzOKMSifFzBjI"  # публичный ключ для чтения
    }
    
    try:
        resp = requests.get(api_url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("files", [])
    except Exception as e:
        print(f"API ошибка: {e}")
    
    return []


def get_folder_contents_html(folder_id):
    """Резервный метод — парсим HTML страницы Drive"""
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        html = resp.text
        
        # Ищем ID файлов и их имена в HTML
        # Паттерн для поиска файлов PDF
        pattern = r'"([0-9A-Za-z_-]{25,})"[^"]*"([^"]*\.pdf)"'
        matches = re.findall(pattern, html, re.IGNORECASE)
        
        files = []
        seen = set()
        for file_id, filename in matches:
            if filename not in seen and len(file_id) > 20:
                files.append({"id": file_id, "name": filename})
                seen.add(filename)
        
        return files
    except Exception as e:
        print(f"HTML парсинг ошибка: {e}")
        return []


# ── Подключение к БД ──────────────────────────────────────
conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

# Получаем все статьи у которых есть file_url (имя файла)
cur.execute("SELECT id, title, file_url FROM articles WHERE file_url IS NOT NULL AND file_url LIKE '%.pdf'")
articles = cur.fetchall()
print(f"Статей с PDF в БД: {len(articles)}")

# Строим словарь filename -> article_id
filename_to_id = {a['file_url']: a['id'] for a in articles}
print(f"Ищем файлы: {list(filename_to_id.keys())[:3]}...")

# ── Получаем список подпапок (2021-2025) ──────────────────
print(f"\nПолучаем содержимое корневой папки...")
subfolders = get_folder_contents(ROOT_FOLDER_ID)

if not subfolders:
    print("API не сработал, пробуем HTML парсинг...")
    # Если API не сработал — выводим инструкцию
    print("""
╔══════════════════════════════════════════════════════╗
║  API без ключа не работает для этой папки.           ║
║  Нужно получить API ключ Google Drive.               ║
║                                                      ║
║  Быстрый способ:                                     ║
║  1. Зайди на console.cloud.google.com                ║
║  2. Создай проект                                    ║
║  3. APIs & Services → Enable APIs → Google Drive API ║
║  4. Credentials → Create Credentials → API Key       ║
║  5. Вставь ключ в переменную GOOGLE_API_KEY ниже     ║
╚══════════════════════════════════════════════════════╝
    """)
    
    # Пробуем альтернативный способ - прямые ссылки по имени файла
    print("\nПробуем альтернативный метод через gdown...")
    
    try:
        import subprocess
        subprocess.run(["py", "-m", "pip", "install", "gdown", "-q"], check=True)
        import gdown
        
        # Получаем список файлов из папки
        url = f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}"
        file_list = gdown.download_folder(url, skip_download=True, quiet=False)
        
        if file_list:
            print(f"Найдено файлов через gdown: {len(file_list)}")
            updated = 0
            for item in file_list:
                filename = item.get('name', '') if isinstance(item, dict) else str(item)
                file_id = item.get('id', '') if isinstance(item, dict) else ''
                
                if filename in filename_to_id and file_id:
                    article_id = filename_to_id[filename]
                    drive_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                    cur.execute(
                        "UPDATE articles SET file_url = %s WHERE id = %s",
                        (drive_url, article_id)
                    )
                    updated += 1
                    print(f"  ✓ {filename} → {file_id}")
            
            conn.commit()
            print(f"\n✅ Обновлено {updated} записей в БД")
        else:
            print("gdown тоже не смог получить список файлов")
            
    except Exception as e:
        print(f"gdown ошибка: {e}")
        print("\n⚠️  Нужен Google Drive API ключ для автоматического получения ID файлов.")
        print("Инструкция выше ↑")

else:
    print(f"Найдено подпапок/файлов: {len(subfolders)}")
    
    all_files = []
    
    # Если нашли подпапки — заходим в каждую
    for item in subfolders:
        if item.get('mimeType') == 'application/vnd.google-apps.folder':
            print(f"  Заходим в папку: {item['name']}")
            subfolder_files = get_folder_contents(item['id'])
            all_files.extend(subfolder_files)
            time.sleep(0.5)
        elif item['name'].endswith('.pdf'):
            all_files.append(item)
    
    print(f"Всего PDF файлов найдено: {len(all_files)}")
    
    # Обновляем БД
    updated = 0
    not_found = 0
    
    for f in all_files:
        filename = f['name']
        file_id = f['id']
        
        if filename in filename_to_id:
            article_id = filename_to_id[filename]
            drive_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            cur.execute(
                "UPDATE articles SET file_url = %s WHERE id = %s",
                (drive_url, article_id)
            )
            updated += 1
            print(f"  ✓ {filename}")
        else:
            not_found += 1
    
    conn.commit()
    print(f"\n✅ Обновлено в БД: {updated}")
    print(f"⚠️  Не найдено в БД: {not_found}")

cur.close()
conn.close()
