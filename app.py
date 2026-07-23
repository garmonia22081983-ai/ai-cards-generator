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
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import extra_streamlit_components as stx
import time
import tempfile
import re

# Импортируем библиотеку субтитров YouTube (как запасной вариант)
try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

# --- АДРЕС ТВОЕГО ПРИЛОЖЕНИЯ (БЕЗ СЛЭША НА КОНЦЕ) ---
APP_URL = "https://ai-cards-generator.streamlit.app"

# --- СПИСОК EMAIL АДМИНИСТРАТОРОВ ---
ADMIN_EMAILS = [
    "garmonia.22081983@gmail.com"
]

# --- ИНИЦИАЛИЗАЦИЯ КУКИ-МЕНЕДЖЕРА ---
cookie_manager = stx.CookieManager(key="auth_cookie_manager")

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


# --- ФУНКЦИЯ ДЛЯ ПОДКЛЮЧЕНИЯ К ГУГЛ-ТАБЛИЦЕ ---
def get_gsheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)


# --- ФУНКЦИЯ ОТПРАВКИ EMAIL С КОДОМ (SMTP) ---
def send_otp_email(target_email, code):
    try:
        smtp_config = st.secrets["smtp"]
        msg = MIMEMultipart()
        msg['From'] = f"Flashcards AI <{smtp_config['email']}>"
        msg['To'] = target_email
        msg['Subject'] = f"{code} — Ваш код входа в Генератор Карточек"

        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #2d3748; padding: 20px;">
                <h2 style="color: #2e6c9e;">🔑 Вход в Генератор Карточек</h2>
                <p>Ваш одноразовый код для авторизации:</p>
                <div style="background-color: #f7fafc; border: 1px dashed #cbd5e0; padding: 15px; text-align: center; font-size: 28px; font-weight: bold; letter-spacing: 5px; color: #1a365d; border-radius: 8px; margin: 15px 0;">
                    {code}
                </div>
                <p style="font-size: 12px; color: #718096;">Код действителен в течение 10 минут. Если вы не запрашивали вход, просто проигнорируйте это письмо.</p>
            </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP_SSL(smtp_config['server'], int(smtp_config['port']))
        server.login(smtp_config['email'], smtp_config['password'])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Ошибка отправки письма: {e}")
        return False


# --- ФУНКЦИЯ ОПРЕДЕЛЕНИЯ ТАРИФА И ПОДСЧЕТА ИСПОЛЬЗОВАННЫХ КАРТОЧЕК ---
def get_user_tariff_and_usage(email, sh):
    clean_admin_emails = [a.strip().lower() for a in ADMIN_EMAILS]
    if email.lower() in clean_admin_emails:
        return "АДМИНИСТРАТОР", 999999, 0, datetime.now() - timedelta(days=365)

    tariff_name = "Пробный"
    max_cards = 45
    period_start = datetime.now() - timedelta(days=3)

    try:
        payments_sheet = sh.worksheet("Payments")
        payments_rows = payments_sheet.get_all_values()

        found_payment = None
        for p_row in reversed(payments_rows[1:]):
            if len(p_row) > 1 and p_row[1].strip().lower() == email.lower():
                product_name = p_row[5].strip() if len(p_row) > 5 else ""
                price_val = p_row[6].strip() if len(p_row) > 6 else ""
                if product_name or price_val:
                    found_payment = p_row
                    break

        if found_payment:
            product_str = found_payment[5].strip() if len(found_payment) > 5 else ""
            raw_d = found_payment[11].strip() if len(found_payment) > 11 else ""
            
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                try:
                    period_start = datetime.strptime(raw_d, fmt)
                    break
                except ValueError:
                    continue

            if "Максимум" in product_str or "1190" in str(found_payment):
                tariff_name = "Максимум"
                max_cards = 3000
            else:
                tariff_name = "Практик"
                max_cards = 300
        else:
            users_sheet = sh.worksheet("Users")
            u_rows = users_sheet.get_all_values()
            for u in u_rows[1:]:
                if len(u) > 0 and u[0].strip().lower() == email.lower():
                    reg_d_str = u[1].strip() if len(u) > 1 else ""
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                        try:
                            period_start = datetime.strptime(reg_d_str, fmt)
                            break
                        except ValueError:
                            continue
                    break

        filter_start = period_start - timedelta(days=1)
        requests_sheet = sh.worksheet("Requests")
        req_rows = requests_sheet.get_all_values()
        
        used_cards = 0
        for r in req_rows[1:]:
            if len(r) > 1 and r[1].strip().lower() == email.lower():
                raw_req_d = r[6].strip() if len(r) > 6 else (r[7].strip() if len(r) > 7 else "")
                req_d = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                    try:
                        req_d = datetime.strptime(raw_req_d, fmt)
                        break
                    except ValueError:
                        continue
                
                if req_d and req_d >= filter_start:
                    try:
                        card_val = r[4].strip() if len(r) > 4 else "0"
                        used_cards += int(card_val)
                    except ValueError:
                        pass

        return tariff_name, max_cards, used_cards, period_start

    except Exception:
        return tariff_name, max_cards, 0, period_start


# --- ВПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ИЗВЛЕЧЕНИЕ YOUTUBE VIDEO ID ---
def extract_youtube_id(url):
    pattern = r"(?:v=|\/([0-9A-Za-z_-]{11}).*|youtu\.be\/|shorts\/)([0-9A-Za-z_-]{11})"
    match = re.search(pattern, url)
    if match:
        return match.group(1) or match.group(2)
    return None


