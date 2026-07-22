import streamlit as st
import google.generativeai as genai
import requests
import json
import os
import re
import tempfile
import urllib.parse
from datetime import datetime
import uuid
import gspread

# --- НАСТРОЙКА СТРАНИЦЫ ---
st.set_page_config(
    page_title="Умный Генератор Двусторонних Карточек",
    page_icon="🎴",
    layout="wide"
)

# --- ИНИЦИАЛИЗАЦИЯ И ПОДКЛЮЧЕНИЕ К GEMINI И GOOGLE SHEETS ---
@st.cache_resource
def init_connections():
    # Настройка Gemini API
    gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
    
    # Настройка Google Sheets
    try:
        credentials_dict = json.loads(st.secrets["text_key"])
        gc = gspread.service_account_from_dict(credentials_dict)
        sheet_url = st.secrets["sheet_url"]
        sh = gc.open_by_url(sheet_url)
        return sh
    except Exception as e:
        st.error(f"Ошибка подключения к Google Таблицам: {e}")
        return None

sh_global = init_connections()

# --- ВПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def extract_youtube_id(url):
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_youtube_transcript(video_url):
    video_id = extract_youtube_id(video_url)
    if not video_id:
        return "ERR: Не удалось распознать ссылку на YouTube. Проверьте правильность URL."
    
    # Надежное получение ключа Supadata API
    api_key = "sd_0b61c52d4b97ec935795c17b295fd47e"
    try:
        if "SUPADATA_API_KEY" in st.secrets and st.secrets["SUPADATA_API_KEY"]:
            api_key = st.secrets["SUPADATA_API_KEY"]
        elif "smtp" in st.secrets and "SUPADATA_API_KEY" in st.secrets["smtp"]:
            api_key = st.secrets["smtp"]["SUPADATA_API_KEY"]
    except Exception:
        pass
    
    url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&text=true"
    headers = {"x-api-key": api_key}
    
    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            data = response.json()
            content = data.get("content", "")
            if content:
                return content
            else:
                return "ERR: У этого видео отсутствуют текстовые субтитры."
        elif response.status_code == 404:
            return "ERR: У этого видео действительно отсутствуют субтитры на YouTube."
        else:
            return "ERR: Не удалось прочитать субтитры через сервис."
    except Exception as e:
        return f"ERR: Ошибка подключения к сервису субтитров: {e}"

