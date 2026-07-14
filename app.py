import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
import urllib.parse
import textwrap  # Импортируем инструмент для очистки пробелов слева

# Инициализация API-ключа из Secrets
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

# Подключение кастомного премиум-дизайна
st.markdown("""
<style>
/* Премиальный мягкий фоновый цвет для всего приложения */
.stApp {
    background-color: #faf6f0 !important;
}

/* Лицевая сторона: имитация качественного теплого картона */
.card-front {
    background-color: #fdfbf7;
    border: 1px solid #ebdcc5;
    border-radius: 16px;
    padding: 40px 20px;
    text-align: center;
    min-height: 380px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-shadow: 0 10px 20px rgba(180, 160, 140, 0.05), 0 2px 6px rgba(0,0,0,0.02);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.card-front:hover {
    transform: translateY(-5px);
    box-shadow: 0 15px 30px rgba(180, 160, 140, 0.12), 0 4px 10px rgba(0,0,0,0.03);
}

/* Оборотная сторона: чистый бумажный стиль с аккуратной версткой */
.card-back {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 22px;
    min-height: 380px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.03), 0 2px 6px rgba(0,0,0,0.01);
}

/* Стили для печати */
.print-row {
    display: flex;
    border: 1px dashed #ccc;
    margin-bottom: 12px;
    page-break-inside: avoid;
    background-color: #ffffff;
}
.print-col {
    width: 50%;
    padding: 15px;
    box-sizing: border-box;
}
.print-left {
    border-right: 1px dashed #ccc;
    text-align: center;
    font-weight: bold;
    font-size: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Georgia', serif;
    color: #1a365d;
}
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
    
    # 1. Выбор модели
    model_option = st.selectbox(
        "Нейросеть:", 
        ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-1.5-flash-latest"],
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
        st.warning("Пожалуйста, заполните поле ввода!")
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

                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                    """
                else:
                    prompt = f"""
                    Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                    Перед тобой учебный материал (текст/статья):
                    ---
                    {final_content}
                    ---
                    
                    Твоя задача:
                    1. Внимательно проанализируй этот текст и выбери из него ровно {num_cards} самых полезных, важных или интересных слов/коллокаций/фразовых глаголов, которые идеально подходят для изучения на уровне {student_level}.
                    2. Для каждого выбранного слова создай карточку.
                    
                    Для каждого слова верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском из предоставленного текста
                    - "translation": точный и красивый перевод на русский (можно несколько синонимов через запятую)
                    - "explanation": простое, понятное объяснение (дефиниция) этого слова на английском языке, адаптированное под уровень {student_level}
                    - "context": ОДНО контекстное предложение на английском, в котором выделено или уместно использовано это слово. Предложение и лексика в нем должны строго соответствовать уровню {student_level}.
                    - "image_keyword": ОДНО короткое ключевое слово на английском (существительное, например "mountain", "decision", "agreement"), которое лучше всего визуально описывает данное понятие для поиска картинки.

                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                    """

                response = model.generate_content(prompt)
                text_response = response.text.strip()
                if text_response.startswith("```"):
                    text_response = text_response.split("```")[1]
                    if text_response.startswith("json"):
                        text_response = text_response[4:]
                text_response = text_response.strip()

                cards_data = json.loads(text_response)
                st.session_state.cards = cards_data
                st.session_state.flipped = {i: False for i in range(len(cards_data))}
                st.success(f"Успешно! Создано карточек: {len(cards_data)} для уровня {student_level}")
            except Exception as e:
                st.error(f"Произошла ошибка при генерации: {e}. Попробуйте еще раз.")

# ВЫВОД КАРТОЧЕК И ЭКСПОРТ
if st.session_state.cards:
    st.write("---")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        anki_list = []
        for card in st.session_state.cards:
            encoded_w = urllib.parse.quote(card['word'])
            image_url = f"https://loremflickr.com/320/240/{urllib.parse.quote(card['image_keyword'])}"
            anki_back = (
                f"<div style='text-align:left; font-family:Arial,sans-serif; max-width:400px; margin:auto;'>"
                f"<img src='{image_url}' style='width:100%; border-radius:8px; margin-bottom:12px;' />"
                f"<h2 style='color:#2e6c9e; margin-bottom:5px; margin-top:0;'>{card['translation']}</h2>"
                f"<p style='font-size:14px; color:#4a5568; margin-bottom:8px;'><b>Definition:</b> {card['explanation']}</p>"
                f"<p style='font-size:14px; color:#718096; margin-bottom:12px;'><i>Context:</i> {card['context']}</p>"
                f"<hr style='border:none; border-top:1px solid #eee; margin:10px 0;' />"
                f"<div style='display:flex; gap:15px; justify-content:center;'>"
                f"<a href='https://translate.google.com/translate_tts?ie=UTF-8&tl=en-US&client=tw-ob&q={encoded_w}' style='text-decoration:none; font-size:13px;'>🇺🇸 Play US</a>"
                f"<a href='https://translate.google.com/translate_tts?ie=UTF-8&tl=en-GB&client=tw-ob&q={encoded_w}' style='text-decoration:none; font-size:13px;'>🇬🇧 Play UK</a>"
                f"</div></div>"
            )
            anki_list.append({"Front": card['word'], "Back": anki_back})
            
        df = pd.DataFrame(anki_list)
        csv = df.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
        
        st.download_button(
            label="📱 Скачать файл для Anki / Quizlet (С картинками и аудио!)",
            data=csv,
            file_name="gemini_anki_cards.txt",
            mime="text/plain"
        )
        
    with col_exp2:
        print_mode = st.checkbox("🖨️ Включить режим для печати на бумаге (Foldable Layout)")

    if print_mode:
        st.info("💡 **Как распечатать:** Нажмите Ctrl + P (или Cmd + P на Mac).")
        for card in st.session_state.cards:
            # textwrap.dedent убирает пробелы слева, исправляя верстку
            st.markdown(textwrap.dedent(f"""
            <div class="print-row">
                <div class="print-col print-left">{card['word']}</div>
                <div class="print-col">
                    <h4 style="color:#2e6c9e; margin-top:0; margin-bottom:5px;">{card['translation']}</h4>
                    <p style="font-size: 12px; color:#4a5568; margin:0 0 4px 0;"><strong>Definition:</strong> {card['explanation']}</p>
                    <p style="font-size: 12px; color:#4a5568; margin:0;"><strong>Context:</strong> {card['context']}</p>
                </div>
            </div>
            """), unsafe_allow_html=True)
            
    else:
        st.write("### 🎴 Интерактивный тренажер")
        cols = st.columns(3)
        for i, card in enumerate(st.session_state.cards):
            col_idx = i % 3
            with cols[col_idx]:
                is_flipped = st.session_state.flipped.get(i, False)
                encoded_word = urllib.parse.quote(card['word'])
                image_keyword_encoded = urllib.parse.quote(card['image_keyword'])
                img_url = f"https://loremflickr.com/320/180/{image_keyword_encoded}"
                
                if not is_flipped:
                    st.markdown(textwrap.dedent(f"""
                    <div class="card-front">
                        <span style="font-size: 28px; font-weight: bold; font-family: 'Georgia', serif; color: #1a365d;">{card['word']}</span>
                        <span style="font-size: 11px; color: #a0aec0; margin-top: 25px; text-transform: uppercase; letter-spacing: 1px;">English Word</span>
                    </div>
                    """), unsafe_allow_html=True)
                    if st.button("🔄 Перевернуть", key=f"flip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = True
                        st.rerun()
                else:
                    st.markdown(textwrap.dedent(f"""
                    <div class="card-back">
                        <div style="text-align: center; margin-bottom: 5px;">
                            <span style="font-size: 11px; font-weight: bold; color: #a0aec0; text-transform: uppercase;">{card['word']}</span>
                        </div>
                        
                        <img src="{img_url}" style="width: 100%; height: 110px; object-fit: cover; border-radius: 8px; margin-bottom: 8px;" />
                        
                        <div style="margin-bottom: 6px;">
                            <span style="font-size: 16px; font-weight: bold; color: #2e6c9e;">{card['translation']}</span>
                        </div>
                        
                        <div style="font-size: 12px; color: #4a5568; margin-bottom: 4px; line-height: 1.3;">
                            <b>Definition:</b> {card['explanation']}
                        </div>
                        
                        <div style="font-size: 12px; color: #718096; line-height: 1.3; margin-bottom: 8px;">
                            <b>Context:</b> <i>{card['context']}</i>
                        </div>
                        
                        <div style="display: flex; justify-content: space-around; background: #f7fafc; padding: 6px; border-radius: 8px; align-items: center; border: 1px solid #edf2f7;">
                            <div style="display: flex; align-items: center; gap: 4px;">
                                <span style="font-size: 12px;">🇺🇸</span>
                                <audio src="https://translate.google.com/translate_tts?ie=UTF-8&tl=en-US&client=tw-ob&q={encoded_word}" controls style="width: 75px; height: 22px;"></audio>
                            </div>
                            <div style="display: flex; align-items: center; gap: 4px;">
                                <span style="font-size: 12px;">🇬🇧</span>
                                <audio src="https://translate.google.com/translate_tts?ie=UTF-8&tl=en-GB&client=tw-ob&q={encoded_word}" controls style="width: 75px; height: 22px;"></audio>
                            </div>
                        </div>
                    </div>
                    """), unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
