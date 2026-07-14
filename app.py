import streamlit as st
import google.generativeai as genai
import json
import pandas as pd

# 1. Настройка страницы и стилей для красивого визуала
st.set_page_config(page_title="AI Card Generator", page_icon="⚡", layout="wide")

# Внедряем кастомные CSS-стили для создания премиального вида карточек
st.markdown("""
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: 800;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 2rem;
    }
    .card-container {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: transform 0.2s;
    }
    .card-container:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
    }
    .card-word {
        color: #1E3A8A;
        font-size: 1.4rem;
        font-weight: 700;
        margin-bottom: 5px;
    }
    .card-translation {
        color: #10B981;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .card-context {
        color: #4B5563;
        font-style: italic;
        font-size: 0.95rem;
        border-left: 3px solid #3B82F6;
        padding-left: 10px;
        margin-top: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">⚡ AI-Конструктор карточек для преподавателей</div>', unsafe_allow_html=True)

# 2. Инициализация API-ключа Gemini из секретов
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
except Exception:
    st.error("Ошибка: API-ключ 'GEMINI_API_KEY' не найден в настройках Secrets вашего Space.")
    st.stop()

# 3. Боковая панель с настройками (Sidebar)
st.sidebar.header("⚙️ Настройки генерации")

# Выбор уровня языка
level = st.sidebar.selectbox(
    "Выберите уровень языка (CEFR):",
    ["A1 (Beginner)", "A2 (Elementary)", "B1 (Intermediate)", "B2 (Upper-Intermediate)", "C1 (Advanced)", "C2 (Proficiency)"]
)

# НОВИНКА: Выбор модели ИИ для обхода региональных и аккаунтных ограничений
model_name = st.sidebar.selectbox(
    "Выберите модель ИИ:",
    [
        "gemini-1.5-flash-latest",
        "gemini-3-flash-preview",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.5-flash"
    ],
    help="Если базовая модель выдает ошибку 404, переключитесь на другую. Для новых аккаунтов отлично подходят 'gemini-1.5-flash-latest' и 'gemini-3-flash-preview'."
)

# 4. Главная рабочая область
user_text = st.text_area(
    "Вставьте текст статьи, абзац или список предложений, из которых нужно извлечь лексику:",
    height=200,
    placeholder="Например: 'The mysterious forest was covered in a thick, heavy fog. Standing at the edge, Clara felt a sudden shiver...'"
)

# 5. Кнопка запуска генерации
if st.button("Создать карточки", type="primary"):
    if not user_text.strip():
        st.warning("Пожалуйста, добавьте текст для анализа.")
    else:
        with st.spinner("Профессиональный методист ИИ анализирует текст..."):
            try:
                # Инициализация выбранной пользователем модели
                model = genai.GenerativeModel(model_name)
                
                # Твой идеальный системный промпт
                prompt = f"""
                Ты — профессиональный методист английского языка. Твоя задача — проанализировать текст пользователя, 
                извлечь из него 10 самых важных лексических единиц (слов или идиом), соответствующих уровню {level}, 
                и перевести их на русский язык. Выдай ответ строго в формате JSON, без лишних слов, вступлений и разметки markdown. 
                
                Формат ответа:
                [
                  {{"word": "слово на английском", "translation": "перевод на русский", "context": "оригинальное предложение из текста, где это слово используется"}}
                ]
                
                Текст для анализа:
                {user_text}
                """
                
                response = model.generate_content(prompt)
                
                # Очистка ответа от возможной разметки markdown (```json ... ```)
                response_text = response.text.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                elif response_text.startswith("```"):
                    response_text = response_text[3:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                # Парсинг результатов
                cards_data = json.loads(response_text)
                
                # Сохраняем результат в сессию, чтобы он не пропадал при скачивании файлов
                st.session_state['cards_data'] = cards_data
                st.success("Карточки успешно созданы!")
                
            except Exception as e:
                st.error(f"Произошла ошибка при генерации. Пожалуйста, выберите другую модель ИИ в боковой панели или попробуйте еще раз. Детали: {e}")

# 6. Отображение результатов и функции экспорта
if 'cards_data' in st.session_state:
    cards = st.session_state['cards_data']
    
    # Кнопки для экспорта
    st.subheader("💾 Экспорт материалов")
    col1, col2 = st.columns(2)
    
    # Экспорт для Quizlet (Формат: Слово \t Перевод (Контекст))
    quizlet_lines = []
    for c in cards:
        quizlet_lines.append(f"{c['word']}\t{c['translation']} | Context: {c['context']}")
    quizlet_text = "\n".join(quizlet_lines)
    
    with col1:
        st.download_button(
            label="📥 Скачать файл для Quizlet",
            data=quizlet_text,
            file_name="quizlet_cards.txt",
            mime="text/plain",
            help="Скопируйте содержимое этого файла и вставьте в поле импорта в Quizlet."
        )
        
    # Экспорт в Excel / CSV (с поддержкой кириллицы UTF-8-SIG)
    df = pd.DataFrame(cards)
    csv_data = df.to_csv(index=False, encoding="utf-8-sig")
    
    with col2:
        st.download_button(
            label="📥 Скачать таблицу Excel (CSV)",
            data=csv_data,
            file_name="english_cards.csv",
            mime="text/csv",
            help="Откройте этот файл в Excel или Google Таблицах."
        )
        
    # Красивый вывод карточек на экран
    st.subheader("👀 Готовые карточки:")
    
    # Выводим карточки красивой сеткой
    for i in range(0, len(cards), 2):
        row_cols = st.columns(2)
        for j in range(2):
            if i + j < len(cards):
                card = cards[i + j]
                with row_cols[j]:
                    st.markdown(f"""
                    <div class="card-container">
                        <div class="card-word">🇬🇧 {card['word']}</div>
                        <div class="card-translation">🇷🇺 {card['translation']}</div>
                        <div class="card-context"><b>Context:</b> {card['context']}</div>
                    </div>
                    """, unsafe_allow_html=True)