def extract_text_from_url(url):
    try:
        r = requests.get(url, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        paragraphs = soup.find_all('p')
        text = " ".join([p.get_text() for p in paragraphs])
        return text if len(text) > 100 else "Ошибка: Не удалось извлечь достаточно текста со страницы."
    except Exception as e:
        return f"Ошибка при парсинге страницы: {e}"

def get_user_name(email):
    if not sh_global:
        return "Преподаватель"
    try:
        users_sheet = sh_global.worksheet("Users")
        records = users_sheet.get_all_records()
        target_email = str(email).strip().lower()
        
        for row in records:
            row_email = str(row.get("Email", "")).strip().lower()
            if row_email == target_email:
                name = str(row.get("Name", "")).strip()
                if name:
                    return name
    except Exception:
        pass
    return "Преподаватель"

# --- АВТОРИЗАЦИЯ И СЕССИЯ ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = True # Или твоя логика авторизации
if "user_email" not in st.session_state:
    st.session_state.user_email = "garmonia.83@mail.ru"

current_user_name = get_user_name(st.session_state.user_email)
is_admin_user = (st.session_state.user_email in ["garmonia.83@mail.ru", "flashcards.ai.help@gmail.com"])

# =========================================================
# 👈 БОКОВАЯ ПАНЕЛЬ (SIDEBAR) — ВОЗВРАЩАЕМ НАСТРОЙКИ В МЕНЮ
# =========================================================
st.sidebar.markdown(f"**Вы вошли как:** `{st.session_state.user_email}`")
if st.sidebar.button("Выйти из аккаунта"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Настройки generation")

# Выбор модели (Админу — выбор, остальным — Gemini 2.0 Flash)
if is_admin_user:
    model_option = st.sidebar.selectbox(
        "Нейросеть (Панель Админа):",
        ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    )
else:
    model_option = "gemini-2.0-flash"

source_type = st.sidebar.radio(
    "Что берем за основу?",
    [
        "✍️ Готовый список слов",
        "📜 Текст / Отрывок статьи / Субтитры",
        "🎬 Ссылка на YouTube",
        "📁 Видео или аудио файл (до 5 мин)",
        "🔗 Ссылка на веб-статью"
    ]
)

student_level = st.sidebar.selectbox(
    "Уровень студента (CEFR):",
    ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)"]
)

num_cards = st.sidebar.slider("Количество карточек:", min_value=3, max_value=25, value=10)

# =========================================================
# 🎯 ГЛАВНАЯ ОБЛАСТЬ ЭКРАНА
# =========================================================
st.title("🎴 Умный Генератор Двусторонних Карточек")
st.markdown(f"### 👋 Рада видеть вас, {current_user_name}!")

col_main, col_info = st.columns([2, 1])

with col_main:
    user_input = ""
    uploaded_file_obj = None

    if source_type == "✍️ Готовый список слов":
        user_input = st.text_area("Введите конкретные слова или фразы через запятую:", height=150)
    elif source_type == "📜 Текст / Отрывок статьи / Субтитры":
        user_input = st.text_area("Вставьте исходный текст статьи или фрагмент:", height=200)
    elif source_type == "🎬 Ссылка на YouTube":
        user_input = st.text_input("Вставьте ссылку на YouTube видео:")
    elif source_type == "📁 Видео или аудио файл (до 5 мин)":
        uploaded_file_obj = st.file_uploader("Загрузите MP4 или MP3 файл (до 30 МБ):", type=["mp4", "mp3", "m4a", "wav"])
    elif source_type == "🔗 Ссылка на веб-статью":
        user_input = st.text_input("Вставьте ссылку на статью в интернете:")

    generate_click = st.button("Создать карточки 🪄", type="primary")

with col_info:
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 15px; border-radius: 10px; border: 1px solid #eee;">
        <h4>📊 Твой тариф и лимиты</h4>
        <p><b>Тариф:</b> ПРАКТИК</p>
        <p>Создано: <b>3 из 300 карточек</b></p>
    </div>
    """, unsafe_allow_html=True)

# =========================================================
# 🚀 ЛОГИКА ГЕНЕРАЦИИ КАРТОЧЕК
# =========================================================
if generate_click:
    is_valid_input = False
    if source_type == "📁 Видео или аудио файл (до 5 мин)":
        is_valid_input = (uploaded_file_obj is not None)
    else:
        is_valid_input = bool(user_input.strip())

    if not is_valid_input:
        st.warning("Пожалуйста, заполните поле ввода или загрузите файл!")
    else:
        final_prompt_content = ""
        gemini_uploaded_file = None
        temp_file_path = None
        source_url_to_save = user_input.strip() if user_input else ""
        has_error = False

        # 1. Сбор текста / данных до запуска спиннера
        if source_type == "🎬 Ссылка на YouTube":
            yt_transcript = get_youtube_transcript(user_input.strip())
            if yt_transcript.startswith("ERR:"):
                error_text = yt_transcript.replace("ERR:", "").strip()
                st.error(f"⚠️ {error_text}")
                st.info("💡 Совет: если у видео недоступны субтитры, вы можете загрузить его фрагмент через опцию «📁 Видео или аудио файл».")
                has_error = True
            else:
                final_prompt_content = yt_transcript

        elif source_type == "📁 Видео или аудио файл (до 5 мин)":
            if uploaded_file_obj.size > 30 * 1024 * 1024:
                st.error("🛑 Файл слишком большой (превышает 30 МБ)! Загрузите более короткий файл.")
                has_error = True
            else:
                file_ext = os.path.splitext(uploaded_file_obj.name)[1]
                source_url_to_save = f"Файл: {uploaded_file_obj.name}"
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                    tmp.write(uploaded_file_obj.read())
                    temp_file_path = tmp.name
                gemini_uploaded_file = genai.upload_file(path=temp_file_path)

        elif source_type == "🔗 Ссылка на веб-статью":
            scraped_text = extract_text_from_url(user_input.strip())
            if "Ошибка" in scraped_text:
                st.error(scraped_text)
                has_error = True
            else:
                final_prompt_content = scraped_text
        else:
            final_prompt_content = user_input.strip()

        # Если возникла ошибка на этапе подготовки — останавливаемся без лишних спиннеров
        if has_error:
            st.stop()

        # 2. Запуск спиннера и отправка запроса в Gemini
        with st.spinner("Методист Gemini обрабатывает материал и собирает карточки..."):
            try:
                model = genai.GenerativeModel(model_option)
                
                prompt_text = f"""
                Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                Проанализируй предоставленный материал и сформируй карточки.
                
                Верни строго валидный JSON-массив объектов со следующими ключами:
                - "word": оригинальное слово на английском
                - "transcription": фонетическая транскрипция в IPA
                - "translation": точный и красивый перевод на русский
                - "explanation": дефиниция на английском языке под уровень {student_level}
                - "collocations": 2-3 самых популярных словосочетания с этим словом на английском языке через запятую
                - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                
                Верни ТОЛЬКО чистый JSON без маркдаун оберток.
                """

                if gemini_uploaded_file:
                    response = model.generate_content([prompt_text, gemini_uploaded_file])
                else:
                    response = model.generate_content([prompt_text, final_prompt_content])

                st.success("Карточки успешно сформированы!")
                st.json(response.text)

            except Exception as e:
                st.error(f"Произошла ошибка при генерации: {e}")
