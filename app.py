import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib.parse
import os
import base64

# Инициализация API-ключа из Secrets
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

# Функция для конвертации локальной картинки в Base64 (чтобы обойти любые блокировки сайтов)
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Проверяем, загрузила ли Наталья файл 'background.jpg' в свой репозиторий GitHub
bg_css = ""
if os.path.exists("background.jpg"):
    try:
        bin_str = get_base64_of_bin_file("background.jpg")
        bg_css = f"background-image: url('data:image/jpeg;base64,{bin_str}') !important;"
    except Exception:
        bg_css = "background-color: #f5f0e8 !important;" # теплый льняной цвет-заглушка
else:
    # Если файла еще нет, используем красивый мягкий цвет холста с вашей фотографии
    bg_css = "background-color: #f5f0e8 !important;"

# Подключение кастомного премиум-дизайна
st.markdown(f"""
<style>
/* Фоновое оформление всего приложения */
.stApp {{
    {bg_css}
    background-size: cover !important;
    background-repeat: no-repeat !important;
    background-attachment: fixed !important;
}}

/* Лицевая сторона: в точном цвете пыльной розы */
.card-front {{
    background-color: #e3b5b5 !important;
    border: 1px solid #d49f9f;
    border-radius: 16px;
    padding: 40px 20px;
    text-align: center;
    min-height: 400px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-shadow: 0 12px 24px rgba(138, 105, 105, 0.15), 0 4px 10px rgba(0,0,0,0.03);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
}}
.card-front:hover {{
    transform: translateY(-5px);
    box-shadow: 0 20px 35px rgba(138, 105, 105, 0.25), 0 6px 12px rgba(0,0,0,0.05);
}}

/* Элегантный глубокий винный/коричневый цвет для текста на лицевой стороне */
.card-front-title {{
    font-size: 30px;
    font-weight: bold;
    font-family: 'Georgia', serif;
    color: #4a2e2e !important;
    text-shadow: 0 1px 1px rgba(255,255,255,0.3);
}}

.card-front-subtitle {{
    font-size: 11px;
    color: #704b4b;
    margin-top: 25px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
}}

/* Оборотная сторона: чистый бумажный стиль с аккуратной версткой */
.card-back {{
    background-color: #ffffff;
    border: 1px solid #ebdcc5;
    border-radius: 16px;
    padding: 22px;
    min-height: 400px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.03), 0 2px 6px rgba(0,0,0,0.01);
}}

/* Скрываем стандартные маркеры треугольников у раскрывающегося списка переводчика */
summary::-webkit-details-marker {{
    display: none !important;
}}
summary {{
    list-style: none !important;
}}

/* Стили для печати */
.print-row {{
    display: flex;
    border: 1px dashed #ccc;
    margin-bottom: 12px;
    page-break-inside: avoid;
    background-color: #ffffff;
}}
.print-col {{
    width: 50%;
    padding: 15px;
    box-sizing: border-box;
}}
.print-left {{
    border-right: 1px dashed #ccc;
    text-align: center;
    font-weight: bold;
    font-size: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Georgia', serif;
    color: #1a365d;
}}
</style>
""", unsafe_allow_html=True)

st.title("🎴 Умный Генератор Двусторонних Карточек")
st.write("Генерируйте профессиональные лексические карточки с озвучкой, картинками и дефинициями.")

# Инициализация состояний в Session State
if "cards" not in st.session_state:
    st.session_state.cards = []
if "flipped" not in st.session_state:
    st.session_state.flipped = {}

# ФУНКЦИЯ ДЛЯ СКАЧИВАНИЯ ТЕКСТА ИЗ СТАТЬИ
def extract_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = '\n'.join(chunk for chunk in chunks if chunk)
            return clean_text[:8000]
        else:
            return f"Ошибка загрузки сайта: Статус {response.status_code}"
    except Exception as e:
        return f"Не удалось прочитать ссылку автоматически: {str(e)}"

# ЛЕВАЯ ПАНЕЛЬ НАСТРОЕК
with st.sidebar:
    st.header("⚙️ Настройки генерации")
    
    # 1. Выбор модели (ВОЗВРАЩАЕМ GEMINI 3.5 И ДРУГИЕ МОДЕЛИ!)
    model_option = st.selectbox(
        "Нейросеть:", 
        ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-1.5-flash"],
        index=0
    )
    
    # 2. Выбор источника
    source_type = st.radio(
        "Что берем за основу?",
        ["📝 Текст / Отрывок статьи / Трэк субтитров", "🔗 Ссылка на веб-статью", "✍️ Готовый список слов"]
    )
    
    # 3. Выбор уровня студента
    student_level = st.selectbox(
        "Уровень студента (CEFR):",
        ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"],
        index=2
    )
    
    # 4. Количество карточек
    num_cards = st.slider("Сколько карточек создать?", min_value=3, max_value=15, value=6)

# ПОЛЕ ВВОДА НА ОСНОВНОМ ЭКРАНЕ
user_input = ""
if source_type == "📝 Текст / Отрывок статьи / Трэк субтитров":
    user_input = st.text_area("Вставьте сюда текст статьи или субтитры (транскрипт) видео:", height=200,
                              placeholder="Вставьте сюда английский текст, из которого нужно вытащить лексику...")
elif source_type == "🔗 Ссылка на веб-статью":
    user_input = st.text_input("Вставьте URL-ссылку на англоязычную статью:", 
                               placeholder="https://www.bbc.com/news/articles/...")
else:
    user_input = st.text_area("Введите конкретные слова или фразы (через запятую или с новой строки):", height=120,
                              placeholder="bold, digital solution, perseverance")

# КНОПКА ЗАПУСКА
if st.button("Создать карточки ✨", type="primary"):
    if not user_input.strip():
        st.warning("Пожалуйста, вспомните и заполните поле ввода!")
    else:
        with st.spinner("ИИ подбирает слова, пишет дефиниции, примеры и ищет картинки..."):
            try:
                final_content = user_input
                if source_type == "🔗 Ссылка на веб-статью":
                    scraped_text = extract_text_from_url(user_input)
                    if "Ошибка" in scraped_text or "Не удалось" in scraped_text:
                        st.error(scraped_text)
                        st.stop()
                    final_content = scraped_text

                model = genai.GenerativeModel(model_option)
                
                if source_type == "✍️ Готовый список слов":
                    prompt = f"""
                    Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                    Создай карточки для следующих слов/фраз: {final_content}.
                    Для каждого слова верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском
                    - "translation": точный и красивый перевод на русский (можно несколько синонимов через запятую)
                    - "explanation": простое, понятное объяснение (дефиниция) этого слова на английском языке, адаптированное под уровень {student_level}
                    - "context": ОДНО контекстное предложение на английском, в котором выделено или уместно использовано это слово. Предложение и лексика в нем должны строго соответствовать уровню {student_level}.
                    - "image_keyword": ОДНО короткое ключевое слово на английском (существительное, например "mountain", "decision", "agreement"), которое лучше всего визуально описывает данное понятие для поиска картинки.

                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ...
