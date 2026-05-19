import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # añade pivot_lineal/ al path

import streamlit as st
from V2.logica.estado import get_sim, SIM_KEYS
from V2.logica.constantes import get_defaults
from V2.ui.estilos import CSS
from V2.ui.teclado import manejar_teclado
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
for _k in SIM_KEYS:
    if _k not in _sim:
        _sim[_k] = _defaults[_k]

_UI_DEFAULTS = {"k_vista_general": False, "marcha_atras_kbd": False}
for _k, _v in _UI_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

manejar_teclado()
renderizar_sidebar()
panel_principal()
