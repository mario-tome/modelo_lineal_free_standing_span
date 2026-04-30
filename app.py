import streamlit as st
from logica.estado import get_sim, SIM_KEYS
from logica.constantes import get_defaults
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

# Inicializar el singleton compartido y migrar claves nuevas si faltaran
# (ocurre cuando se añaden claves tras un hot-reload sin reiniciar Streamlit)
_sim      = get_sim()
_defaults = get_defaults()
for _k in SIM_KEYS:
    if _k not in _sim:
        _sim[_k] = _defaults[_k]

# Estado per-sesión: solo UI local
_UI_DEFAULTS = {"k_vista_general": False, "marcha_atras_kbd": False}
for _k, _v in _UI_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

manejar_teclado()
renderizar_sidebar()
panel_principal()
