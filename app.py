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
                    Верни ТОЛЬКО чистый JSON без маркдаун оберток.
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
                    Верни ТОЛЬКО чистый JSON без маркдаун оберток.
                    """

                response = model.generate_content(prompt)
                text_response = response.text.strip()
                
                # Защищенный разбор ответа от маркдаун-оберток без использования трех бэктэков в коде
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
                
                # ПОСЛЕДОВАТЕЛЬНАЯ ГЕНЕРАЦИЯ И ЗАКАЧКА КАРТИНОК НА БЭКЕНДЕ
                status_text = st.empty()
                progress_bar = st.progress(0)
                total_to_gen = len(cards_data)
                
                for idx, card in enumerate(cards_data):
                    current_word = card['word'].upper()
                    status_text.write(f"🎨 Нейросеть рисует иллюстрацию для слова **{current_word}** ({idx+1}/{total_to_gen})...")
                    
                    ai_image_prompt = f"A simple clear professional 3D render or photo of a {card['word']}, isolated on a clean white background, minimalist, highly recognizable visual flashcard style"
                    encoded_prompt = urllib.parse.quote(ai_image_prompt)
                    img_url = f"[https://image.pollinations.ai/p/](https://image.pollinations.ai/p/){encoded_prompt}?width=320&height=240&nologo=true"
                    
                    try:
                        img_response = requests.get(img_url, timeout=15)
                        if img_response.status_code == 200:
                            b64_img = base64.b64encode(img_response.content).decode()
                            card['image_b64'] = f"data:image/jpeg;base64,{b64_img}"
                        else:
                            card['image_b64'] = ""
                    except Exception:
                        card['image_b64'] = ""
                    
                    progress_bar.progress((idx + 1) / total_to_gen)
                    time.sleep(0.2)
                
                status_text.empty()
                progress_bar.empty()
                
                st.session_state.cards = cards_data
                st.session_state.flipped = {i: False for i in range(len(cards_data))}
                st.success(f"Успешно! Создано карточек: {len(cards_data)}")
            except Exception as e:
                st.error(f"Произошла ошибка при генерации: {e}.")

# ВЫВОД КАРТОЧЕК
if st.session_state.cards:
    st.write("---")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        anki_list = []
        for card in st.session_state.cards:
            encoded_w = urllib.parse.quote(card['word'])
            img_src = card.get('image_b64', '')
            
            anki_back = (
                f"<div style='text-align:left; font-family:Arial,sans-serif; max-width:400px; margin:auto;'>"
                f"<img src='{img_src}' style='width:100%; border-radius:8px; margin-bottom:12px;' />"
                f"<h2 style='color:#2e6c9e; margin-bottom:5px; margin-top:0;'>{card['translation']}</h2>"
                f"<p style='font-size:14px; color:#4a5568; margin-bottom:8px;'><b>Definition:</b> {card['explanation']}</p>"
                f"<p style='font-size:14px; color:#718096; margin-bottom:12px;'><i>Context:</i> {card['context']}</p>"
                f"<hr style='border:none; border-top:1px solid #eee; margin:10px 0;' />"
                f"<div style='display:flex; gap:15px; justify-content:center;'>"
                f"<a href='[https://dict.youdao.com/dictvoice?audio=](https://dict.youdao.com/dictvoice?audio=){encoded_w}&type=2' style='text-decoration:none; font-size:13px;'>🇺🇸 Play US</a>"
                f"<a href='[https://dict.youdao.com/dictvoice?audio=](https://dict.youdao.com/dictvoice?audio=){encoded_w}&type=1' style='text-decoration:none; font-size:13px;'>🇬🇧 Play UK</a>"
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
<div class="print-col print-left">{card['word']}</div>
<div class="print-col">
<h4 style="color:#2e6c9e; margin-top:0; margin-bottom:5px;">{card['translation']}</h4>
<p style="font-size: 12px; color:#4a5568; margin:0 0 4px 0;"><strong>Definition:</strong> {card['explanation']}</p>
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
                
                svg_placeholder = f"""<svg xmlns='[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)' width='110' height='70'>
                <rect width='100%' height='100%' fill='%23fdfbf7' stroke='%23ebdcc5' stroke-width='1' rx='6'/>
                <text x='50%' y='52%' dominant-baseline='middle' text-anchor='middle' font-family='Georgia, serif' font-size='10' font-weight='bold' fill='%23718096'>✨ {card['word'].upper()}</text>
                </svg>"""
                fallback_src = f"data:image/svg+xml,{urllib.parse.quote(svg_placeholder)}"
                
                img_src = card.get('image_b64', '')
                if not img_src:
                    img_src = fallback_src
                
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
<div style="text-align: center; margin-bottom: 3px;">
<span style="font-size: 11px; font-weight: bold; color: #a0aec0; text-transform: uppercase;">{card['word']}</span>
</div>

<img src="{img_src}" onerror="this.onerror=null; this.src='{fallback_src}';" style="width: 110px; height: 70px; object-fit: cover; border-radius: 6px; margin: 0 auto 8px auto; display: block; box-shadow: 0 3px 6px rgba(0,0,0,0.04);" />

<div style="font-size: 11.5px; color: #4a5568; margin-bottom: 3px; line-height: 1.25;">
<b>Definition:</b> {card['explanation']}
</div>

<div style="font-size: 11.5px; color: #718096; line-height: 1.25; margin-bottom: 6px;">
<b>Context:</b> <i>{card['context']}</i>
</div>

<details style="border: 1px solid #ebdcc5; border-radius: 6px; padding: 4px 8px; background: #fdfbf7; margin-bottom: 8px;">
<summary style="font-size: 12px; font-weight: bold; color: #1a365d; cursor: pointer; list-style: none; text-align: center; outline: none; user-select: none;">💬 Показать перевод</summary>
<div style="margin-top: 5px; font-size: 13.5px; font-weight: bold; color: #2e6c9e; text-align: center; border-top: 1px dashed #ebdcc5; padding-top: 4px;">
{card['translation']}
</div>
</details>

<div style="display: flex; gap: 8px; align-items: center; justify-content: space-between; background: #f7fafc; padding: 4px 8px; border-radius: 8px; border: 1px solid #edf2f7;">
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold; color: #4a5568;">🇺🇸</span>
        <audio src="[https://dict.youdao.com/dictvoice?audio=](https://dict.youdao.com/dictvoice?audio=){encoded_word}&type=2" controls style="width: 100px; height: 28px; outline: none;"></audio>
    </div>
    <div style="display: flex; align-items: center; gap: 4px;">
        <span style="font-size: 11px; font-weight: bold; color: #4a5568;">🇬🇧</span>
        <audio src="[https://dict.youdao.com/dictvoice?audio=](https://dict.youdao.com/dictvoice?audio=){encoded_word}&type=1" controls style="width: 100px; height: 28px; outline: none;"></audio>
    </div>
</div>
</div>"""
                    st.markdown(back_html, unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
