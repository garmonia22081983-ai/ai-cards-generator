import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib.parse
import os
import base64
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import uuid  # Библиотека для генерации уникальных ID карточек
from streamlit_javascript import st_javascript  # Для работы с LocalStorage

# --- ИНИЦИАЛИЗАЦИЯ API-КЛЮЧА GEMINI ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)


# --- ТЕХНИЧЕСКИЙ ОТПЕЧАТОК УСТРОЙСТВА (LOCALSTORAGE) ---
device_id = st_javascript("""
    let id = localStorage.getItem('gemini_flashcards_device_id');
    if (!id) {
        id = 'dev-' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
        localStorage.setItem('gemini_flashcards_device_id', id);
    }
    id;
""")


# --- ФУНКЦИЯ ДЛЯ ПОДКЛЮЧЕНИЯ К ГУГЛ-ТАБЛИЦЕ ---
def get_gsheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)


# --- БЛОК АВТОРИЗАЦИИ И ПРОВЕРКИ ТРИАЛА ---
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_name" not in st.session_state:
    st.session_state.user_name = "Преподаватель"
if "trial_expired" not in st.session_state:
    st.session_state.trial_expired = False

if not st.session_state.user_email:
    st.subheader("🔑 Доступ к Генератору Карточек")
    st.write("Введите ваш Email для входа. Новым пользователям автоматически предоставляется 3 дня бесплатного доступа!")
    
    email_input = st.text_input("Ваш Email:")
    if st.button("Войти"):
        # --- 🔥 ЗАЩИТА ОТ АСИНХРОННОГО НУЛЯ ---
        if not device_id or device_id == 0 or device_id == "0":
            st.warning("🔒 Секунду, система определяет цифровой отпечаток вашего устройства для защиты тест-драйва. Пожалуйста, нажмите кнопку «Войти» ещё раз.")
            st.rerun()
            
        if "@" not in email_input or "." not in email_input:
            st.error("Пожалуйста, введите корректный адрес электронной почты.")
        else:
            email = email_input.strip().lower()
            try:
                gc = get_gsheets_client()
                sh = gc.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
                users_sheet = sh.worksheet("Users")
                
                rows = users_sheet.get_all_values()
                # Добавляем Name и Device ID в шапку, если таблица пустая
                if not rows:
                    users_sheet.append_row(["Email", "Registration Date", "Status", "Name", "Device ID"])
                    rows = [["Email", "Registration Date", "Status", "Name", "Device ID"]]
                
                user_row = None
                for i, r in enumerate(rows[1:], start=2):
                    if r[0].strip().lower() == email:
                        user_row = (i, r)
                        break
                
                if user_row:
                    row_num, row_data = user_row
                    reg_date_str = row_data[1]
                    status = row_data[2] if len(row_data) > 2 else "active"
                    st.session_state.user_name = row_data[3] if len(row_data) > 3 else "Преподаватель"
                    
                    if status == "blocked":
                        st.error("🚫 Ваш доступ заблокирован. Пожалуйста, обратитесь к администратору.")
                        st.stop()
                        
                    # --- 🔥 УМНЫЙ АПГРЕЙД: ЕСЛИ БЫЛ ТРИАЛ, НО ПОЯВИЛАСЬ ОПЛАТА ---
                    if status == "active":
                        has_paid = False
                        try:
                            payments_sheet = sh.worksheet("Payments")
                            payments_rows = payments_sheet.get_all_values()
                            
                            for p_row in payments_rows[1:]:
                                if len(p_row) > 1 and p_row[1].strip().lower() == email:
                                    has_price = len(p_row) > 6 and p_row[6].strip()
                                    has_order = len(p_row) > 3 and p_row[3].strip()
                                    
                                    if has_price or has_order:
                                        has_paid = True
                                        if p_row[0].strip():
                                            st.session_state.user_name = p_row[0].strip()
                                        break
                        except Exception:
                            pass
                        
                        # Если нашли оплату — меняем статус в базе прямо в текущей строке!
                        if has_paid:
                            status = "paid"
                            users_sheet.update_cell(row_num, 3, "paid")  # Столбец C (Status)
                            users_sheet.update_cell(row_num, 4, st.session_state.user_name)  # Столбец D (Name)
                            try:
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                logs_sheet = sh.worksheet("Logs")
                                logs_sheet.append_row([now_str, email, "Апгрейд", "Пользователь успешно перешел с тест-драйва на платный тариф!"])
                            except Exception:
                                pass
                    # --- КОНЕЦ БЛОКА АПГРЕЙДА ---

                    if status == "paid":
                        st.session_state.user_email = email
                        st.session_state.trial_expired = False
                        st.rerun()
                    else:
                        reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d %H:%M:%S")
                        expiration_date = reg_date + timedelta(days=3)
                        
                        st.session_state.user_email = email
                        if datetime.now() > expiration_date:
                            st.session_state.trial_expired = True
                        else:
                            st.session_state.trial_expired = False
                        st.rerun()
                else:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # --- УМНАЯ ПРОВЕРКА ТАНДЕМА С ТИЛЬДОЙ ---
                    has_paid = False
                    tilda_name = "Преподаватель"
                    tilda_reg_date = now_str
                    
                    try:
                        payments_sheet = sh.worksheet("Payments")
                        payments_rows = payments_sheet.get_all_values()
                        
                        for p_row in payments_rows[1:]:
                            if len(p_row) > 1 and p_row[1].strip().lower() == email:
                                if p_row[0].strip():
                                    tilda_name = p_row[0].strip()
                                
                                has_price = len(p_row) > 6 and p_row[6].strip()
                                has_order = len(p_row) > 3 and p_row[3].strip()
                                
                                if has_price or has_order:
                                    has_paid = True
                                    break
                                else:
                                    if len(p_row) > 11 and p_row[11].strip():
                                        raw_date = p_row[11].strip()
                                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                                            try:
                                                tilda_reg_date = datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d %H:%M:%S")
                                                break
                                            except ValueError:
                                                continue
                    except Exception:
                        pass
                    
                    if has_paid:
                        # Платящих пускаем без проверки ограничений на устройство
                        users_sheet.append_row([email, now_str, "paid", tilda_name, str(device_id)])
                        st.session_state.user_name = tilda_name
                        st.session_state.user_email = email
                        st.session_state.trial_expired = False
                        try:
                            logs_sheet = sh.worksheet("Logs")
                            logs_sheet.append_row([now_str, email, "Авторизация", "Оплата найдена, предоставлен полный доступ"])
                        except Exception:
                            pass
                    else:
                        # --- АНТИ-ФРОД ПРОВЕРКА УСТРОЙСТВА ДЛЯ ТЕСТ-ДРАЙВА ---
                        device_already_used = False
                        if device_id and device_id != 0:
                            for r in rows[1:]:
                                if len(r) > 4 and r[4].strip() == str(device_id):
                                    device_already_used = True
                                    break
                        
                        if device_already_used:
                            st.error("🚫 С этого устройства уже запрашивался бесплатный тест-драйв для другого аккаунта. Пожалуйста, войдите под вашей первой почтой или выберите платный тариф на сайте.")
                            st.stop()
                        
                        # Если устройство чистое — регистрируем триал
                        users_sheet.append_row([email, tilda_reg_date, "active", tilda_name, str(device_id)])
                        st.session_state.user_name = tilda_name
                        st.session_state.user_email = email
                        
                        reg_date = datetime.strptime(tilda_reg_date, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() > (reg_date + timedelta(days=3)):
                            st.session_state.trial_expired = True
                        else:
                            st.session_state.trial_expired = False
                            
                        try:
                            logs_sheet = sh.worksheet("Logs")
                            logs_sheet.append_row([now_str, email, "Регистрация", f"Новый пользователь начал пробный период от {tilda_reg_date} (ID устройства: {device_id})"])
                        except Exception:
                            pass
                    
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Ошибка базы данных: {e}")
                
    # --- ЮРИДИЧЕСКИЙ БЛОК СОГЛАСИЯ ПОД КНОПКОЙ ---
    st.markdown(
        """
        <div style="margin-top: 15px; padding-top: 10px; border-top: 1px dashed #cbd5e0;">
            <small style="color: #718096; font-family: Arial, sans-serif; line-height: 1.4; display: block;">
            Нажимая кнопку «Войти», вы даете согласие на обработку персональных данных 
            в соответствии с <a href="https://flashcards-ai.ru/privacy" target="_blank" style="color: #2e6c9e; text-decoration: underline;">Политикой конфиденциальности</a> 
            и соглашаетесь с условиями <a href="https://flashcards-ai.ru/oferta" target="_blank" style="color: #2e6c9e; text-decoration: underline;">Публичной оферты</a>.
            </small>
        </div>
        """, 
        unsafe_allow_html=True
    )
    st.stop()


# --- КНОПКА ВЫХОДА В БОКОВОЙ ПАНЕЛИ ---
st.sidebar.write(f"Вы вошли как: **{st.session_state.user_email}**")
if st.sidebar.button("Выйти из аккаунта"):
    st.session_state.user_email = None
    st.session_state.trial_expired = False
    st.rerun()


# --- НАСТРОЙКА ПРЕМИУМ-ДИЗАЙНА И СТИЛЕЙ КАРТОЧЕК ---
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

bg_css = ""
if os.path.exists("background.jpg"):
    try:
        bin_str = get_base64_of_bin_file("background.jpg")
        bg_css = f"background-image: url('data:image/jpeg;base64,{bin_str}') !important;"
    except Exception:
        bg_css = "background-color: #f5f0e8 !important;"
else:
    bg_css = "background-color: #f5f0e8 !important;"

st.markdown(f"""
<style>
html, body, [data-testid="stAppViewContainer"], .stApp {{
    {bg_css}
    background-size: cover !important;
    background-repeat: no-repeat !important;
    background-attachment: fixed !important;
    color: #2d3748 !important;
}}

h1, h2, h3, h4, h5, h6, p, span, label, li, div {{
    color: #2d3748 !important;
}}

[data-testid="stHeader"], header, [data-testid="stHeader"] > div {{
    background-color: transparent !important;
    background-image: none !important;
    box-shadow: none !important;
}}

[data-testid="stHeader"] svg, 
[data-testid="stHeader"] button, 
[data-testid="stHeader"] a,
[data-testid="stHeader"] span,
[data-testid="stHeader"] div,
[data-testid="stSidebarCollapsedControl"] button svg,
[data-testid="stSidebarCollapsedControl"] button {{
    color: #2d3748 !important;
    fill: #2d3748 !important;
}}

input, textarea, select, 
.stTextInput input, 
.stTextArea textarea,
[data-baseweb="base-input"],
[data-baseweb="textarea"],
[data-baseweb="select"] > div {{
    background-color: #ffffff !important;
    color: #2d3748 !important;
    -webkit-text-fill-color: #2d3748 !important;
    border: 1px solid #cbd5e0 !important;
}}

input::placeholder, textarea::placeholder {{
    color: #a0aec0 !important;
    -webkit-text-fill-color: #a0aec0 !important;
    opacity: 1 !important;
}}

[data-testid="stSidebar"], 
.stSidebar, 
[data-testid="stSidebar"] > div, 
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    background-color: #f5f0e8 !important;
    background-image: none !important;
}}

[data-testid="stSidebar"] h1, 
[data-testid="stSidebar"] h2, 
[data-testid="stSidebar"] h3, 
[data-testid="stSidebar"] p, 
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] small,
.stSidebar p,
.stSidebar label,
.stSidebar span {{
    color: #2d3748 !important;
}}

.card-front {{
    background-color: #e3b5b5 !important;
    border: 1px solid #d49f9f;
    border-radius: 12px;
    padding: 15px;
    text-align: center;
    min-height: 180px;
    max-height: 180px;
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
    color: #704b4b !important;
    margin-top: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 600;
}}

.card-back {{
    background-color: #ffffff !important;
    border: 1px solid #ebdcc5;
    border-radius: 12px;
    padding: 15px;
    min-height: 310px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.02), 0 1px 4px rgba(0,0,0,0.01);
    color: #2d3748 !important;
}}

.card-back div, 
.card-back span, 
.card-back p, 
.card-back b, 
.card-back i {{
    color: #2d3748 !important;
}}

.card-back .transcription-text {{
    color: #718096 !important;
}}

.card-back .collocations-text {{
    color: #2e6c9e !important;
}}

.card-back i {{
    color: #718096 !important;
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

# Выводим персонализированное приветствие по Имени из Тильды
st.write(f"👋 **Рада видеть вас, {st.session_state.get('user_name', 'Преподаватель')}!**")

if "cards" not in st.session_state:
    st.session_state.cards = []
if "flipped" not in st.session_state:
    st.session_state.flipped = {}


# --- ФУНКЦИЯ ПАРСИНГА СТАТЕЙ ПО ССЫЛКЕ ---
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


# --- БОКОВАЯ ПАНЕЛЬ НАСТРОЕК ---
with st.sidebar:
    st.header("⚙️ Настройки generation")
    model_option = st.selectbox("Нейросеть:", ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-1.5-flash"])
    source_type = st.radio("Что берем за основу?", ["📝 Текст / Отрывок статьи / Трэк субтитров", "🔗 Ссылка на веб-статью", "✍️ Готовый список слов"])
    student_level = st.selectbox("Уровень студента (CEFR):", ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"], index=2)
    
    if source_type != "✍️ Готовый список слов":
        num_cards = st.slider("Сколько карточек создать?", min_value=3, max_value=15, value=6)
    else:
        num_cards = 0


# --- МЯГКАЯ ПРОВЕРКА ОКОНЧАНИЯ ТРИАЛА ---
if st.session_state.get("trial_expired", False):
    st.warning("🛑 **Срок действия вашего бесплатного тест-драйва (3 дня) окончен.**")
    st.info("Вы можете изучать или экспортировать уже сгенерированные в этой сессии карточки ниже. Чтобы продолжить создавать новые уникальные колоды без ограничений, пожалуйста, выберите и оплатите тариф.")
    st.link_button("💳 Посмотреть тарифы и оплатить", "https://flashcards-ai.ru/#tarifs", type="primary")

else:
    # --- РАБОЧИЙ ИНТЕРФЕЙС ГЕНЕРАТОРА (ДОСТУПЕН, ЕСЛИ ТРИАЛ АКТИВЕН ИЛИ ТАРИФ ОПЛАЧЕН) ---
    if source_type == "📝 Текст / Отрывок статьи / Трэк субтитров":
        user_input = st.text_area("Вставьте сюда текст статьи или субтитры:", height=200)
    elif source_type == "🔗 Ссылка на веб-статью":
        user_input = st.text_input("Вставьте URL-ссылку на англоязычную статью:")
    else:
        user_input = st.text_area("Введите конкретные слова or фразы:", height=120)

    # --- КНОПКА ЗАПУСКА ГЕНЕРАЦИИ ГЛАВНАЯ ЛОГИКА ---
    if st.button("Создать карточки ✨", type="primary"):
        if not user_input.strip():
            st.warning("Пожалуйста, заполните поле ввода!")
        else:
            with st.spinner("Методист Gemini собирает лингвистические данные..."):
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
                        Ты профессиональный методист английского языка. Твой student имеет уровень {student_level}.
                        Создай обучающие карточки для следующих слов/фраз: {final_content}.
                        Верни строго валидный JSON-массив объектов со следующими ключами:
                        - "word": оригинальное слово на английском
                        - "transcription": фонетическая транскрипция в IPA (например, [ˈlɛt.ər] or [ˌekstrəlɪŋˈɡwɪstɪk])
                        - "translation": точный и красивый перевод на русский
                        - "explanation": дефиниция на английском языке под уровень {student_level}
                        - "collocations": 2-3 самых популярных словосочетания с этим словом на английском языке через запятую (например, 'write a letter, capital letter')
                        - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                        Верни ТОЛЬКО чистый JSON без маркдаун оберток.
                        """
                    else:
                        prompt = f"""
                        Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                        Выбери из предоставленного текста ровно {num_cards} важных слов под уровень {student_level} из материала: {final_content}
                        Верни строго валидный JSON-массив объектов со следующими ключами:
                        - "word": оригинальное слово на английском
                        - "transcription": фонетическая транскрипция в IPA (например, [ˈlɛt.ər] or [ˌekstrəlɪŋˈɡwɪstɪk])
                        - "translation": точный и красивый перевод на русский
                        - "explanation": дефиниция на английском языке под уровень {student_level}
                        - "collocations": 2-3 самых популярных словосочетания с этим словом на английском языке через запятую (например, 'write a letter, capital letter')
                        - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                        Верни ТОЛЬКО чистый JSON без маркдаун оберток.
                        """

                    response = model.generate_content(prompt)
                    text_response = response.text.strip()
                    
                    backtick_triple = chr(96) * 3
                    if backtick_triple in text_response:
                        chunks = text_response.split(backtick_triple)
                        for chunk in chunks:
                            clean_chunk = chunk.strip()
                            if clean_chunk.startswith("json"):
                                clean_chunk = clean_chunk[4:].strip()
                            if (clean_chunk.startswith("[") and clean_chunk.endswith("]")) or (clean_chunk.startswith("{") and clean_chunk.endswith("}")):
                                text_response = clean_chunk
                                break

                    text_response = text_response.strip()
                    cards_data = json.loads(text_response)
                    
                    st.session_state.cards = cards_data
                    st.session_state.flipped = {i: False for i in range(len(cards_data))}
                    
                    # =========================================================================
                    # 🔥 АВТОМАТИЧЕСКАЯ ЗАПИСЬ РЕЗУЛЬТАТОВ В ГУГЛ-ТАБЛИЦУ (REQUESTS И CARDS)
                    # =========================================================================
                    try:
                        gc_gen = get_gsheets_client()
                        sh_gen = gc_gen.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
                        now_gen_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        request_id = f"req-{int(datetime.now().timestamp())}"
                        source_snippet = user_input[:200] + "..." if len(user_input) > 200 else user_input
                        
                        requests_sheet = sh_gen.worksheet("Requests")
                        requests_sheet.append_row([
                            request_id, 
                            st.session_state.user_email, 
                            source_snippet, 
                            student_level, 
                            num_cards, 
                            "Completed", 
                            now_gen_str
                        ])
                        
                        cards_sheet = sh_gen.worksheet("Cards")
                        
                        for card in cards_data:
                            card_id = str(uuid.uuid4())
                            encoded_w = urllib.parse.quote(card['word'])
                            
                            audio_us = f"https://dict.youdao.com/dictvoice?audio={encoded_w}&type=2"
                            audio_uk = f"https://dict.youdao.com/dictvoice?audio={encoded_w}&type=1"
                            
                            cards_sheet.append_row([
                                card_id,
                                request_id,
                                card['word'],
                                card.get('transcription', ''),
                                card['translation'],
                                card['explanation'],
                                card.get('collocations', ''),
                                card['context'],
                                audio_us,
                                audio_uk,
                                st.session_state.user_email
                            ])
                    except Exception as sheets_err:
                        st.warning(f"⚠️ Карточки созданы, но произошел сбой сохранения в базу истории: {sheets_err}")
                    # =========================================================================
                    
                    st.success(f"Успешно! Создано карточек: {len(cards_data)}")
                except Exception as e:
                    st.error(f"Произошла ошибка при генерации: {e}.")

# --- ОТРИСОВКА И ВЫВОД РЕЗУЛЬТАТОВ НА ЭКРАН ---
if st.session_state.cards:
    st.write("---")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        anki_list = []
        for card in st.session_state.cards:
            encoded_w = urllib.parse.quote(card['word'])
            
            anki_back = (
                f"<div style='text-align:left; font-family:Arial,sans-serif; max-width:400px; margin:auto;'>"
                f"<h2 style='color:#2e6c9e; margin-bottom:2px; margin-top:0;'>{card['translation']}</h2>"
                f"<p style='font-size:13px; color:#a0aec0; margin-top:0; margin-bottom:10px;'>{card.get('transcription', '')}</p>"
                f"<p style='font-size:14px; color:#4a5568; margin-bottom:8px;'><b>Definition:</b> {card['explanation']}</p>"
                f"<p style='font-size:14px; color:#2d3748; margin-bottom:8px;'><b>Collocations:</b> <span style='color:#2e6c9e;'>{card.get('collocations', '')}</span></p>"
                f"<p style='font-size:14px; color:#718096; margin-bottom:12px;'><i>Context:</i> {card['context']}</p>"
                f"<hr style='border:none; border-top:1px solid #eee; margin:10px 0;' />"
                f"<div style='display:flex; gap:15px; justify-content:center;'>"
                f"<a href='https://dict.youdao.com/dictvoice?audio={encoded_w}&type=2' style='text-decoration:none; font-size:13px;'>🇺🇸 Play US</a>"
                f"<a href='https://dict.youdao.com/dictvoice?audio={encoded_w}&type=1' style='text-decoration:none; font-size:13px;'>🇬🇧 Play UK</a>"
                f"</div></div>"
            )
            anki_list.append({"Front": card['word'], "Back": anki_back})
            
        df = pd.DataFrame(anki_list)
        csv = df.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
        st.download_button(label="📱 Скачать файл для Anki / Quizlet", data=csv, file_name="gemini_anki_cards.txt", mime="text/plain")
        
    with col_exp2:
        print_mode = st.checkbox("🖨️ Включить режим для печати")

    if print_mode:
        for card in st.session_state.cards:
            print_html = f"""<div class="print-row">
<div class="print-col print-left">
    {card['word']}<br/>
    <span style="font-size:14px; font-weight:normal; color:#718096;">{card.get('transcription', '')}</span>
</div>
<div class="print-col">
<h4 style="color:#2e6c9e; margin-top:0; margin-bottom:5px;">{card['translation']}</h4>
<p style="font-size: 12px; color:#4a5568; margin:0 0 4px 0;"><strong>Definition:</strong> {card['explanation']}</p>
<p style="font-size: 12px; color:#2d3748; margin:0 0 4px 0;"><strong>Collocations:</strong> {card.get('collocations', '')}</p>
<p style="font-size: 12px; color:#4a5568; margin:0;"><strong>Context:</strong> {card['context']}</p>
</div>
</div>"""
            st.markdown(print_html, unsafe_allow_html=True)
            
    else:
        st.write("### 🎴 Интерактивный тренажер")
        cols = st.columns(3)
        for i, card in enumerate(st.session_state.cards):
            col_idx = i % 3
            with cols[col_idx]:
                is_flipped = st.session_state.flipped.get(i, False)
                encoded_word = urllib.parse.quote(card['word'])
                
                if not is_flipped:
                    front_html = f"""<div class="card-front">
<span class="card-front-title">{card['word']}</span>
<span class="card-front-subtitle">English Word</span>
</div>"""
                    st.markdown(front_html, unsafe_allow_html=True)
                    if st.button("🔄 Перевернуть", key=f"flip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = True
                        st.rerun()
                else:
                    back_html = f"""<div class="card-back">
<div style="text-align: center; margin-bottom: 5px;">
<span style="font-size: 13px; font-weight: bold; color: #4a2e2e !important; text-transform: uppercase;">{card['word']}</span><br/>
<span class="transcription-text" style="font-size: 11px; font-family: 'Arial', sans-serif;">{card.get('transcription', '')}</span>
</div>

<div style="font-size: 12px; margin-bottom: 5px; line-height: 1.3;">
<b>Definition:</b> {card['explanation']}
</div>

<div style="font-size: 12px; margin-bottom: 6px; line-height: 1.3;">
<b>Collocations:</b> <span class="collocations-text" style="font-weight: 500;">{card.get('collocations', '')}</span>
</div>

<div style="font-size: 12px; line-height: 1.3; margin-bottom: 10px;">
<b>Context:</b> <i>{card['context']}</i>
</div>

<details style="border: 1px solid #ebdcc5; border-radius: 6px; padding: 4px 8px; background: #fdfbf7; margin-bottom: 10px;">
<summary style="font-size: 12px; font-weight: bold; color: #1a365d; cursor: pointer; list-style: none; text-align: center; outline: none; user-select: none;">💬 Показать перевод</summary>
<div style="margin-top: 5px; font-size: 13.5px; font-weight: bold; color: #2e6c9e; text-align: center; border-top: 1px dashed #ebdcc5; padding-top: 4px;">
{card['translation']}
</div>
</details>

<div style="display: flex; gap: 8px; align-items: center; justify-content: space-between; background: #f7fafc; padding: 4px 8px; border-radius: 8px; border: 1px solid #edf2f7;">
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇺🇸</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=2" controls style="width: 100px; height: 28px; outline: none;"></audio>
    </div>
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇬🇧</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=1" controls style="width: 100px; height: 28px; outline: none;"></audio>
    </div>
</div>
</div>"""
                    st.markdown(back_html, unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
