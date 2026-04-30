import streamlit as st
from logica.estado import get_sim
from ui.estilos import CSS
from ui.teclado import manejar_teclado
from ui.sidebar import renderizar_sidebar
from ui.panel import panel_principal

st.set_page_config(
    page_title="Gemelo Digital Lineal",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CSS, unsafe_allow_html=True)

# Inicializar el singleton compartido (no-op si ya existe)
get_sim()

# Estado per-sesión: solo UI local
_UI_DEFAULTS = {"k_vista_general": False, "marcha_atras_kbd": False}
for _k, _v in _UI_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

manejar_teclado()
renderizar_sidebar()
panel_principal()
