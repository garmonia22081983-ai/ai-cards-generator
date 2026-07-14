import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Инициализация API-ключа из Secrets
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

# Подключение стилей для красивых карточек
st.markdown("""
<style>
.card-front {
    background-color: #f8f9fa;
    border: 2px solid #dee2e6;
    border-radius: 12px;
    padding: 30px;
    text-align: center;
    min-height: 220px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
}
.card-back {
    background-color: #e8f4fd;
    border: 2px solid #bbeeeb;
    border-radius: 12px;
    padding: 25px;
    min-height: 220px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
}
.print-row {
    display: flex;
    border: 1px dashed #ccc;
    margin-bottom: 12px;
    page-break-inside: avoid;
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
}
</style>
""", unsafe_allow_html=True)

st.title("🎴 Умный Генератор Двусторонних Карточек")
st.write("Генерируйте лексические карточки из статей, транскриптов видео или готовых списков слов под уровень ваших студентов.")

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
            # Удаляем скрипты и стили
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = '\n'.join(chunk for chunk in chunks if chunk)
            return clean_text[:8000]  # Ограничение длины для контекста ИИ
        else:
            return f"Ошибка загрузки сайта: Статус {response.status_code}"
    except Exception as e:
        return f"Не удалось прочитать ссылку автоматически: {str(e)}"

# ЛЕВАЯ ПАНЕЛЬ НАСТРОЕК
with st.sidebar:
    st.header("⚙️ Настройки генерации")
    
    # 1. Выбор модели (Добавили новые Gemini 3)
    model_option = st.selectbox(
        "Нейросеть:", 
        [
            "gemini-3.5-flash", 
            "gemini-3-flash-preview", 
            "gemini-1.5-flash-latest", 
            "gemini-1.5-flash"
        ],
        index=0  # По умолчанию выберет самую новую gemini-3.5-flash
    )
    
    # 2. Выбор источника
    source_type = st.radio(
        "Что берем за основу?",
        ["📝 Текст / Отрывок статьи / Транскрипт", "🔗 Ссылка на веб-статью", "✍️ Готовый список слов"]
    )
    
    # 3. Выбор уровня студента
    student_level = st.selectbox(
        "Уровень студента (CEFR):",
        ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficient)"],
        index=2  # По умолчанию B1
    )
    
    # 4. Количество карточек
    num_cards = st.slider("Сколько карточек создать?", min_value=3, max_value=15, value=7)

# ПОЛЕ ВВОДА НА ОСНОВНОМ ЭКРАНЕ
user_input = ""
if source_type == "📝 Текст / Отрывок статьи / Транскрипт":
    user_input = st.text_area("Вставьте сюда текст статьи или субтитры (транскрипт) видео:", height=250,
                              placeholder="Вставьте сюда английский текст, из которого нужно вытащить лексику...")
elif source_type == "🔗 Ссылка на веб-статью":
    user_input = st.text_input("Вставьте URL-ссылку на англоязычную статью:", 
                               placeholder="https://www.bbc.com/news/articles/...")
    st.caption("⚠️ Примечание: Для видео с YouTube лучше скопировать и вставить их текстовый транскрипт через режим 'Текст', так как прямые ссылки на видео часто защищены от автоматического чтения.")
else:
    user_input = st.text_area("Введите конкретные слова или фразы (через запятую или с новой строки):", height=150,
                              placeholder="bold, digital solution, perseverance")

