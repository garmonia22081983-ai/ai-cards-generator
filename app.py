import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib.parse
import os
import base64
import time

# Инициализация API-ключа из Secrets
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

# Функция для конвертации локальной картинки в Base64
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Проверяем файл 'background.jpg'
bg_css = ""
if os.path.exists("background.jpg"):
    try:
        bin_str = get_base64_of_bin_file("background.jpg")
        bg_css = f"background-image: url('data:image/jpeg;base64,{bin_str}') !important;"
    except Exception:
        bg_css = "background-color: #f5f0e8 !important;"
else:
    bg_css = "background-color: #f5f0e8 !important;"

# Подключение кастомного премиум-дизайна
st.markdown(f"""
<style>
.stApp {{
    {bg_css}
    background-size: cover !important;
    background-repeat: no-repeat !important;
    background-attachment: fixed !important;
}}

.card-front {{
    background-color: #e3b5b5 !important;
    border: 1px solid #d49f9f;
    border-radius: 12px;
    padding: 20px 15px;
    text-align: center;
    min-height: 260px;
    max-height: 260px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-shadow: 0 8px 16px rgba(138, 105, 105, 0.12), 0 2px 6px rgba(0,0,0,0.02);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}
.card-front:hover {{
    transform: translateY(-3px);
    box-shadow: 0 12px 24px rgba(138, 105, 105, 0.18), 0 4px 8px rgba(0,0,0,0.04);
}}

.card-front-title {{
    font-size: 22px;
    font-weight: bold;
    font-family: 'Georgia', serif;
    color: #4a2e2e !important;
    text-shadow: 0 1px 1px rgba(255,255,255,0.3);
    word-break: break-word;
}}

.card-front-subtitle {{
    font-size: 10px;
    color: #704b4b;
    margin-top: 15px;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 600;
}}

.card-back {{
    background-color: #ffffff;
    border: 1px solid #ebdcc5;
    border-radius: 12px;
    padding: 15px;
    min-height: 350px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.02), 0 1px 4px rgba(0,0,0,0.01);
}}

summary::-webkit-details-marker {{ display: none !important; }}
summary {{ list-style: none !important; }}

.print-row {{
    display: flex;
    border: 1px dashed #ccc;
    margin-bottom: 12px;
    page-break-inside: avoid;
    background-color: #ffffff;
}}
.print-col {{ width: 50%; padding: 15px; box-sizing: border-box; }}
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

if "cards" not in st.session_state:
    st.session_state.cards = []
if "flipped" not in st.session_state:
    st.session_state.flipped = {}

def extract_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]): script.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            return '\n'.join(chunk for chunk in chunks if chunk)[:8000]
        return f"Ошибка загрузки сайта: Статус {response.status_code}"
    except Exception as e:
        return f"Не удалось прочитать ссылку автоматически: {str(e)}"

with st.sidebar:
    st.header("⚙️ Настройки генерации")
    model_option = st.selectbox("Нейросеть:", ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-1.5-flash"])
    source_type = st.radio("Что берем за основу?", ["📝 Текст / Отрывок статьи / Трэк субтитров", "🔗 Ссылка на веб-статью", "✍️ Готовый список слов"])
    student_level = st.selectbox("Уровень студента (CEFR):", ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"], index=2)
    num_cards = st.slider("Сколько карточек создать?", min_value=3, max_value=15, value=6)

user_input = ""
if source_type == "📝 Текст / Отрывок статьи / Трэк субтитров":
    user_input = st.text_area("Вставьте сюда текст статьи или субтитры:", height=200)
elif source_type == "🔗 Ссылка на веб-статью":
    user_input = st.text_input("Вставьте URL-ссылку на англоязычную статью:")
else:
    user_input = st.text_area("Введите конкретные слова или фразы:", height=120)

if st.button("Создать карточки ✨", type="primary"):
    if not user_input.strip():
        st.warning("Пожалуйста, заполните поле ввода!")
    else:
        with st.spinner("ИИ подбирает слова, пишет дефиниции и примеры..."):
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
                    Верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском
                    - "translation": точный и красивый перевод на русский
                    - "explanation": дефиниция на английском языке под уровень {student_level}
                    - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                    - "image_keyword": ОДНО короткое ключевое слово на английском для ИИ-картинки.
                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                    """
                else:
                    prompt = f"""
                    Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                    Выбери из текста ровно {num_cards} важных слов под уровень {student_level} из материала: {final_content}
                    Верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском
                    - "translation": точный и красивый перевод на русский
                    - "explanation": дефиниция на английском языке под уровень {student_level}
                    - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                    - "image_keyword": ОДНО короткое ключевое слово на английском для ИИ-картинки.
                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                    """

                response = model.generate_content(prompt)
                text_response = response.text.strip()
                if text_response.startswith("```"):
                    text_response = text_response.split("
