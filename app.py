<b>Context:</b> <i>{card['context']}</i>
</div>

<!-- Раскрывающийся блок с скрытым переводом -->
<details style="border: 1px solid #ebdcc5; border-radius: 8px; padding: 6px 12px; background: #fdfbf7; margin-bottom: 10px;">
<summary style="font-size: 13px; font-weight: bold; color: #1a365d; cursor: pointer; list-style: none; text-align: center; outline: none; user-select: none;">💬 Показать перевод</summary>
<div style="margin-top: 8px; font-size: 15px; font-weight: bold; color: #2e6c9e; text-align: center; border-top: 1px dashed #ebdcc5; padding-top: 6px;">
{card['translation']}
</div>
</details>

<!-- Озвучка через SpeechSynthesis API (локальный синтез браузера, защищен от блокировок и песочниц) -->
<div style="display: flex; justify-content: space-around; background: #f7fafc; padding: 6px; border-radius: 8px; align-items: center; border: 1px solid #edf2f7;">
<button onclick="let u = new SpeechSynthesisUtterance('{escaped_word}'); u.lang='en-US'; window.speechSynthesis.speak(u);" style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 12px; cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; color: #4a5568;">
<span>🔊</span> US
</button>
<button onclick="let u = new SpeechSynthesisUtterance('{escaped_word}'); u.lang='en-GB'; window.speechSynthesis.speak(u);" style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px 12px; cursor: pointer; display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; color: #4a5568;">
<span>🔊</span> UK
</button>
</div>
</div>"""
                    st.markdown(back_html, unsafe_allow_html=True)
                    if st.button("👈 Показать слово", key=f"unflip_{i}", use_container_width=True):
                        st.session_state.flipped[i] = False
                        st.rerun()
"""
