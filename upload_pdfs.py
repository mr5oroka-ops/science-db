"""
Скрипт для загрузки PDF файлов в Railway volume через API
"""
import os
import requests
from pathlib import Path

# Railway API URL
RAILWAY_URL = "https://web-production-89c45.up.railway.app/api/upload"

# Папка с PDF файлами
LIBRARY_PATH = "library"

def upload_pdf(file_path):
    """Загрузить один PDF файл"""
    filename = os.path.basename(file_path)
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f, 'application/pdf')}
            response = requests.post(RAILWAY_URL, files=files)
            
        if response.status_code == 200:
            print(f"✓ {filename} - загружен")
            return True
        else:
            print(f"✗ {filename} - ошибка: {response.text}")
            return False
    except Exception as e:
        print(f"✗ {filename} - ошибка: {str(e)}")
        return False

def main():
    """Загрузить все PDF файлы"""
    # Находим все PDF файлы
    pdf_files = []
    for root, dirs, files in os.walk(LIBRARY_PATH):
        for file in files:
            if file.endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    
    print(f"Найдено {len(pdf_files)} PDF файлов")
    print(f"Начинаю загрузку...")
    
    success_count = 0
    for i, file_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] ", end="")
        if upload_pdf(file_path):
            success_count += 1
    
    print(f"\nЗагружено: {success_count}/{len(pdf_files)} файлов")

if __name__ == "__main__":
    main()
