import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from V2.logica.estado import get_sim, CLAVES_SIMULACION
from V2.logica.constantes import get_defaults
from V2.ui.estilos import CSS
from V2.ui.sidebar import renderizar_sidebar
from V2.ui.panel import panel_principal

st.set_page_config(
    page_title="Gemelo Digital Lineal v2",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CSS, unsafe_allow_html=True)

_sim = get_sim()
_defaults = get_defaults()
for _k in CLAVES_SIMULACION:
    if _k not in _sim:
        _sim[_k] = _defaults[_k]

# Claves de la sesión de usuario (no pertenecen al estado de simulación compartido).
_UI_DEFAULTS = {"k_vista_general": False, "es_operador": False}
for _k, _v in _UI_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

renderizar_sidebar()
panel_principal()
