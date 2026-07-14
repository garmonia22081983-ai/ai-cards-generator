import streamlit as st
import google.generativeai as genai
import json
import pandas as pd

# Инициализация API-ключа из Secrets
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Ключ API не найден в настройках Secrets на Streamlit!")

st.set_page_config(page_title="Генератор карточек", layout="wide")

# Подключение кастомных стилей для красивых карточек
st.markdown("""
<style>
.card-front {
    background-color: #f8f9fa;
    border: 2px solid #dee2e6;
    border-radius: 12px;
    padding: 30px;
    text-align: center;
    min-height: 200px;
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
    min-height: 200px;
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

# Инициализация состояний в Session State (чтобы ничего не сбрасывалось)
if "cards" not in st.session_state:
    st.session_state.cards = []
if "flipped" not in st.session_state:
    st.session_state.flipped = {}

# Выбор модели
model_option = st.selectbox("Использовать нейросеть:", ["gemini-1.5-flash-latest", "gemini-1.5-flash"])

# Поле для ввода слов
words_input = st.text_area("Введите слова или фразы (каждое с новой строки или через запятую):", 
                           placeholder="bold, digital solution, perseverance")

if st.button("Создать карточки", type="primary"):
    if not words_input.strip():
        st.warning("Пожалуйста, введите слова для генерации.")
    else:
        with st.spinner("Gemini генерирует карточки, перевод и контекст..."):
            try:
                model = genai.GenerativeModel(model_option)
                prompt = f"""
                Ты профессиональный методист английского языка. Создай карточки для следующих слов/фраз: {words_input}.
                Для каждого слова верни строго валидный JSON-массив объектов со следующими ключами:
                - "word": оригинальное слово на английском
                - "translation": точный и красивый перевод на русский (можно несколько синонимов через запятую)
                - "context": ОДНО интересное контекстное предложение на английском, в котором выделено или уместно использовано это слово. Предложение должно быть живым, современным и легким для понимания.

                Верни ТОЛЬКО чистый JSON без разметки markdown (без ```json ... ```).
                """
                response = model.generate_content(prompt)
                
                # Очистка ответа от возможных markdown-тегов
                text_response = response.text.strip()
                if text_response.startswith("```"):
                    text_response = text_response.split("```")[1]
                    if text_response.startswith("json"):
                        text_response = text_response[4:]
                text_response = text_response.strip()

                cards_data = json.loads(text_response)
                st.session_state.cards = cards_data
                # Сбрасываем перевороты для новых карточек
                st.session_state.flipped = {i: False for i in range(len(cards_data))}
                st.success(f"Готово! Сгенерировано карточек: {len(cards_data)}")
            except Exception as e:
                st.error(f"Произошла ошибка: {e}. Попробуйте еще раз.")

# Показываем блок работы с карточками, если они сгенерированы
if st.session_state.cards:
    st.write("---")
    
    # ПАНЕЛЬ УПРАВЛЕНИЯ ЭКСПОРТОМ
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        # Экспорт для Anki (телефон)
        df = pd.DataFrame([
            {
                "Front": card['word'],
                "Back": f"<div style='text-align:center;'><h2 style='color:#2e6c9e; margin-bottom:10px;'>{card['translation']}</h2><p style='font-size:16px; color:#555;'><i>Context:</i> {card['context']}</p></div>"
            } for card in st.session_state.cards
        ])
        # Кодируем в UTF-8 с BOM, чтобы Excel и Anki читали русский язык без кракозябр
        csv = df.to_csv(index=False, header=False, sep='\t').encode('utf-8-sig')
        
        st.download_button(
            label="📱 Скачать файл для Anki / Quizlet (TXT/CSV)",
            data=csv,
            file_name="gemini_anki_cards.txt",
            mime="text/plain",
            help="Импортируйте этот файл в приложение Anki на телефоне. Ссылка станет двусторонней автоматически!"
        )
        
    with col_exp2:
        # Переключатель в режим печати
        print_mode = st.checkbox("🖨️ Включить режим для печати на бумаге (Foldable Layout)")

    # ЕСЛИ ВКЛЮЧЕН РЕЖИМ ПЕЧАТИ
    if print_mode:
        st.info("💡 **Как распечатать:** Нажмите Ctrl + P (или Cmd + P на Mac) прямо в браузере. В настройках печати выберите 'Сохранить в PDF' или отправьте на принтер. Сложите лист пополам по вертикальной линии, склейте половинки и разрежьте карточки!")
        
        for card in st.session_state.cards:
            st.markdown(f"""
            <div class="print-row">
                <div class="print-col print-left">
                    {card['word']}
                </div>
                <div class="print-col">
                    <h4 style="color:#00c08b; margin-top:0; margin-bottom:5px;">{card['translation']}</h4>
                    <p style="font-size: 13px; color:#555; margin:0;"><strong>Context:</strong> {card['context']}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
    # ЕСЛИ ОБЫЧНЫЙ ИНТЕРАКТИВНЫЙ РЕЖИМ
    else:
        st.write("### 🎴 Интерактивный тренажер")
        st.caption("Нажмите кнопку под карточкой, чтобы перевернуть её.")
        
        cols = st.columns(3)
        for i, card in enumerate(st.session_state.cards):
            col_idx = i % 3
            with cols[col_idx]:
                is_flipped = st.session_state.flipped.get(i, False)
                
                if not is_flipped:
                    # Лицевая сторона (Английский)
                    st.markdown(f"""
                    <div class="card-front">
                        <span style="font-size: 26px; font-weight: bold; color: #1e3d59;">{card['word']}</span>
                        <span style="font-size: 11px; color: #888; margin-top: 15px;">English</span>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("🔄 Перевернуть", key=f"flip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = True
                        st.rerun()
                else:
                    # Оборотная сторона (Русский + Контекст)
                    st.markdown(f"""
                    <div class="card-back">
                        <span style="font-size: 18px; font-weight: bold; color: #2e6c9e; margin-bottom:8px;">{card['translation']}</span>
                        <div style="font-size: 13px; color: #555; line-height:1.4;">
                            <strong>Context:</strong> <i>{card['context']}</i>
                        </div>
                    </div>
                    """, "-")
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
