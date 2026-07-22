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

# --- 🎨 ДИЗАЙН, ФОН И СТИЛИ ДЛЯ ПЕЧАТИ ---
def apply_custom_design():
    st.markdown(
        """
        <style>
        /* Фоновая текстура сайта (холст/клеточка) */
        .stApp {
            background-color: #f7f5f0;
            background-image: 
                linear-gradient(90deg, rgba(200, 195, 185, 0.2) 1px, transparent 1px),
                linear-gradient(rgba(200, 195, 185, 0.2) 1px, transparent 1px);
            background-size: 12px 12px;
        }
        
        /* Стилизация боковой панели */
        [data-testid="stSidebar"] {
            background-color: #f1ede4 !important;
            border-right: 1px solid #e2ddd3;
        }

        /* Белые карточки блоков */
        .css-card-box {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
            border: 1px solid #e8e4dc;
            margin-bottom: 15px;
        }

        /* Интерактивная флип-карточка */
        .flashcard {
            background-color: #ffffff;
            border: 2px solid #e8e4dc;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        }

        /* Cтили для печатной версии (@media print) */
        @media print {
            [data-testid="stSidebar"], .no-print, header, footer {
                display: none !important;
            }
            .stApp {
                background: none !important;
            }
            .print-card-grid {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
                page-break-inside: avoid;
            }
            .print-card {
                border: 1px dashed #999;
                padding: 15px;
                border-radius: 8px;
                min-height: 140px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

apply_custom_design()

# --- ПОДКЛЮЧЕНИЕ К GEMINI И GOOGLE SHEETS ---
@st.cache_resource
def init_connections():
    gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
    
    sh = None
    try:
        credentials_dict = None
        if "text_key" in st.secrets:
            raw_key = st.secrets["text_key"]
            credentials_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)
        elif "gcp_service_account" in st.secrets:
            credentials_dict = dict(st.secrets["gcp_service_account"])
            
        if credentials_dict:
            gc = gspread.service_account_from_dict(credentials_dict)
            sheet_url = st.secrets.get("sheet_url", "")
            if sheet_url:
                sh = gc.open_by_url(sheet_url)
    except Exception:
        pass
        
    return sh

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
            return content if content else "ERR: У этого видео отсутствуют текстовые субтитры."
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
    target_email = str(email).strip().lower()
    default_name = "Наталья" if target_email == "garmonia.83@mail.ru" else "Преподаватель"
        
    if not sh_global:
        return default_name
        
    try:
        users_sheet = sh_global.worksheet("Users")
        records = users_sheet.get_all_records()
        for row in records:
            if str(row.get("Email", "")).strip().lower() == target_email:
                name = str(row.get("Name", "")).strip()
                if name:
                    return name
    except Exception:
        pass
        
    return default_name

# --- АВТОРИЗАЦИЯ И СЕССИЯ ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = True 
if "user_email" not in st.session_state:
    st.session_state.user_email = "garmonia.83@mail.ru"

current_user_name = get_user_name(st.session_state.user_email)
is_admin_user = (st.session_state.user_email in ["garmonia.83@mail.ru", "flashcards.ai.help@gmail.com"])

# =========================================================
# 👈 БОКОВАЯ ПАНЕЛЬ (SIDEBAR)
# =========================================================
st.sidebar.markdown(f"Вы вошли как: **{st.session_state.user_email}**")
if st.sidebar.button("Выйти из аккаунта"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Настройки generation")

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

# =========================================================
# 🎯 ГЛАВНАЯ ОБЛАСТЬ И ПРАВАЯ КОЛОНКА (ТАРИФЫ + КОЛОДЫ)
# =========================================================
st.title("🎴 Умный Генератор Двусторонних Карточек")
st.markdown(f"### 👋 Рада видеть вас, {current_user_name}!")

col_main, col_info = st.columns([2.2, 1])

# --- ПРАВАЯ КОЛОНКА: ТАРИФЫ И СОХРАНЕННЫЕ КОЛОДЫ ---
with col_info:
    st.markdown("""
    <div style="background-color: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #e8e4dc; box-shadow: 0 4px 12px rgba(0,0,0,0.02); margin-bottom: 15px;">
        <h4 style="margin-top:0; margin-bottom: 10px;">📊 Твой тариф и лимиты</h4>
        <p style="margin-bottom: 5px;">Тариф: <b>ПРАКТИК</b></p>
        <div style="background-color: #e0e0e0; border-radius: 10px; height: 8px; width: 100%; margin: 10px 0;">
            <div style="background-color: #4caf50; height: 100%; width: 1%; border-radius: 10px;"></div>
        </div>
        <p style="color: #666; font-size: 0.9em; margin-bottom: 2px;">Создано: <b>3 из 300 карточек</b></p>
        <p style="color: #888; font-size: 0.85em; margin: 0;">Осталось: 297 карточек</p>
    </div>
    """, unsafe_allow_html=True)

    # 🌟 ВОЗВРАЩЕННЫЙ БЛОК: СОХРАНЕННЫЕ КОЛОДЫ СПРАВА
    with st.expander("📁 Мои сохраненные колоды", expanded=True):
        st.caption("История созданных ранее наборов:")
        # Пример сохраненных колод (или загрузка из session_state / Google Sheets)
        if "saved_decks" not in st.session_state:
            st.session_state.saved_decks = [
                {"title": "BBC News: Climate Change", "date": "2026-07-21", "count": 12},
                {"title": "Business English: Negotiations", "date": "2026-07-20", "count": 15}
            ]
        
        for deck in st.session_state.saved_decks:
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                st.markdown(f"**{deck['title']}**\n<small style='color:#777;'>{deck['date']} • {deck['count']} карт.</small>", unsafe_allow_html=True)
            with col_d2:
                st.button("Открыть", key=f"open_{deck['title']}")
            st.markdown("<hr style='margin: 8px 0; border: none; border-top: 1px solid #eee;'>", unsafe_allow_html=True)

# --- ЛЕВАЯ (ОСНОВНАЯ) КОЛОНКА ---
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

# =========================================================
# 🚀 ЛОГИКА ГЕНЕРАЦИИ И ВЫВОД С КАСТОМИЗАЦИЕЙ ПЕЧАТИ
# =========================================================
if generate_click:
    is_valid_input = bool(uploaded_file_obj) if source_type == "📁 Видео или аудио файл (до 5 мин)" else bool(user_input.strip())

    if not is_valid_input:
        st.warning("Пожалуйста, заполните поле ввода или загрузите файл!")
    else:
        final_prompt_content = ""
        gemini_uploaded_file = None
        temp_file_path = None
        has_error = False

        if source_type == "🎬 Ссылка на YouTube":
            yt_transcript = get_youtube_transcript(user_input.strip())
            if yt_transcript.startswith("ERR:"):
                st.error(f"⚠️ {yt_transcript.replace('ERR:', '').strip()}")
                st.info("💡 Совет: если у видео недоступны субтитры, вы можете загрузить его фрагмент через опцию «📁 Видео или аудио файл».")
                has_error = True
            else:
                final_prompt_content = yt_transcript

        elif source_type == "📁 Видео или аудио файл (до 5 мин)":
            if uploaded_file_obj.size > 30 * 1024 * 1024:
                st.error("🛑 Файл слишком большой (превышает 30 МБ)!")
                has_error = True
            else:
                file_ext = os.path.splitext(uploaded_file_obj.name)[1]
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

        if has_error:
            st.stop()

        with st.spinner("Методист Gemini обрабатывает материал и собирает карточки..."):
            try:
                model = genai.GenerativeModel(model_option)
                
                prompt_text = f"""
                Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                Проанализируй предоставленный материал и сформируй обучающие карточки.
                
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
                    res = model.generate_content([prompt_text, gemini_uploaded_file])
                else:
                    res = model.generate_content([prompt_text, final_prompt_content])

                # Чистка JSON от вероятных оберток ```json ... ```
                raw_text = res.text.strip()
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                    raw_text = re.sub(r"\n?```$", "", raw_text)
                
                cards_data = json.loads(raw_text)
                st.session_state.generated_cards = cards_data
                st.success("Карточки успешно сформированы!")

            except Exception as e:
                st.error(f"Произошла ошибка при генерации: {e}")

# =========================================================
# 🖨️ ОТОБРАЖЕНИЕ КАРТОЧЕК И КАСТОМИЗАЦИЯ ПЕЧАТИ
# =========================================================
if "generated_cards" in st.session_state and st.session_state.generated_cards:
    cards = st.session_state.generated_cards
    
    st.markdown("---")
    st.subheader("🎴 Готовые карточки")

    # 🌟 ВОЗВРАЩЕННЫЙ БЛОК: КАСТОМИЗАЦИЯ И ПОДГОТОВКА К ПЕЧАТИ
    with st.expander("🖨️ Настройки и кастомизация печати (PDF / Принтер)", expanded=False):
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            print_layout = st.selectbox("Формат раскладки:", ["2 карточки в ряд (Стандарт)", "1 карточка (Большой формат)"])
        with col_p2:
            font_size = st.select_slider("Размер шрифта:", options=["Мелкий", "Средний", "Крупный"], value="Средний")
        with col_p3:
            show_transcription = st.checkbox("Показывать транскрипцию", value=True)
            show_collocations = st.checkbox("Показывать словосочетания", value=True)

        st.caption("💡 Скопируйте или нажмите Ctrl+P (Cmd+P на Mac) для отправки на печать без лишних элементов интерфейса.")

    # Интерактивный просмотр карточек на экране
    tab1, tab2 = st.tabs(["👁️ Просмотр карточек", "📄 JSON / Экспорт"])

    with tab1:
        for idx, card in enumerate(cards, 1):
            with st.container():
                st.markdown(f"""
                <div class="flashcard">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h3 style="margin:0; color: #2c3e50;">{idx}. {card.get('word', '')}</h3>
                        <span style="color: #7f8c8d; font-family: monospace;">{card.get('transcription', '') if show_transcription else ''}</span>
                    </div>
                    <p style="color: #e67e22; font-weight: bold; margin: 5px 0;">Перевод: {card.get('translation', '')}</p>
                    <p style="margin: 5px 0;"><b>Definition:</b> <i>{card.get('explanation', '')}</i></p>
                    {f"<p style='margin: 5px 0; color: #27ae60;'><b>Collocations:</b> {card.get('collocations', '')}</p>" if show_collocations and card.get('collocations') else ''}
                    <p style="margin: 5px 0; background: #f8f9fa; padding: 8px; border-left: 3px solid #3498db;"><b>Context:</b> {card.get('context', '')}</p>
                </div>
                """, unsafe_allow_html=True)

    with tab2:
        st.json(cards)