# КНОПКА ЗАПУСКА
if st.button("Создать карточки ✨", type="primary"):
    if not user_input.strip():
        st.warning("Пожалуйста, заполните поле ввода!")
    else:
        with st.spinner("ИИ анализирует материал и генерирует идеальные карточки..."):
            try:
                # Шаг 1: Подготовка контента
                final_content = user_input
                if source_type == "🔗 Ссылка на веб-статью":
                    scraped_text = extract_text_from_url(user_input)
                    if "Ошибка" in scraped_text or "Не удалось" in scraped_text:
                        st.error(scraped_text)
                        st.stop()
                    final_content = scraped_text

                # Шаг 2: Формирование промпта для Gemini
                model = genai.GenerativeModel(model_option)
                
                if source_type == "✍️ Готовый список слов":
                    prompt = f"""
                    Ты профессиональный методист английского языка. Твой студент имеет уровень {student_level}.
                    Создай карточки для следующих слов/фраз: {final_content}.
                    Для каждого слова верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском
                    - "translation": точный и красивый перевод на русский (можно несколько синонимов через запятую)
                    - "context": ОДНО интересное контекстное предложение на английском, в котором выделено или уместно использовано это слово. Предложение и лексика в нем должны строго соответствовать уровню {student_level}.

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
                    1. Внимательно проанализируй этот текст и выбери из него ровно {num_cards} самых полезных, важных или интересных слов/коллокаций/фразовых глаголов, которые идеально подходят для изучения на уровне {student_level}. Они не должны быть слишком легкими (уровня ниже) или нереалистично сложными.
                    2. Для каждого выбранного слова создай карточку.
                    
                    Для каждого слова верни строго валидный JSON-массив объектов со следующими ключами:
                    - "word": оригинальное слово на английском из предоставленного текста
                    - "translation": точный и красивый перевод на русский (можно несколько синонимов через запятую)
                    - "context": ОДНО контекстное предложение на английском, в котором выделено или уместно использовано это слово. Это предложение должно отражать смысл или тему оригинальной статьи, но быть грамматически и лексически адаптированным под уровень {student_level}.

                    Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                    """

                response = model.generate_content(prompt)
                
                # Очистка JSON ответа
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
        # Экспорт в Anki
        df = pd.DataFrame([
            {
                "Front": card['word'],
                "Back": f"<div style='text-align:center;'><h2 style='color:#2e6c9e; margin-bottom:10px;'>{card['translation']}</h2><p style='font-size:16px; color:#555;'><i>Context:</i> {card['context']}</p></div>"
            } for card in st.session_state.cards
        ])
        csv = df.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
        
        st.download_button(
            label="📱 Скачать файл для Anki / Quizlet (TXT/CSV)",
            data=csv,
            file_name="gemini_anki_cards.txt",
            mime="text/plain"
        )
        
    with col_exp2:
        print_mode = st.checkbox("🖨️ Включить режим для печати на бумаге (Foldable Layout)")

    if print_mode:
        st.info("💡 **Как распечатать:** Нажмите Ctrl + P (или Cmd + P на Mac). Сложите лист вертикально пополам, склейте половинки и разрежьте карточки!")
        for card in st.session_state.cards:
            st.markdown(f"""
            <div class="print-row">
                <div class="print-col print-left">{card['word']}</div>
                <div class="print-col">
                    <h4 style="color:#00c08b; margin-top:0; margin-bottom:5px;">{card['translation']}</h4>
                    <p style="font-size: 13px; color:#555; margin:0;"><strong>Context:</strong> {card['context']}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.write("### 🎴 Интерактивный тренажер")
        cols = st.columns(3)
        for i, card in enumerate(st.session_state.cards):
            col_idx = i % 3
            with cols[col_idx]:
                is_flipped = st.session_state.flipped.get(i, False)
                if not is_flipped:
                    st.markdown(f"""
                    <div class="card-front">
                        <span style="font-size: 24px; font-weight: bold; color: #1e3d59;">{card['word']}</span>
                        <span style="font-size: 11px; color: #888; margin-top: 15px;">English</span>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("🔄 Перевернуть", key=f"flip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = True
                        st.rerun()
                else:
                    st.markdown(f"""
                    <div class="card-back">
                        <span style="font-size: 18px; font-weight: bold; color: #00c08b; margin-bottom:8px;">{card['translation']}</span>
                        <div style="font-size: 13px; color: #555; line-height:1.4;">
                            <strong>Context:</strong> <i>{card['context']}</i>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