# --- ВПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПОЛУЧЕНИЕ СУБТИТРОВ С YOUTUBE (СПОЧАЛА SUPADATA, ЗАТЕМ FALLBACK) ---
def get_youtube_transcript(video_url):
    video_id = extract_youtube_id(video_url)
    if not video_id:
        return "Ошибка: Не удалось распознать ссылку на YouTube. Проверьте правильность URL."

    # 1. Пробуем извлечь через SupaData API (если есть ключ)
    supa_key = st.secrets.get("SUPADATA_API_KEY", None)
    if supa_key:
        try:
            supa_url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&text=true"
            headers = {"x-api-key": supa_key}
            res = requests.get(supa_url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "content" in data and data["content"]:
                    return data["content"]
                elif isinstance(data, list):
                    return " ".join([item.get("text", "") for item in data])
        except Exception:
            pass  # Переходим к обратному методу при сбое SupaData

    # 2. Резервный способ через youtube_transcript_api
    if not YouTubeTranscriptApi:
        return "Ошибка: Не удалось загрузить субтитры через SupaData, а резервная библиотека youtube-transcript-api не установлена."
    
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US', 'en-GB'])
        text = " ".join([item['text'] for item in transcript_list])
        return text
    except Exception as e:
        return f"Не удалось автоматически извлечь субтитры: {e}. Возможно, у видео отключены субтитры."


# --- СТИЛИ ПРИЛОЖЕНИЯ (UI/UX) ---
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
        bg_css = "background-color: #f8f6f0 !important;"
else:
    bg_css = "background-color: #f8f6f0 !important;"

st.markdown(f"""
<style>
/* Полностью убираем системную верхнюю шапку Streamlit */
[data-testid="stHeader"], header {{
    display: none !important;
}}

/* Убираем верхние отступы у основного контейнера и боковой панели */
[data-testid="stMainBlockContainer"],
.main .block-container,
[data-testid="stSidebarContent"] {{
    padding-top: 0rem !important;
    margin-top: 0rem !important;
}}

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

/* Карточка авторизации */
.auth-container {{
.auth-header {
    text-align: center;
    margin-bottom: 20px;
}

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
    border-radius: 8px !important;
}}

/* Фикс выпадающих списков (Selectbox popover) - предотвращаем обрезание элементов B2, C1, C2 */
div[data-baseweb="popover"] {{
    z-index: 999999 !important;
}}

div[data-baseweb="popover"] ul {{
    max-height: 320px !important;
    overflow-y: auto !important;
}}

/* Спускаем кнопку немного ниже и окрашиваем в синий цвет с белым текстом */
.stButton > button[kind="primary"] {{
    background-color: #2563eb !important;
    color: #ffffff !important;
    margin-top: 14px !important;
    border: none !important;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: #1d4ed8 !important;
    color: #ffffff !important;
}}

[data-testid="stSidebar"], 
.stSidebar, 
[data-testid="stSidebar"] > div, 
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
    background-color: #f4efe6 !important;
    background-image: none !important;
}}

.tariff-box {{
    background-color: #ffffff !important;
    border: 1px solid #ebdcc5;
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.03);
}}

/* Интерактивные карточки */
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
    box-shadow: 0 8px 16px rgba(138, 105, 105, 0.12);
}}

.card-front-title {{
    font-size: 22px;
    font-weight: bold;
    font-family: 'Georgia', serif;
    color: #4a2e2e !important;
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
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.02);
    color: #2d3748 !important;
}}

summary::-webkit-details-marker {{ display: none !important; }}
summary {{ list-style: none !important; }}

/* Стили печатных карточек */
.print-row-bw {{
    display: flex;
    border: 1px dashed #ccc;
    margin-bottom: 12px;
    page-break-inside: avoid;
    background-color: #ffffff;
}}

.print-row-kids {{
    display: flex;
    border: 2px solid #ffb74d;
    border-radius: 12px;
    margin-bottom: 12px;
    page-break-inside: avoid;
    background-color: #ffffff;
    overflow: hidden;
}}

.print-col-kids-left {{
    width: 45%;
    padding: 15px;
    background-color: #ffe0b2;
    border-right: 2px dashed #ffb74d;
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
}}

.print-col-kids-right {{
    width: 55%;
    padding: 15px;
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


# --- ФУНКЦИЯ ОТРИСОВКИ КВИЗА / ТЕСТИРОВАНИЯ ---
def render_quiz_section(cards_data, quiz_key_prefix="quiz"):
    st.markdown("### 🧪 Интерактивный тест по колоде")
    st.caption("Выберите один из вариантов перевода для каждого слова:")
    
    # Инициализация вопросов теста в сессии
    questions_key = f"{quiz_key_prefix}_questions"
    submitted_key = f"{quiz_key_prefix}_submitted"
    user_ans_key = f"{quiz_key_prefix}_answers"

    if questions_key not in st.session_state:
        all_translations = [c.get('translation', '').strip() for c in cards_data if c.get('translation')]
        all_translations = list(set([t for t in all_translations if t]))
        
        q_list = []
        for idx, card in enumerate(cards_data):
            correct_ans = card.get('translation', '').strip()
            other_ans = [t for t in all_translations if t != correct_ans]
            
            # Набираем 3 неправильных ответа из колоды (или фолбэк-заглушки при короткой колоде)
            distractors = random.sample(other_ans, min(3, len(other_ans)))
            fallback_pool = ["проверять", "выбирать", "создавать", "понимать", "изучать", "следовать"]
            while len(distractors) < 3:
                cand = random.choice(fallback_pool)
                if cand not in distractors and cand != correct_ans:
                    distractors.append(cand)
            
            opts = distractors[:3] + [correct_ans]
            random.shuffle(opts)
            
            q_list.append({
                "id": idx,
                "word": card.get('word', ''),
                "transcription": card.get('transcription', ''),
                "explanation": card.get('explanation', ''),
                "context": card.get('context', ''),
                "correct": correct_ans,
                "options": opts
            })
        st.session_state[questions_key] = q_list
        st.session_state[submitted_key] = False
        st.session_state[user_ans_key] = {}

    quiz_questions = st.session_state[questions_key]
    is_submitted = st.session_state.get(submitted_key, False)

    # Форма ответов
    with st.form(key=f"{quiz_key_prefix}_form"):
        user_choices = {}
        for q in quiz_questions:
            st.markdown(f"#### **{q['id'] + 1}. {q['word']}** <span style='font-size:14px; color:#718096;'>{q['transcription']}</span>", unsafe_allow_html=True)
            if q['explanation']:
                st.caption(f"💡 *Definition:* {q['explanation']}")
            
            default_val = st.session_state[user_ans_key].get(q['id'], None)
            choice = st.radio(
                f"Выберите перевод для «{q['word']}»:",
                q['options'],
                key=f"{quiz_key_prefix}_radio_{q['id']}",
                index=q['options'].index(default_val) if default_val in q['options'] else 0
            )
            user_choices[q['id']] = choice
            st.write("---")

        submit_btn = st.form_submit_button("✅ Завершить тест и проверить", type="primary", use_container_width=True)

    if submit_btn:
        st.session_state[submitted_key] = True
        st.session_state[user_ans_key] = user_choices
        st.rerun()

    # Результаты тестирования
    if is_submitted:
        score = 0
        total = len(quiz_questions)
        saved_choices = st.session_state.get(user_ans_key, {})

        st.markdown("### 📊 Результаты вашего теста")
        for q in quiz_questions:
            user_choice = saved_choices.get(q['id'])
            if user_choice == q['correct']:
                score += 1
                st.success(f"<b>{q['id'] + 1}. {q['word']}</b> — Верно! 🎉 ({q['correct']})", icon="✅")
            else:
                st.error(f"<b>{q['id'] + 1}. {q['word']}</b> — Ошибка. Ваш ответ: <i>{user_choice}</i>. Правильный ответ: <b>{q['correct']}</b>", icon="❌")

        percent = int((score / total) * 100) if total > 0 else 0
        st.progress(score / total if total > 0 else 0)
        
        if percent == 100:
            st.balloons()
            st.success(f"🏆 **Идеально! Ваш результат: {score} из {total} ({percent}%)**")
        elif percent >= 70:
            st.info(f"👍 **Отличный результат: {score} из {total} ({percent}%)**")
        else:
            st.warning(f"📖 **Ваш результат: {score} из {total} ({percent}%). Попробуйте повторить карточки!**")

        if st.button("🔄 Пройти тест еще раз", key=f"{quiz_key_prefix}_retake_btn", use_container_width=True):
            del st.session_state[questions_key]
            st.session_state[submitted_key] = False
            st.session_state[user_ans_key] = {}
            st.rerun()


# ==============================================================================
# 🎓 1. РЕЖИМ УЧЕНИКА (ПО ССЫЛКЕ ?deck=deck_id)
# ==============================================================================
student_deck_id = None
try:
    if hasattr(st, "query_params"):
        student_deck_id = st.query_params.get("deck", None)
    else:
        q_dict = st.experimental_get_query_params()
        student_deck_id = q_dict.get("deck", [None])[0]
        
    if isinstance(student_deck_id, list):
        student_deck_id = student_deck_id[0] if student_deck_id else None
except Exception:
    student_deck_id = None

if student_deck_id:
    st.title("🎴 Интерактивная колода карточек")
    
    try:
        gc_client = get_gsheets_client()
        sh_global = gc_client.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
        decks_sheet = sh_global.worksheet("Decks")
        rows = decks_sheet.get_all_values()
        
        found_deck = None
        for r in rows[1:]:
            if len(r) > 0 and r[0].strip() == str(student_deck_id).strip():
                found_deck = r
                break
                
        if not found_deck:
            st.error("🔴 Колода не найдена или была удалена преподавателем.")
            st.stop()
            
        deck_name = found_deck[2]
        deck_level = found_deck[3]
        cards_data = json.loads(found_deck[5])
        
        st.subheader(f"📚 {deck_name} (Уровень: {deck_level})")
        st.caption(f"Всего карточек: {len(cards_data)}")
        
        # Переключатель режимов занятий ученика
        student_mode = st.radio(
            "Выберите режим:",
            ["🎴 Интерактивные карточки", "🧪 Пройти тест", "🖨️ Версия для печати"],
            horizontal=True,
            key="student_mode_selector"
        )
        st.write("---")

        if student_mode == "🖨️ Версия для печати":
            for card in cards_data:
                print_html = f"""<div class="print-row-bw">
<div class="print-col print-left">{card.get('word', '')}<br/><span style="font-size:14px; font-weight:normal; color:#718096;">{card.get('transcription', '')}</span></div>
<div class="print-col">
<h4 style="color:#2e6c9e; margin-top:0; margin-bottom:5px;">{card.get('translation', '')}</h4>
<p style="font-size: 12px; color:#4a5568; margin:0 0 4px 0;"><strong>Definition:</strong> {card.get('explanation', '')}</p>
<p style="font-size: 12px; color:#2d3748; margin:0 0 4px 0;"><strong>Collocations:</strong> {card.get('collocations', '')}</p>
<p style="font-size: 12px; color:#4a5568; margin:0;"><strong>Context:</strong> {card.get('context', '')}</p>
</div>
</div>"""
                st.markdown(print_html, unsafe_allow_html=True)

        elif student_mode == "🧪 Пройти тест":
            render_quiz_section(cards_data, quiz_key_prefix=f"s_quiz_{student_deck_id}")

        else:
            # 🎴 Интерактивные карточки
            anki_list_student = []
            for card in cards_data:
                encoded_w = urllib.parse.quote(str(card.get('word', '')))
                anki_back = (
                    f"<div style='text-align:left; font-family:Arial,sans-serif; max-width:400px; margin:auto;'>"
                    f"<h2 style='color:#2e6c9e; margin-bottom:2px; margin-top:0;'>{card.get('translation', '')}</h2>"
                    f"<p style='font-size:13px; color:#a0aec0; margin-top:0; margin-bottom:10px;'>{card.get('transcription', '')}</p>"
                    f"<p style='font-size:14px; color:#4a5568; margin-bottom:8px;'><b>Definition:</b> {card.get('explanation', '')}</p>"
                    f"<p style='font-size:14px; color:#2d3748; margin-bottom:8px;'><b>Collocations:</b> <span style='color:#2e6c9e;'>{card.get('collocations', '')}</span></p>"
                    f"<p style='font-size:14px; color:#718096; margin-bottom:12px;'><i>Context:</i> {card.get('context', '')}</p>"
                    f"</div>"
                )
                anki_list_student.append({"Front": card.get('word', ''), "Back": anki_back})
                
            df_s = pd.DataFrame(anki_list_student)
            csv_s = df_s.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
            st.download_button(label="📱 Скачать файл для Anki / Quizlet", data=csv_s, file_name=f"{deck_name}_anki.txt", mime="text/plain", key="s_anki_btn")
            st.write("")

            if "student_flipped" not in st.session_state:
                st.session_state.student_flipped = {}
                
            cols = st.columns(3)
            for i, card in enumerate(cards_data):
                col_idx = i % 3
                with cols[col_idx]:
                    is_flipped = st.session_state.student_flipped.get(i, False)
                    encoded_word = urllib.parse.quote(str(card.get('word', '')))
                    
                    if not is_flipped:
                        front_html = f"""<div class="card-front">
<span class="card-front-title">{card.get('word', '')}</span>
<span class="card-front-subtitle">English Word</span>
</div>"""
                        st.markdown(front_html, unsafe_allow_html=True)
                        if st.button("🔄 Перевернуть", key=f"s_flip_{i}", use_container_width=True):
                            st.session_state.student_flipped[i] = True
                            st.rerun()
                    else:
                        back_html = f"""<div class="card-back">
<div style="text-align: center; margin-bottom: 5px;">
<span style="font-size: 13px; font-weight: bold; color: #4a2e2e !important; text-transform: uppercase;">{card.get('word', '')}</span><br/>
<span style="color: #718096; font-size: 11px;">{card.get('transcription', '')}</span>
</div>
<div style="font-size: 12px; margin-bottom: 5px;"><b>Definition:</b> {card.get('explanation', '')}</div>
<div style="font-size: 12px; margin-bottom: 6px;"><b>Collocations:</b> <span style="color: #2e6c9e;">{card.get('collocations', '')}</span></div>
<div style="font-size: 12px; margin-bottom: 10px;"><b>Context:</b> <i>{card.get('context', '')}</i></div>
<details style="border: 1px solid #ebdcc5; border-radius: 6px; padding: 4px 8px; background: #fdfbf7; margin-bottom: 10px;">
<summary style="font-size: 12px; font-weight: bold; color: #1a365d; cursor: pointer; text-align: center;">💬 Показать перевод</summary>
<div style="margin-top: 5px; font-size: 13.5px; font-weight: bold; color: #2e6c9e; text-align: center; border-top: 1px dashed #ebdcc5; padding-top: 4px;">
{card.get('translation', '')}
</div>
</details>
<div style="display: flex; gap: 8px; align-items: center; justify-content: space-between; background: #f7fafc; padding: 4px 8px; border-radius: 8px;">
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇺🇸</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=2" controls style="width: 100px; height: 28px;"></audio>
    </div>
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇬🇧</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=1" controls style="width: 100px; height: 28px;"></audio>
    </div>
</div>
</div>"""
                        st.markdown(back_html, unsafe_allow_html=True)
                        if st.button("👈 Показать слово", key=f"s_unflip_{i}", use_container_width=True):
                            st.session_state.student_flipped[i] = False
                            st.rerun()

    except Exception as e:
        st.error(f"Ошибка загрузки колоды: {e}")

    st.stop()


# ==============================================================================
# 👩‍🏫 2. ИНТЕРФЕЙС УЧИТЕЛЯ (АВТОРИЗАЦИЯ, ГЕНЕРАЦИЯ, СОХРАНЕНИЕ)
# ==============================================================================

# --- ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННЫХ СЕССИИ ---
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_name" not in st.session_state:
    st.session_state.user_name = "Преподаватель"
if "trial_expired" not in st.session_state:
    st.session_state.trial_expired = False
if "otp_sent" not in st.session_state:
    st.session_state.otp_sent = False
if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = None
if "pending_email" not in st.session_state:
    st.session_state.pending_email = None
if "logout_requested" not in st.session_state:
    st.session_state.logout_requested = False


# --- ПРОВЕРКА КУКИ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ ---
saved_email = cookie_manager.get(cookie="auth_email")

if not saved_email:
    st.session_state.logout_requested = False

if saved_email and not st.session_state.user_email and not st.session_state.logout_requested:
    email = str(saved_email).strip().lower()
    clean_admin_emails = [a.strip().lower() for a in ADMIN_EMAILS]
    
    st.session_state.user_email = email
    
    if email in clean_admin_emails:
        st.session_state.user_name = "Администратор"
        st.session_state.trial_expired = False
    else:
        try:
            gc = get_gsheets_client()
            sh = gc.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
            
            users_sheet = sh.worksheet("Users")
            rows = users_sheet.get_all_values()
            
            user_row = None
            for i, r in enumerate(rows[1:], start=2):
                if len(r) > 0 and r[0].strip().lower() == email:
                    user_row = (i, r)
                    break
            
            if user_row:
                row_num, row_data = user_row
                reg_date_str = row_data[1]
                status = row_data[2] if len(row_data) > 2 else "active"
                st.session_state.user_name = row_data[3] if len(row_data) > 3 else "Преподаватель"
                
                if status == "paid":
                    last_pay_date = datetime.now()
                    try:
                        payments_sheet = sh.worksheet("Payments")
                        payments_rows = payments_sheet.get_all_values()
                        for p_row in reversed(payments_rows[1:]):
                            if len(p_row) > 1 and p_row[1].strip().lower() == email:
                                raw_d = p_row[11].strip() if len(p_row) > 11 else ""
                                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                                    try:
                                        last_pay_date = datetime.strptime(raw_d, fmt)
                                        break
                                    except ValueError:
                                        continue
                                break
                    except Exception:
                        pass
                    
                    if datetime.now() > (last_pay_date + timedelta(days=30)):
                        st.session_state.trial_expired = True
                    else:
                        st.session_state.trial_expired = False
                else:
                    reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() > (reg_date + timedelta(days=3)):  # 3 дня доступа на генерацию
                        st.session_state.trial_expired = True
                    else:
                        st.session_state.trial_expired = False
        except Exception:
            pass


# --- БЛОК АВТОРИЗАЦИИ ПО EMAIL И КОДУ ---
if not st.session_state.user_email:
    col_a1, col_a2, col_a3 = st.columns([1, 1.8, 1])
    with col_a2:
        st.markdown(
            """
            <div class="auth-container">
                <div class="auth-header">
                    <h2 style="margin-bottom: 5px; color: #1a365d;">🎓 Flashcards AI</h2>
                    <p style="color: #4a5568; font-size: 16px; font-weight: 600; margin-top: 0;">Умный генератор двусторонних карточек</p>
                </div>
            """, 
            unsafe_allow_html=True
        )
        
        if not st.session_state.otp_sent:
            st.write("**Вход в Личный Кабинет**")
            email_input = st.text_input("Ваш Email:", placeholder="example@gmail.com")
            
            if st.button("Получить код входа", type="primary", use_container_width=True):
                if "@" not in email_input or "." not in email_input:
                    st.error("Пожалуйста, введите корректный адрес почты.")
                else:
                    email = email_input.strip().lower()
                    clean_admin_emails = [a.strip().lower() for a in ADMIN_EMAILS]
                    
                    if email in clean_admin_emails:
                        user_exists = True
                    else:
                        try:
                            gc = get_gsheets_client()
                            sh = gc.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
                            
                            users_sheet = sh.worksheet("Users")
                            users_rows = users_sheet.get_all_values()
                            
                            payments_sheet = sh.worksheet("Payments")
                            payments_rows = payments_sheet.get_all_values()
                            
                            user_exists = False
                            for r in users_rows[1:]:
                                if len(r) > 0 and r[0].strip().lower() == email:
                                    user_exists = True
                                    break
                            
                            if not user_exists:
                                for p in payments_rows[1:]:
                                    if len(p) > 1 and p[1].strip().lower() == email:
                                        user_exists = True
                                        break
                        except Exception as e:
                            st.error(f"Ошибка базы данных: {e}")
                            user_exists = False
                    
                    if not user_exists:
                        st.error("🔴 Email не найден в системе.")
                        st.link_button("👉 Получить 3 дня тест-драйва на flashcards-ai.ru", "https://flashcards-ai.ru", type="primary", use_container_width=True)
                    else:
                        otp_code = str(random.randint(100000, 999999))
                        with st.spinner("Отправка одноразового кода..."):
                            if send_otp_email(email, otp_code):
                                st.session_state.generated_otp = otp_code
                                st.session_state.pending_email = email
                                st.session_state.otp_sent = True
                                st.rerun()

        else:
            st.info(f"📩 Код отправлен на **{st.session_state.pending_email}**.")
            st.caption("Проверьте папку «Спам», если письма нет в течение минуты.")
            
            user_code = st.text_input("6-значный код из письма:", max_chars=6)
            
            if st.button("Подтвердить и войти", type="primary", use_container_width=True):
                if user_code.strip() == st.session_state.generated_otp:
                    email = st.session_state.pending_email
                    clean_admin_emails = [a.strip().lower() for a in ADMIN_EMAILS]
                    
                    st.session_state.user_email = email
                    st.session_state.logout_requested = False
                    
                    if email in clean_admin_emails:
                        cookie_manager.set("auth_email", email, expires_at=datetime.now() + timedelta(days=365))
                        st.session_state.user_name = "Администратор"
                        st.session_state.trial_expired = False
                        st.success("Успешный вход!")
                        time.sleep(0.3)
                        st.rerun()
                    
                    try:
                        gc = get_gsheets_client()
                        sh = gc.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
                        
                        users_sheet = sh.worksheet("Users")
                        rows = users_sheet.get_all_values()
                        
                        user_row = None
                        for i, r in enumerate(rows[1:], start=2):
                            if len(r) > 0 and r[0].strip().lower() == email:
                                user_row = (i, r)
                                break
                        
                        if not user_row:
                            payments_sheet = sh.worksheet("Payments")
                            p_rows = payments_sheet.get_all_values()
                            
                            found_p = None
                            for p in reversed(p_rows[1:]):
                                if len(p) > 1 and p[1].strip().lower() == email:
                                    found_p = p
                                    break
                            
                            if found_p:
                                user_name = found_p[0].strip() if found_p[0].strip() else "Преподаватель"
                                product_name = found_p[5].strip() if len(found_p) > 5 else ""
                                price_val = found_p[6].strip() if len(found_p) > 6 else ""
                                reg_time_str = found_p[11].strip() if len(found_p) > 11 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                new_status = "paid" if (product_name or price_val) else "active"
                                users_sheet.append_row([email, reg_time_str, new_status, user_name])
                                
                                st.session_state.user_name = user_name
                                exp_date = datetime.now() + timedelta(days=30 if new_status == "paid" else 3)
                                st.session_state.trial_expired = False
                                cookie_manager.set("auth_email", email, expires_at=datetime.now() + timedelta(days=365))
                        else:
                            row_num, row_data = user_row
                            reg_date_str = row_data[1]
                            status = row_data[2] if len(row_data) > 2 else "active"
                            st.session_state.user_name = row_data[3] if len(row_data) > 3 else "Преподаватель"
                            
                            if status == "blocked":
                                st.error("🚫 Ваш доступ заблокирован.")
                                st.stop()
                                
                            if status == "paid":
                                last_pay_date = datetime.now()
                                try:
                                    payments_sheet = sh.worksheet("Payments")
                                    payments_rows = payments_sheet.get_all_values()
                                    for p_row in reversed(payments_rows[1:]):
                                        if len(p_row) > 1 and p_row[1].strip().lower() == email:
                                            raw_d = p_row[11].strip() if len(p_row) > 11 else ""
                                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                                                try:
                                                    last_pay_date = datetime.strptime(raw_d, fmt)
                                                    break
                                                except ValueError:
                                                    continue
                                            break
                                except Exception:
                                    pass
                                
                                exp_date = last_pay_date + timedelta(days=30)
                                if datetime.now() > exp_date:
                                    st.session_state.trial_expired = True
                                else:
                                    st.session_state.trial_expired = False
                                
                                cookie_manager.set("auth_email", email, expires_at=datetime.now() + timedelta(days=365))
                            else:
                                reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d %H:%M:%S")
                                exp_date = reg_date + timedelta(days=3)  # 3 дня доступа
                                if datetime.now() > exp_date:
                                    st.session_state.trial_expired = True
                                else:
                                    st.session_state.trial_expired = False
                                
                                cookie_manager.set("auth_email", email, expires_at=datetime.now() + timedelta(days=365))
                                    
                        st.success("Успешный вход!")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка авторизации: {e}")
                else:
                    st.error("Неверный код.")
                    
            if st.button("Ввести другой Email", use_container_width=True):
                st.session_state.otp_sent = False
                st.session_state.generated_otp = None
                st.session_state.pending_email = None
                st.rerun()

        st.markdown(
            """
            <div style="margin-top: 20px; text-align: center;">
                <small style="color: #718096;">
                Входя в систему, вы принимаете <a href="https://flashcards-ai.ru/privacy" target="_blank" style="color: #2e6c9e;">Политику конфиденциальности</a>.
                </small>
            </div>
            </div>
            """, 
            unsafe_allow_html=True
        )
    st.stop()


# --- КНОПКА ВЫХОДА В БОКОВОЙ ПАНЕЛИ ---
st.sidebar.write(f"Вы вошли как: **{st.session_state.user_email}**")
if st.sidebar.button("Выйти из аккаунта"):
    cookie_manager.delete("auth_email")
    st.session_state.user_email = None
    st.session_state.otp_sent = False
    st.session_state.trial_expired = False
    st.session_state.logout_requested = True
    time.sleep(0.3)
    st.rerun()

st.title("🎴 Умный Генератор Двусторонних Карточек")
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


# --- ЗАГРУЗКА ДАННЫХ О ТАРИФЕ И ЛИМИТАХ ---
gc_client = get_gsheets_client()
sh_global = gc_client.open_by_key("1YTuOcYeNTecheAn57L8TzCq0bXolYMVOa94MuMGoj88")
tariff_name, max_cards, used_cards, period_start = get_user_tariff_and_usage(st.session_state.user_email, sh_global)


# --- БОКОВАЯ ПАНЕЛЬ НАСТРОЕК ---
with st.sidebar:
    st.header("⚙️ Настройки generation")
    
    # Выбор модели доступен только для администратора
    clean_admin_emails = [a.strip().lower() for a in ADMIN_EMAILS]
    is_admin = st.session_state.user_email and (st.session_state.user_email.strip().lower() in clean_admin_emails)
    
    if is_admin:
        model_option = st.selectbox("Нейросеть:", ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.0-flash"])
    else:
        model_option = "gemini-3.5-flash"
    
    source_type = st.radio(
        "Что берем за основу?", 
        [
            "✍️ Готовый список слов",
            "📝 Текст / Отрывок статьи / Субтитры", 
            "🎬 Ссылка на YouTube",
            "📁 Видео или аудио файл (до 5 мин)",
            "🔗 Ссылка на веб-статью"
        ],
        index=0
    )
    
    student_level = st.selectbox("Уровень студента (CEFR):", ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"], index=2)
    
    if source_type != "✍️ Готовый список слов":
        num_cards = st.slider("Сколько карточек создать?", min_value=3, max_value=15, value=6)
    else:
        num_cards = 0


# --- ПРОВЕРКА СОСТОЯНИЯ ПОДПИСКИ И ЛИМИТОВ ---
is_expired = st.session_state.get("trial_expired", False)
is_limit_reached = (tariff_name != "АДМИНИСТРАТОР") and (used_cards >= max_cards)

button_disabled = is_expired or is_limit_reached

if is_expired:
    st.warning("🛑 **Срок действия вашей подписки окончен.**")
    st.info("Вы можете изучать или экспортировать ранее созданные карточки. Чтобы продолжить создавать новые колоды, пожалуйста, продлите тариф.")
    st.link_button("💳 Посмотреть тарифы и продлить", "https://flashcards-ai.ru/#tarifs", type="primary")

elif is_limit_reached:
    st.warning(f"🛑 **Вы исчерпали лимит карточек ({max_cards} шт.) по тарифу «{tariff_name}».**")
    st.info("Вы можете изучать или экспортировать ранее созданные карточки. Чтобы увеличить лимит или перейти на следующий тариф, нажмите кнопку ниже.")
    st.link_button("💳 Повысить тариф / Продлить", "https://flashcards-ai.ru/#tarifs", type="primary")


# --- РАБОЧИЙ ИНТЕРФЕЙС ГЕНЕРАТОРА ---
col_main, col_stats = st.columns([1.6, 1], gap="medium")

user_input = ""
uploaded_file_obj = None

with col_main:
    if source_type == "✍️ Готовый список слов":
        user_input = st.text_area("Введите конкретные слова или фразы через запятую:", height=120)
    elif source_type == "📝 Текст / Отрывок статьи / Субтитры":
        user_input = st.text_area("Вставьте сюда текст статьи, субтитры или диалог:", height=200)
    elif source_type == "🎬 Ссылка на YouTube":
        user_input = st.text_input("Вставьте URL-ссылку на YouTube видео (например, https://www.youtube.com/watch?v=...):")
    elif source_type == "📁 Видео или аудио файл (до 5 мин)":
        uploaded_file_obj = st.file_uploader("Загрузите видео или аудио фрагмент (до 5 минут, макс. 30 МБ):", type=["mp3", "mp4", "wav", "m4a", "mov"])
        st.caption("Поддерживаются форматы: MP4, MP3, WAV, M4A, MOV. Gemini распознает английскую речь напрямую.")
    elif source_type == "🔗 Ссылка на веб-статью":
        user_input = st.text_input("Вставьте URL-ссылку на англоязычную статью:")

    generate_click = st.button(
        "Создать карточки ✨", 
        type="primary", 
        disabled=button_disabled
    )

with col_stats:
    st.markdown(
        f"""
        <div class="tariff-box">
            <h3 style="margin-top:0; font-size:18px;">📊 Твой тариф и лимиты</h3>
            <p style="color:#718096; font-size:13px; margin-bottom:12px;">Тариф: <b>{tariff_name.upper()}</b></p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    if tariff_name == "АДМИНИСТРАТОР":
        st.success("👑 Безлимитный доступ")
    else:
        progress_val = min(float(used_cards) / float(max_cards), 1.0)
        st.progress(progress_val)
        remaining_cards = max(0, max_cards - used_cards)
        st.write(f"Создано: **{used_cards}** из **{max_cards}** карточек")
        st.caption(f"Осталось: **{remaining_cards}** карточек")

    st.write("---")
    # --- БЛОК МОИ СОХРАНЕННЫЕ КОЛОДЫ В ПРАВОЙ КОЛОНКЕ ---
    st.markdown("<h4 style='font-size: 18px; font-weight: bold; margin-top: 5px; margin-bottom: 10px; color: #1a365d;'>📂 Мои сохраненные колоды</h4>", unsafe_allow_html=True)
    try:
        decks_sheet = sh_global.worksheet("Decks")
        d_rows = decks_sheet.get_all_values()
        my_decks = [r for r in d_rows[1:] if len(r) > 1 and r[1].strip().lower() == st.session_state.user_email.lower()]
        
        if not my_decks:
            st.caption("У вас пока нет сохраненных колод.")
        else:
            search_q = st.text_input("🔍 Поиск колоды:", key="deck_search_query", placeholder="Название...").strip().lower()
            show_all = st.checkbox("Показать все колоды", key="show_all_my_decks")
            
            all_my_decks_rev = list(reversed(my_decks))
            
            if search_q:
                filtered_decks = [d for d in all_my_decks_rev if search_q in d[2].lower()]
            else:
                filtered_decks = all_my_decks_rev
                
            display_decks = filtered_decks if (show_all or search_q) else filtered_decks[:5]
            
            if not search_q and len(my_decks) > 5 and not show_all:
                st.caption(f"Показано последние 5 из {len(my_decks)}.")
            
            for d in display_decks:
                d_id = d[0]
                d_name = d[2]
                d_level = d[3]
                d_cards_json = d[5]
                d_created_str = d[6] if len(d) > 6 else ""
                
                # Проверка заморозки колоды (7 дней для Пробного, 60 дней для остальных)
                is_frozen = False
                max_freeze_days = 7 if tariff_name == "Пробный" else 60
                if d_created_str:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
                        try:
                            created_dt = datetime.strptime(d_created_str.strip(), fmt)
                            if datetime.now() > (created_dt + timedelta(days=max_freeze_days)) and tariff_name != "АДМИНИСТРАТОР":
                                is_frozen = True
                            break
                        except ValueError:
                            continue

                if is_frozen:
                    st.write(f"❄️ **{d_name}** ({d_level}) — *Заморожена*")
                    st.warning(f"❄️ **Колода заморожена**\nСрок хранения колоды истёк (прошло {max_freeze_days} дн.). Продлите тариф или перейдите на тариф «Практик» или «Максимум», чтобы разблокировать доступ.")
                    st.link_button("💳 Продлить тариф", "https://flashcards-ai.ru/#tarifs", key=f"freeze_renew_{d_id}")
                else:
                    st.write(f"**{d_name}** ({d_level})")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("👁️ Открыть", key=f"open_{d_id}", use_container_width=True):
                            st.session_state.cards = json.loads(d_cards_json)
                            st.session_state.flipped = {i: False for i in range(len(st.session_state.cards))}
                            st.rerun()
                    with c2:
                        if st.button("📋 Ссылка", key=f"copylink_btn_{d_id}", use_container_width=True):
                            st.session_state[f"show_link_{d_id}"] = not st.session_state.get(f"show_link_{d_id}", False)
                            
                    if st.session_state.get(f"show_link_{d_id}", False):
                        student_link = f"{APP_URL}?deck={d_id}"
                        st.code(student_link, language=None)
                    
                st.markdown("<hr style='margin: 8px 0;'>", unsafe_allow_html=True)
    except Exception:
        st.caption("Не удалось загрузить список колод.")

# --- ОБРАБОТКА НАЖАТИЯ КНОПКИ ГЕНЕРАЦИИ ---
if generate_click:
    is_valid_input = False
    if source_type == "📁 Видео или аудио файл (до 5 мин)":
        is_valid_input = (uploaded_file_obj is not None)
    else:
        is_valid_input = bool(user_input.strip())

    if not is_valid_input:
        st.warning("Пожалуйста, заполните поле ввода или загрузите файл!")
    else:
        actual_requested = num_cards
        if source_type == "✍️ Готовый список слов":
            words_list = [w.strip() for w in user_input.replace("\n", ",").split(",") if w.strip()]
            actual_requested = len(words_list)

        if tariff_name != "АДМИНИСТРАТОР" and (used_cards + actual_requested) > max_cards:
            rem = max(0, max_cards - used_cards)
            st.error(f"🛑 Превышен лимит тарифа! У вас осталось **{rem}** карточек, а вы пытаетесь сгенерировать **{actual_requested}**.")
            st.info("Пожалуйста, уменьшите количество карточек в слайдере или перейдите на более старший тариф.")
            st.link_button("💳 Посмотреть тарифы", "https://flashcards-ai.ru/#tarifs")
        else:
            with st.spinner("Методист Gemini обрабатывает материал и собирает карточки..."):
                try:
                    final_prompt_content = ""
                    gemini_uploaded_file = None
                    temp_file_path = None
                    source_url_to_save = user_input.strip()

                    # 1. YOUTUBE ССЫЛКА
                    if source_type == "🎬 Ссылка на YouTube":
                        yt_transcript = get_youtube_transcript(user_input.strip())
                        if "Ошибка" in yt_transcript or "Не удалось" in yt_transcript:
                            st.error(yt_transcript)
                            st.info("💡 Совет: если у видео нет субтитров на YouTube, вы можете вырезать нужный фрагмент и загрузить его через опцию «📁 Видео или аудио файл».")
                            st.stop()
                        final_prompt_content = yt_transcript

                    # 2. МЕДИАФАЙЛ (MP4 / MP3)
                    elif source_type == "📁 Видео или аудио файл (до 5 мин)":
                        if uploaded_file_obj.size > 30 * 1024 * 1024:
                            st.error("🛑 Файл слишком большой (превышает 30 МБ)! Пожалуйста, вырежьте короткий фрагмент длительностью до 5 минут.")
                            st.stop()
                            
                        file_ext = os.path.splitext(uploaded_file_obj.name)[1]
                        source_url_to_save = f"Файл: {uploaded_file_obj.name} ({round(uploaded_file_obj.size/1024/1024, 1)} MB)"
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                            tmp.write(uploaded_file_obj.read())
                            temp_file_path = tmp.name
                            
                        gemini_uploaded_file = genai.upload_file(path=temp_file_path)

                    # 3. ВЕБ-СТАТЬЯ
                    elif source_type == "🔗 Ссылка на веб-статью":
                        scraped_text = extract_text_from_url(user_input.strip())
                        if "Ошибка" in scraped_text or "Не удалось" in scraped_text:
                            st.error(scraped_text)
                            st.stop()
                        final_prompt_content = scraped_text
                    
                    else:
                        final_prompt_content = user_input.strip()

                    model = genai.GenerativeModel(model_option)
                    
                    if source_type == "✍️ Готовый список слов":
                        prompt_text = f"""
                        Ты профессиональный методист английского языка. Твой student имеет уровень {student_level}.
                        Создай обучающие карточки для следующих слов/фраз: {final_prompt_content}.
                        Верни строго валидный JSON-массив объектов со следующими ключами:
                        - "word": оригинальное слово на английском
                        - "transcription": фонетическая транскрипция в IPA
                        - "translation": точный и красивый перевод на русский
                        - "explanation": дефиниция на английском языке под уровень {student_level}
                        - "collocations": 2-3 самых популярных словосочетания с этим словом на английском языке через запятую
                        - "context": ОДНО контекстное предложение на английском под уровень {student_level}.
                        Верни ТОЛЬКО чистый JSON без маркдаун оберток.
                        """
                    else:
                        prompt_text = f"""
                        Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                        Проанализируй предоставленный материал и выбери из него ровно {num_cards} самых важных полезных фраз или слов под уровень {student_level}.
                        
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
                    
                    # --- СОХРАНЕНИЕ В ИСТОРИЮ (ВКЛАДКА REQUESTS С ИСТОЧНИКОМ) ---
                    try:
                        now_gen_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        request_id = f"req-{int(datetime.now().timestamp())}"
                        
                        requests_sheet = sh_global.worksheet("Requests")
                        requests_sheet.append_row([
                            request_id, 
                            st.session_state.user_email, 
                            source_type,
                            source_url_to_save[:250], 
                            student_level, 
                            len(cards_data), 
                            "Completed", 
                            now_gen_str
                        ])
                        
                        cards_sheet = sh_global.worksheet("Cards")
                        for card in cards_data:
                            card_id = str(uuid.uuid4())
                            encoded_w = urllib.parse.quote(card['word'])
                            audio_us = f"https://dict.youdao.com/dictvoice?audio={encoded_w}&type=2"
                            audio_uk = f"https://dict.youdao.com/dictvoice?audio={encoded_w}&type=1"
                            
                            cards_sheet.append_row([
                                card_id, request_id, card['word'], card.get('transcription', ''),
                                card['translation'], card['explanation'], card.get('collocations', ''),
                                card['context'], audio_us, audio_uk, st.session_state.user_email
                            ])
                    except Exception as sheets_err:
                        st.warning(f"⚠️ Карточки созданы, но произошел сбой сохранения в историю: {sheets_err}")
                    
                    if gemini_uploaded_file:
                        try: genai.delete_file(gemini_uploaded_file.name)
                        except Exception: pass
                    if temp_file_path and os.path.exists(temp_file_path):
                        try: os.remove(temp_file_path)
                        except Exception: pass

                    st.success(f"Успешно! Создано карточек: {len(cards_data)}")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Произошла ошибка при генерации: {e}.")


# --- ОТРИСОВКА, РЕДАКТИРОВАНИЕ И СОХРАНЕНИЕ КАРТОЧЕК ---
if st.session_state.cards:
    st.write("---")
    
    # ✏️ БЛОК РЕДАКТИРОВАНИЯ
    with st.expander("✏️ Отредактировать текст карточек (нажмите, чтобы изменить перевод или контекст)", expanded=False):
        st.caption("Все правки в таблице ниже мгновенно обновят интерактивные карточки, Anki-файл и версию для печати:")
        
        df_edit = pd.DataFrame(st.session_state.cards)
        required_cols = ["word", "translation", "transcription", "explanation", "collocations", "context"]
        for col in required_cols:
            if col not in df_edit.columns:
                df_edit[col] = ""
        
        df_edit = df_edit[required_cols]
        
        edited_df = st.data_editor(
            df_edit,
            num_rows="dynamic",
            use_container_width=True,
            key="cards_data_editor",
            column_config={
                "word": st.column_config.TextColumn("Слово / Фраза (EN)", required=True),
                "translation": st.column_config.TextColumn("Перевод (RU)", required=True),
                "transcription": st.column_config.TextColumn("Транскрипция"),
                "explanation": st.column_config.TextColumn("Дефиниция (EN)"),
                "collocations": st.column_config.TextColumn("Коллокации"),
                "context": st.column_config.TextColumn("Контекстное предложение"),
            }
        )
        st.session_state.cards = edited_df.to_dict(orient="records")

    # 💾 БЛОК СОХРАНЕНИЯ КОЛОДЫ
    st.markdown("### 💾 Сохранить колоду в личный кабинет")
    col_save1, col_save2 = st.columns([2, 1])
    with col_save1:
        default_deck_title = f"Колода {student_level} — {datetime.now().strftime('%d.%m.%Y')}"
        deck_title_input = st.text_input("Название колоды:", value=default_deck_title)
    with col_save2:
        st.write(" ")
        st.write(" ")
        if st.button("💾 Сохранить колоду", type="primary"):
            try:
                decks_sheet = sh_global.worksheet("Decks")
                new_deck_id = f"deck-{int(datetime.now().timestamp())}"
                cards_json_str = json.dumps(st.session_state.cards, ensure_ascii=False)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                decks_sheet.append_row([
                    new_deck_id,
                    st.session_state.user_email,
                    deck_title_input.strip(),
                    student_level,
                    len(st.session_state.cards),
                    cards_json_str,
                    now_str
                ])
                
                share_url = f"{APP_URL}?deck={new_deck_id}"
                st.success(f"✅ Колода «{deck_title_input}» успешно сохранена!")
                st.write("🔗 **Ссылка для отправки ученикам:**")
                st.code(share_url, language=None)
            except Exception as save_err:
                st.error(f"Ошибка сохранения колоды: {save_err}")

    st.write("---")

    # Переключатель режимов в интерфейсе преподавателя
    teacher_view_mode = st.radio(
        "Выберите режим предпросмотра:",
        ["🎴 Интерактивный тренажер", "🧪 Пройти тест", "🖨️ Режим для печати"],
        horizontal=True,
        key="teacher_view_mode_selector"
    )
    st.write("")

    if teacher_view_mode == "🖨️ Режим для печати":
        # 🌟 НАСТРОЙКИ ПЕЧАТИ
        is_max_tariff = (tariff_name in ["Максимум", "АДМИНИСТРАТОР"])
        custom_print_teacher = ""
        custom_print_note = ""
        print_style = "🖨️ Черно-белая (Экономный режим)"

        if is_max_tariff:
            with st.expander("👑 Настройка брендирования распечатки (Тариф Максимум)", expanded=True):
                print_style = st.selectbox(
                    "Выберите стиль оформления:", 
                    [
                        "🖨️ Черно-белая (Экономный режим)", 
                        "🎨 Цветная детская (Игровая / Пастельная)", 
                        "💼 Цветная стильная (Премиум)"
                    ]
                )
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    custom_print_teacher = st.text_input("Имя преподавателя / Название школы:", placeholder="English Class with Anna").strip()
                with col_p2:
                    custom_print_note = st.text_input("Заметка / Задание для ученика:", placeholder="Задание: Составьте предложение с каждым словом").strip()

        if "детская" in print_style and is_max_tariff:
            teacher_title = custom_print_teacher if custom_print_teacher else "English Class"
            note_str = f"<p style='margin:4px 0 0 0; color:#5d4037; font-size:12px;'><b>Задание:</b> {custom_print_note}</p>" if custom_print_note else ""
            st.markdown(
                f"""
                <div style="background: #fff3e0; border: 2px dashed #ffb74d; border-radius: 12px; padding: 12px 18px; margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 16px; font-weight: bold; color: #d84315;">🦁 {teacher_title}</span>
                        <span style="font-size: 12px; color: #666; font-weight: 500;">Name: ______________________ | Date: ___/___/2026</span>
                    </div>
                    {note_str}
                </div>
                """,
                unsafe_allow_html=True
            )
        elif "стильная" in print_style and is_max_tariff:
            teacher_title = custom_print_teacher if custom_print_teacher else "English Worksheet"
            note_str = f"<p style='margin:3px 0 0 0; color:#718096; font-size:12px;'>{custom_print_note}</p>" if custom_print_note else ""
            st.markdown(
                f"""
                <div style="border-bottom: 2px solid #1a365d; padding: 12px 15px; margin-bottom: 20px; background: #ffffff; border-radius: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-end;">
                        <h3 style="margin:0; color:#1a365d; font-family:'Georgia', serif;">{teacher_title}</h3>
                        <span style="font-size: 12px; color: #718096;">Name: ______________________ | Date: ___/___/2026</span>
                    </div>
                    {note_str}
                </div>
                """,
                unsafe_allow_html=True
            )

        for card in st.session_state.cards:
            if "детская" in print_style and is_max_tariff:
                print_html = f"""<div class="print-row-kids">
<div class="print-col-kids-left">
    <span style="font-size:20px; font-weight:bold; font-family:'Georgia', serif; color:#5d4037;">{card.get('word', '')}</span>
    <span style="font-size:12px; color:#8d6e63; margin-top:4px;">{card.get('transcription', '')}</span>
</div>
<div class="print-col-kids-right">
    <h4 style="color:#2e7d32; margin-top:0; margin-bottom:4px;">{card.get('translation', '')}</h4>
    <p style="font-size: 12px; color:#333; margin:0 0 4px 0;"><strong>Definition:</strong> {card.get('explanation', '')}</p>
    <p style="font-size: 12px; color:#1b5e20; margin:0 0 4px 0;"><strong>Collocations:</strong> {card.get('collocations', '')}</p>
    <p style="font-size: 12px; color:#4a5568; margin:0;"><strong>Context:</strong> {card.get('context', '')}</p>
</div>
</div>"""
            else:
                print_html = f"""<div class="print-row-bw">
<div class="print-col print-left">{card.get('word', '')}<br/><span style="font-size:14px; font-weight:normal; color:#718096;">{card.get('transcription', '')}</span></div>
<div class="print-col">
<h4 style="color:#2e6c9e; margin-top:0; margin-bottom:5px;">{card.get('translation', '')}</h4>
<p style="font-size: 12px; color:#4a5568; margin:0 0 4px 0;"><strong>Definition:</strong> {card.get('explanation', '')}</p>
<p style="font-size: 12px; color:#2d3748; margin:0 0 4px 0;"><strong>Collocations:</strong> {card.get('collocations', '')}</p>
<p style="font-size: 12px; color:#4a5568; margin:0;"><strong>Context:</strong> {card.get('context', '')}</p>
</div>
</div>"""
            st.markdown(print_html, unsafe_allow_html=True)

    elif teacher_view_mode == "🧪 Пройти тест":
        render_quiz_section(st.session_state.cards, quiz_key_prefix="teacher_preview_quiz")

    else:
        # 🎴 Интерактивный тренажер
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            anki_list = []
            for card in st.session_state.cards:
                encoded_w = urllib.parse.quote(str(card.get('word', '')))
                anki_back = (
                    f"<div style='text-align:left; font-family:Arial,sans-serif; max-width:400px; margin:auto;'>"
                    f"<h2 style='color:#2e6c9e; margin-bottom:2px; margin-top:0;'>{card.get('translation', '')}</h2>"
                    f"<p style='font-size:13px; color:#a0aec0; margin-top:0; margin-bottom:10px;'>{card.get('transcription', '')}</p>"
                    f"<p style='font-size:14px; color:#4a5568; margin-bottom:8px;'><b>Definition:</b> {card.get('explanation', '')}</p>"
                    f"<p style='font-size:14px; color:#2d3748; margin-bottom:8px;'><b>Collocations:</b> <span style='color:#2e6c9e;'>{card.get('collocations', '')}</span></p>"
                    f"<p style='font-size:14px; color:#718096; margin-bottom:12px;'><i>Context:</i> {card.get('context', '')}</p>"
                    f"</div>"
                )
                anki_list.append({"Front": card.get('word', ''), "Back": anki_back})
                
            df = pd.DataFrame(anki_list)
            csv = df.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
            st.download_button(label="📱 Скачать файл для Anki / Quizlet", data=csv, file_name="gemini_anki_cards.txt", mime="text/plain")

        st.write("")
        cols = st.columns(3)
        for i, card in enumerate(st.session_state.cards):
            col_idx = i % 3
            with cols[col_idx]:
                is_flipped = st.session_state.flipped.get(i, False)
                encoded_word = urllib.parse.quote(str(card.get('word', '')))
                
                if not is_flipped:
                    front_html = f"""<div class="card-front">
<span class="card-front-title">{card.get('word', '')}</span>
<span class="card-front-subtitle">English Word</span>
</div>"""
                    st.markdown(front_html, unsafe_allow_html=True)
                    if st.button("🔄 Перевернуть", key=f"flip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = True
                        st.rerun()
                else:
                    back_html = f"""<div class="card-back">
<div style="text-align: center; margin-bottom: 5px;">
<span style="font-size: 13px; font-weight: bold; color: #4a2e2e !important; text-transform: uppercase;">{card.get('word', '')}</span><br/>
<span style="color: #718096; font-size: 11px;">{card.get('transcription', '')}</span>
</div>
<div style="font-size: 12px; margin-bottom: 5px;"><b>Definition:</b> {card.get('explanation', '')}</div>
<div style="font-size: 12px; margin-bottom: 6px;"><b>Collocations:</b> <span style="color: #2e6c9e;">{card.get('collocations', '')}</span></div>
<div style="font-size: 12px; margin-bottom: 10px;"><b>Context:</b> <i>{card.get('context', '')}</i></div>
<details style="border: 1px solid #ebdcc5; border-radius: 6px; padding: 4px 8px; background: #fdfbf7; margin-bottom: 10px;">
<summary style="font-size: 12px; font-weight: bold; color: #1a365d; cursor: pointer; text-align: center;">💬 Показать перевод</summary>
<div style="margin-top: 5px; font-size: 13.5px; font-weight: bold; color: #2e6c9e; text-align: center; border-top: 1px dashed #ebdcc5; padding-top: 4px;">
{card.get('translation', '')}
</div>
</details>
<div style="display: flex; gap: 8px; align-items: center; justify-content: space-between; background: #f7fafc; padding: 4px 8px; border-radius: 8px;">
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇺🇸</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=2" controls style="width: 100px; height: 28px;"></audio>
    </div>
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold;">🇬🇧</span>
        <audio src="https://dict.youdao.com/dictvoice?audio={encoded_word}&type=1" controls style="width: 100px; height: 28px;"></audio>
    </div>
</div>
</div>"""
                    st.markdown(back_html, unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
