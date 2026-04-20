"""
streamlit run app.py
"""
import csv
import io
import os
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
from modelo import Lineal, Torre_Guia, Torre_Intermedia, GPS, CajaInterfaz
try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

# Componente de teclado personalizado para controlar el lineal con teclas físicas.
# Funciona como un mini-iframe invisible (height=0) incrustado en la página de Streamlit.
# Escucha las teclas en el documento padre y envía el estado a Python vía postMessage.
# El iframe persiste entre rerenderizados, por eso los listeners de teclado se añaden solo una vez.
#   < (mantener) → giro izquierda   - (mantener) → giro derecha   R (toggle) → marcha atrás
_GIRO_KBD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giro_kbd")
os.makedirs(_GIRO_KBD_DIR, exist_ok=True)
with open(os.path.join(_GIRO_KBD_DIR, "index.html"), "w", encoding="utf-8") as _f:
    _f.write("""<!DOCTYPE html><html><head><script>
var _init = false;
var _st   = {left: false, right: false, reverse: false};
function _send() {
    window.parent.postMessage({
        isStreamlitMessage: true,
        type: 'streamlit:setComponentValue',
        value: {left: _st.left, right: _st.right, reverse: _st.reverse},
        dataType: 'json'
    }, '*');
}
window.addEventListener('message', function(ev) {
    if (!ev.data || ev.data.type !== 'streamlit:render') return;
    if (!_init) {
        _init = true;
        window.parent.document.addEventListener('keydown', function(e) {
            if (e.repeat) return;
            var ch = false;
            if (e.key === '<')              { _st.left    = true;          ch = true; }
            if (e.key === '-')              { _st.right   = true;          ch = true; }
            if (e.key.toLowerCase() === 'r'){ _st.reverse = !_st.reverse;  ch = true; }
            if (ch) _send();
        });
        window.parent.document.addEventListener('keyup', function(e) {
            var ch = false;
            if (e.key === '<') { _st.left  = false; ch = true; }
            if (e.key === '-') { _st.right = false; ch = true; }
            if (ch) _send();
        });
    }
    window.parent.postMessage(
        {isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: 0}, '*');
});
window.parent.postMessage(
    {isStreamlitMessage: true, type: 'streamlit:componentReady', apiVersion: 1}, '*');
</script></head><body></body></html>""")
_giro_kbd = components.declare_component("pivot_giro_kbd", path=_GIRO_KBD_DIR)

st.set_page_config(
    page_title="Gemelo Digital Lineal",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 16px;
}
[data-testid="stMetricValue"]  { font-size: 1.35rem !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"]  { font-size: 0.7rem !important; letter-spacing: 1px; color: #8b949e !important; text-transform: uppercase; }
[data-testid="stSidebar"]      { background-color: #0d1117; border-right: 1px solid #21262d; }
[data-testid="stSidebar"] h2   { color: #ffa657; letter-spacing: 1px; }
div.stButton > button[kind="primary"] {
    background-color: #1a4731 !important;
    border: 1px solid #3fb950 !important;
    color: #3fb950 !important;
    font-weight: 700; letter-spacing: 1px;
}
div.stButton > button[kind="primary"]:hover { background-color: #1f5a3d !important; }
hr  { border-color: #21262d !important; }
h1  { color: #e6edf3 !important; letter-spacing: 1px; }
h2, h5 { color: #8b949e !important; }
[data-testid="stSidebar"] .stCaption p { color: #484f58 !important; font-size: 0.72rem !important; }
</style>
""", unsafe_allow_html=True)


defaults = {
    "lineal":          None,
    "longitud_campo":  800,
    "running":         False,
    "finished":        False,
    "paused":          False,
    "log":             [],     # eventos: {t, tipo, msg}
    "historial":       [],     # filas para CSV: {tiempo_s, pos, torres...}
    "gps_track":       [],     # últimas lecturas GPS para la mini-tabla
    "gps_prev":        None,  # lectura GPS anterior para calcular delta en UI
    "vel_real":        0.0,    # velocidad media real calculada entre frames
    "pos_prev":        0.0,    # posicion_norte del frame anterior
    "tramos_ok_prev":  None,   # estado de alineacion anterior para detectar cambios
    "k_vista_general": False,  # True = campo completo, False = seguir lineal 1:1
    "tower_trails":     None,   # list[list[(x,y)]] — histórico de posiciones por torre
    "marcha_atras_kbd": False,  # estado del pulsador 'S' — sincronizado con el componente JS
    "ar_pasadas":       0,      # número de inversiones automáticas realizadas (auto-reverse)
    "caja_slow_prev":   {"cart": False, "end": False, "safety": True},  # estado anterior para detectar cambios
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# Sidebar: se renderiza una sola vez, nunca parpadea
with st.sidebar:
    st.markdown("## LINEAL")
    st.caption("Configura tu Gemelo Digital")
    st.divider()

    state  = st.session_state
    locked = state.lineal is not None

    st.markdown("##### Geometria del Lineal")
    if locked:
        st.markdown(
            "<span style='color:#484f58;font-size:0.72rem'>"
            "Simulacion activa — parametros bloqueados</span>",
            unsafe_allow_html=True,
        )
    c1, c2 = st.columns(2)
    tramos = c1.number_input("N° de tramos",         3,   20,   5,   1,   disabled=locked, key="k_tramos")
    t_len  = c2.number_input("Long. tramo (m)",      5,   500,  50,  5,   disabled=locked, key="k_tlen")
    c3, c4 = st.columns(2)
    v_nom  = c3.number_input("Vel. nominal (m/min)", 0.5, 10.0, 3.0, 0.5, disabled=locked, key="k_vnom")
    campo  = c4.number_input("Campo total (m)",      100, 5000, 800, 50,  disabled=locked, key="k_campo")

    st.markdown("##### Panel speed")
    vel_pct = st.slider(
        "Panel speed  (Duty cycle %)",
        1, 100, 50, key="k_vpct", format="%d %%",
        help="Porcentaje de la velocidad máxima a la que avanza el lineal.",
    )
    v_media = vel_pct / 100 * v_nom
    st.markdown(
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
        f"padding:8px 12px;margin:2px 0 10px 0;display:flex;justify-content:space-between'>"
        f"<span><span style='color:#8b949e;font-size:0.7rem'>ON </span>"
        f"<b style='color:#e6edf3;font-family:monospace'>{vel_pct * 60 / 100:.0f} s</b>"
        f"<span style='color:#8b949e;font-size:0.7rem'> / 60 s</span></span>"
        f"<span><span style='color:#8b949e;font-size:0.7rem'>MEDIA </span>"
        f"<b style='color:#3fb950;font-family:monospace'>{v_media:.2f} m/min</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("##### Simulacion")
    sim_spd = st.slider(
        "Factor de escala temporal de ejecución x veces real",
        1, 600, 60, key="k_simspd", format="x%d",
        help="Cuantos segundos de simulacion avanza el modelo entre cada refresco de pantalla.",
    )
    st.caption(f"Cada refresco = **{sim_spd} s** avanza")

    st.divider()
    st.markdown("##### Grados de patinaje por terreno")
    _TERRENOS = {
        "Perfecto (sin ruido)":   0.000,
        "Poco":                  0.006,
        "Normal":                 0.012,
        "Irregular":              0.030,
        "Lineal loco":            0.070,
    }
    terreno_sel = st.selectbox(
        "Elije el tipo de patinaje",
        options=list(_TERRENOS.keys()),
        index=2,
        key="k_terreno",
        disabled=locked,
        help="Modela la deriva lateral natural de las torres guía según las irregularidades del terreno.",
    )
    ruido_val = _TERRENOS[terreno_sel]
    if ruido_val > 0.0:
        deriva_aprox = ruido_val * (3.0 / 60.0) * (state.get("k_vpct", 50) / 100.0) * (state.get("k_campo", 800) ** 0.5) * 60.0
        st.caption(f"Deriva acumulada estimada al final del campo: **±{deriva_aprox:.0f} cm**")

    st.divider()
    st.markdown("##### Auto-reverse")
    ar_on = st.toggle(
        "Activar auto-reverse",
        key="k_auto_reverse",
        help="El lineal rebota automáticamente entre los límites Y configurados. "
             "La tecla S sigue funcionando para forzar un giro manual en cualquier momento.",
    )
    if ar_on:
        _ar_ymin_def = 0
        _ar_ymax_def = int(state.get("k_campo", 800))
        c_ar1, c_ar2 = st.columns(2)
        c_ar1.number_input(
            "Y mín (m)", min_value=0, max_value=_ar_ymax_def,
            value=state.get("k_ar_ymin", _ar_ymin_def),
            step=5, key="k_ar_ymin",
            help="Posición norte mínima — al llegar aquí en marcha atrás se invierte a avance",
        )
        c_ar2.number_input(
            "Y máx (m)", min_value=0, max_value=int(campo),
            value=state.get("k_ar_ymax", _ar_ymax_def),
            step=5, key="k_ar_ymax",
            help="Posición norte máxima — al llegar aquí en avance se invierte a marcha atrás",
        )
        _ymin_disp = state.get("k_ar_ymin", _ar_ymin_def)
        _ymax_disp = state.get("k_ar_ymax", _ar_ymax_def)
        _pasadas   = state.get("ar_pasadas", 0)
        st.caption(
            f"Rebota entre **{_ymin_disp} m** y **{_ymax_disp} m**"
            + (f"  ·  **{_pasadas}** inversiones" if state.running else "")
        )

    st.divider()
    st.markdown("##### Conexión externa")
    # Solo una opción activa a la vez: GPS directo o caja de interfaz Arduino
    st.radio(
        "Modo de conexión",
        options=["ninguno", "gps", "caja"],
        format_func=lambda k: {
            "ninguno": "Sin conexión",
            "gps":     "GPS directo  (cable cruzado, 9 600 baud)",
            "caja":    "Caja de interfaz Arduino  (115 200 baud)",
        }[k],
        key="k_conexion_modo",
        disabled=locked,
        label_visibility="collapsed",
    )
    _modo   = state.get("k_conexion_modo", "ninguno")
    gps_on  = (_modo == "gps")
    caja_on = (_modo == "caja")

    _SIN_PUERTO = "— Sin puerto (solo consola) —"
    if _SERIAL_DISPONIBLE:
        _puertos_serie = [p.device for p in _list_ports.comports()]
    else:
        _puertos_serie = []

    if gps_on:
        # GPS directo: envía LAT:xxx,LON:xxx al otro PC (cable cruzado, 9 600 baud)
        gps_torre = st.selectbox(
            "Torre con el GPS",
            options=list(range(1, tramos)),
            key="k_gps_torre",
            disabled=locked,
            format_func=lambda i: f"Intermedia {i}",
        )
        c_lat, c_lon = st.columns(2)
        c_lat.number_input("Lat. origen (°)", value=40.4168, format="%.4f",
                           key="k_gps_lat", disabled=locked)
        c_lon.number_input("Lon. origen (°)", value=-3.7038, format="%.4f",
                           key="k_gps_lon", disabled=locked)
        st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie</p>',
                    unsafe_allow_html=True)
        c_puerto, c_refresh = st.columns([6, 1])
        with c_puerto:
            st.selectbox("Puerto serie",
                         options=[_SIN_PUERTO] + _puertos_serie,
                         key="k_gps_puerto", disabled=locked, label_visibility="collapsed")
        with c_refresh:
            if st.button("↺", help="Actualizar puertos", disabled=locked, width="stretch"):
                st.rerun()

    if caja_on:
        # Caja de interfaz: bidireccional con Arduino (envía GPS, recibe slow-down)
        st.selectbox(
            "Torre GPS", options=list(range(1, tramos)),
            key="k_caja_torre", disabled=locked,
            format_func=lambda i: f"Intermedia {i}",
            help="Torre cuya posición se envía al Arduino como coordenada GPS.",
        )
        # Carr=2 fijo: el gemelo conoce la posición exacta, siempre reportamos RTK FIX
        st.session_state["k_caja_carr"] = 2
        c_lat_c, c_lon_c = st.columns(2)
        c_lat_c.number_input("Lat. origen (°)", value=40.4168, format="%.4f",
                              key="k_caja_lat", disabled=locked)
        c_lon_c.number_input("Lon. origen (°)", value=-3.7038, format="%.4f",
                              key="k_caja_lon", disabled=locked)
        st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie Arduino</p>',
                    unsafe_allow_html=True)
        _SIN_CAJA_PUERTO = "— Selecciona puerto —"
        c_pcaja, c_rcaja = st.columns([6, 1])
        with c_pcaja:
            st.selectbox(
                "Puerto serie caja",
                options=_puertos_serie if _puertos_serie else [_SIN_CAJA_PUERTO],
                key="k_caja_puerto", disabled=locked, label_visibility="collapsed",
            )
        with c_rcaja:
            if st.button("↺", help="Actualizar puertos", disabled=locked,
                         width="stretch", key="btn_ref_caja"):
                st.rerun()
        st.caption("Arduino conectado a este PC · cable USB normal · Carr=2 (RTK FIX) fijo")

    st.divider()

    # Controles
    if state.lineal is None:
        if st.button("INICIAR", key="btn_iniciar", type="primary", width="stretch"):
            _ruido_terreno = _TERRENOS.get(st.session_state.get("k_terreno", "Normal"), 0.012)
            state.lineal = Lineal(
                numero_tramos        = tramos,
                longitud_tramo       = t_len,
                velocidad_porcentaje = vel_pct,
                velocidad_nominal    = v_nom,
                ruido_lateral        = _ruido_terreno,
            )
            state.lineal.start()
            state.log.append({"t": "00h 00m 00s", "tipo": "START", "msg": "Sistema iniciado"})
            _modo_cx = st.session_state.get("k_conexion_modo", "ninguno")
            if _modo_cx == "gps":
                _SIN_PUERTO = "— Sin puerto (solo consola) —"
                puerto_raw = st.session_state.get("k_gps_puerto", _SIN_PUERTO)
                puerto = None if (puerto_raw == _SIN_PUERTO) else puerto_raw
                state.lineal.asignar_gps(
                    indice_torre    = st.session_state.get("k_gps_torre", 1),
                    lat_origen      = st.session_state.get("k_gps_lat", 40.4168),
                    lon_origen      = st.session_state.get("k_gps_lon", -3.7038),
                    puerto_serial   = puerto,
                    verbose_consola = (puerto is None),
                )
                state.lineal.gps.iniciar_transmision_background()
            if _modo_cx == "caja":
                _caja_puerto = st.session_state.get("k_caja_puerto", "")
                if _caja_puerto and _caja_puerto != "— Selecciona puerto —":
                    state.lineal.asignar_caja(
                        indice_torre  = st.session_state.get("k_caja_torre", 1),
                        lat_origen    = st.session_state.get("k_caja_lat", 40.4168),
                        lon_origen    = st.session_state.get("k_caja_lon", -3.7038),
                        puerto_serial = _caja_puerto,
                        carr          = st.session_state.get("k_caja_carr", 2),
                    )
                    state.lineal.caja_interfaz.iniciar()
            state.longitud_campo  = campo
            state.running         = True
            state.finished        = False
            state.paused          = False
            state.caja_slow_prev  = {"cart": False, "end": False, "safety": True}
            state.tower_trails    = [[] for _ in range(len(state.lineal.torres))]
            st.rerun()

    elif state.running:
        if st.button("STOP / PAUSAR", key="btn_stop", width="stretch"):
            state.lineal.stop()
            if state.lineal.gps:
                state.lineal.gps.detener_transmision_background()
            if state.lineal.caja_interfaz:
                state.lineal.caja_interfaz.detener()
            state.log.append({"t": state.lineal._tiempo_formateado(), "tipo": "STOP",
                               "msg": f"Sistema pausado en {state.lineal.posicion_norte:.2f} m"})
            state.running   = False
            state.paused    = True
            st.rerun()

    elif state.paused and not state.finished:
        bc1, bc2 = st.columns(2)
        if bc1.button("START / CONTINUAR", key="btn_start", type="primary", width="stretch"):
            state.lineal.start()
            if state.lineal.gps:
                state.lineal.gps.iniciar_transmision_background()
            state.log.append({"t": state.lineal._tiempo_formateado(), "tipo": "START",
                               "msg": f"Sistema reanudado desde {state.lineal.posicion_norte:.2f} m"})
            state.running = True
            state.paused  = False
            st.rerun()
        if bc2.button("RESET", key="btn_reset", width="stretch"):
            if state.lineal and state.lineal.gps:
                state.lineal.gps.detener_transmision_background()
            if state.lineal and state.lineal.caja_interfaz:
                state.lineal.caja_interfaz.detener()
            for k, v in defaults.items():
                state[k] = v
            st.rerun()

    elif state.finished:
        if st.button("REINICIAR", key="btn_reiniciar", type="primary", width="stretch"):
            if state.lineal and state.lineal.gps:
                state.lineal.gps.detener_transmision_background()
            if state.lineal and state.lineal.caja_interfaz:
                state.lineal.caja_interfaz.detener()
            for k, v in defaults.items():
                state[k] = v
            st.rerun()

    st.divider()
    st.markdown("##### Teclado (simulación activa)")
    for _key, _desc in [
        ("< (mantener)", "Ralentiza Cart — sigue motor rápido, giro gradual izquierda"),
        ("- (mantener)", "Ralentiza End-tower — sigue motor rápido, giro gradual derecha"),
        ("R (pulsar)",   "Marcha atrás / avance normal"),
    ]:
        st.markdown(
            f"<code style='background:#161b22;border:1px solid #30363d;border-radius:4px;"
            f"padding:1px 6px;font-size:0.78rem;color:#e6edf3'>{_key}</code>"
            f"<span style='color:#8b949e;font-size:0.78rem;margin-left:6px'>{_desc}</span>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("##### Leyenda")
    for color, name, desc in [
        ("#f78166", "Guia Izq (Cart)",   "Motor + set speed · cascada izq"),
        ("#d2a8ff", "End-tower",        "Motor + set speed · cascada der"),
        ("#58a6ff", "Intermedia izq",   "Sigue guia izquierda"),
        ("#56d364", "Intermedia der",   "Sigue guia derecha"),
        ("#ffa657", "Motor rapido [R]", "Extremo der del tramo rigido"),
        ("#ffa657", "Zona rigida",      "Free Standing Span central"),
        ("#3fb950", "Alineado",         "Desv < 5 cm, angulo < 0.5 grd"),
        ("#e3b341", "Advertencia",      "Desv < 5 cm, angulo >= 0.5 grd"),
        ("#f85149", "Desalineado",      "Desv >= 5 cm"),
        ("#58d68d", "GPS activo",       "Torre con unidad GPS"),
    ]:
        st.markdown(
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"border-radius:50%;background:{color};margin-right:8px;vertical-align:middle'></span>"
            f"<b>{name}</b> <span style='color:#8b949e;font-size:0.82rem'>— {desc}</span>",
            unsafe_allow_html=True,
        )


# Funciones de la figura Plotly (definidas fuera del fragment)
def _tramo_color(tramo) -> str:
    if not tramo.esta_alineado:
        return "#f85149"
    ang = abs(tramo.angulo_grados)
    if ang < 0.5:
        return "#3fb950"
    return "#e3b341"


def _torre_style(lineal: Lineal, i: int):
    """Devuelve (color, simbolo, etiqueta, tamaño) para la torre i."""
    torre = lineal.torres[i]
    n     = len(lineal.torres)
    if i == 0:
        return "#f78166", "square", "CART", 20
    if i == n - 1:
        return "#d2a8ff", "square", "END", 20
    if isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
        return "#ffa657", "star", f"I{i}★", 18
    if i <= lineal.indice_tramo_rigido:
        return "#58a6ff", "circle", f"I{i}", 14
    return "#56d364", "circle", f"I{i}", 14


def build_figure(lineal: Lineal | None, longitud_campo: float, pos_norte: float = 0.0,
                 vista_general: bool = False, tower_trails: list | None = None) -> go.Figure:
    if lineal is None:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#0a1f10",
            height=560, margin=dict(l=0, r=0, t=0, b=0),
            annotations=[dict(
                text="Configura el lineal en el panel izquierdo y pulsa  INICIAR",
                xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                font=dict(size=15, color="#8b949e"),
            )],
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig

    fw, fh = lineal.longitud_total, longitud_campo
    traces, shapes, annotations = [], [], []

    # Viewport Y: calcula el rango visible para mantener escala 1:1 (scaleanchor en Plotly).
    # Los px estiman el área de trazado en pantalla wide típica (sidebar ~340 px).
    _INNER_W_PX = 960   # px — ancho interior
    _INNER_H_PX = 660   # px — alto objetivo
    _MARGIN_V   = 140   # px — márgenes top+bottom

    pad_x  = fw * 0.06
    _pad_y = max(20.0, fw * 0.05)

    if not vista_general:
        x_range_m = fw + 2 * pad_x
        # metros en Y para que _INNER_H_PX píxeles = 1:1 con _INNER_W_PX píxeles en X
        viewport_h  = x_range_m * _INNER_H_PX / _INNER_W_PX - 2 * _pad_y
        viewport_h  = max(viewport_h, fw * 0.25)    # mínimo 25% de fw
        _full_range = viewport_h + 2 * _pad_y       # rango total de datos en Y

        if _full_range >= fh + 2 * _pad_y:
            # viewport mayor que el campo → campo completo
            y_lo = -_pad_y
            y_hi = fh + _pad_y
        else:
            # lineal al 30 % desde el fondo del viewport; desliza hacia el norte
            y_lo = pos_norte - viewport_h * 0.30 - _pad_y
            y_hi = y_lo + _full_range
            if y_lo < -_pad_y:          # clamp inferior: margen visual bajo el lineal
                y_lo = -_pad_y
                y_hi = y_lo + _full_range
            if y_hi > fh + _pad_y:      # clamp superior: margen visual sobre el campo
                y_hi = fh + _pad_y
                y_lo = y_hi - _full_range

        # Altura de figura proporcional al viewport (se ajusta si el campo es corto)
        y_range_m  = y_hi - y_lo
        fig_height = int(_INNER_W_PX * y_range_m / x_range_m) + _MARGIN_V
        fig_height = max(400, min(fig_height, 950))
        use_scaleanchor = True
    else:
        # Vista general: campo completo sin restricción de escala
        y_lo = -fh * 0.20
        y_hi = fh + fh * 0.20
        fig_height = 620
        use_scaleanchor = False

    # Fondo del campo
    shapes.append(dict(type="rect", xref="x", yref="y",
        x0=0, y0=0, x1=fw, y1=fh,
        fillcolor="#0a1f10", line=dict(color="#30363d", width=1), layer="below"))

    # Zona ya irrigada
    min_y = min(t.posicion_y for t in lineal.torres)
    if min_y > 0.1:
        shapes.append(dict(type="rect", xref="x", yref="y",
            x0=0, y0=0, x1=fw, y1=min_y,
            fillcolor="rgba(63,185,80,0.10)", line=dict(width=0), layer="below"))

    # Lineas de cultivo sutiles (horizontales)
    row_step = max(2, int((y_hi - y_lo) / 40))
    gx, gy = [], []
    for y in range(0, int(fh) + 1, row_step):
        gx += [0, fw, None]; gy += [y, y, None]
    traces.append(go.Scatter(x=gx, y=gy, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1),
        hoverinfo="skip", showlegend=False))

    # Lineas de posicion de torres (verticales)
    vx, vy = [], []
    for i in range(lineal.numero_tramos + 1):
        xv = i * lineal.longitud_tramo
        vx += [xv, xv, None]; vy += [0, fh, None]
    traces.append(go.Scatter(x=vx, y=vy, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False))

    # Zona del tramo rigido
    k   = lineal.indice_tramo_rigido
    rx1 = lineal.torres[k].posicion_x
    rx2 = lineal.torres[k + 1].posicion_x
    shapes.append(dict(type="rect", xref="x", yref="paper",
        x0=rx1, y0=0, x1=rx2, y1=1,
        fillcolor="rgba(255,166,87,0.07)",
        line=dict(color="rgba(255,166,87,0.30)", width=1, dash="dot"),
        layer="below"))

    annotations.append(dict(
        x=(rx1 + rx2) / 2, y=1.0,
        text="TRAMO RIGIDO",
        showarrow=False,
        font=dict(color="#ffa657", size=13, family="monospace"),
        bgcolor="rgba(13,17,23,0.6)",
        bordercolor="#ffa657", borderwidth=1,
        xref="x", yref="paper",
        yanchor="top",
    ))

    # Trayectorias históricas de cada torre
    if tower_trails:
        for _ti in range(len(lineal.torres)):
            _trail = tower_trails[_ti] if _ti < len(tower_trails) else []
            if len(_trail) < 2:
                continue
            _tc, _, _, _ = _torre_style(lineal, _ti)
            traces.append(go.Scatter(
                x=[p[0] for p in _trail],
                y=[p[1] for p in _trail],
                mode="lines",
                line=dict(color=_tc, width=1.5),
                opacity=0.35,
                hoverinfo="skip",
                showlegend=False,
            ))

    # Tramos
    for idx, tramo in enumerate(lineal.tramos):
        x1 = tramo.torre_izquierda.posicion_x
        y1 = tramo.torre_izquierda.posicion_y
        x2 = tramo.torre_derecha.posicion_x
        y2 = tramo.torre_derecha.posicion_y
        ang   = tramo.angulo_grados
        color = _tramo_color(tramo)

        hover = (
            f"<b>Tramo {idx + 1}{'  [RIGIDO]' if tramo.es_rigido else ''}</b><br>"
            f"Angulo:    <b>{ang:+.3f} grd</b><br>"
            f"Desviacion: {tramo.desviacion_norte:+.3f} m<br>"
            f"Estado: {'OK' if tramo.esta_alineado else 'DESVIADO'}"
            f"<extra></extra>"
        )

        if tramo.es_rigido:
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color="#ffa657", width=28), opacity=0.15,
                hoverinfo="skip", showlegend=False))
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=8),
                hovertemplate=hover, showlegend=False))
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color="#ffa657", width=3, dash="dash"),
                hoverinfo="skip", showlegend=False))
        else:
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=14), opacity=0.12,
                hoverinfo="skip", showlegend=False))
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=4),
                hovertemplate=hover, showlegend=False))

        # Anotacion en el punto medio de TODOS los tramos
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # Texto usa el color de alineacion (verde/amarillo/rojo)
        ann_text_color = color
        # Borde naranja para el FSS, color de alineacion para el resto
        ann_border = "#ffa657" if tramo.es_rigido else color
        header_txt = f"T{idx + 1}  FSS" if tramo.es_rigido else f"T{idx + 1}"
        annotations.append(dict(
            x=mx, y=my,
            text=(
                f"<b>{header_txt}</b><br>"
                f"{ang:+.2f}\u00b0<br>"
                f"{tramo.desviacion_norte:+.3f} m"
            ),
            showarrow=False,
            font=dict(color=ann_text_color, size=11, family="monospace"),
            bgcolor="rgba(13,17,23,0.82)",
            bordercolor=ann_border, borderwidth=1,
            borderpad=5,
            xref="x", yref="y",
            align="center",
        ))

    # Torres
    n       = len(lineal.torres)
    gps_idx = lineal.torres.index(lineal.gps.torre) if lineal.gps else -1
    for i, torre in enumerate(lineal.torres):
        color, sym, label, sz = _torre_style(lineal, i)

        if i == 0:
            nombre = "Guia Izq (Cart)"
        elif i == n - 1:
            nombre = "End-tower"
        elif isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
            nombre = f"Intermedia {i}  [Motor Rapido — extremo der tramo rigido]"
        elif i <= lineal.indice_tramo_rigido:
            nombre = f"Intermedia {i}  [cascada izquierda]"
        else:
            nombre = f"Intermedia {i}  [cascada derecha]"

        cont_cerrado = torre.contactor.esta_cerrado

        # Detectar si esta torre guía está en modo slow_down (duty cycle reducido al 25%).
        # El flag vive en lineal directamente — lo activa la caja Arduino O el teclado.
        _en_slow_down = (
            isinstance(torre, Torre_Guia) and (
                (i == 0                      and lineal.slow_down_cart)      or
                (i == len(lineal.torres) - 1 and lineal.slow_down_end_tower)
            )
        )

        if isinstance(torre, Torre_Guia):
            if _en_slow_down:
                cont_txt = f"Contactor: {'ON' if cont_cerrado else 'OFF'}  (sigue motor rápido)"
            else:
                cont_txt = f"Contactor: {'ON' if cont_cerrado else 'OFF'}  (set speed {torre.contactor.duty_cycle*100:.0f}%)"
        else:
            cont_txt = f"Contactor: {'ON — desalineada' if cont_cerrado else 'OFF — alineada'}"

        gps_hover = ""
        if i == gps_idx:
            g = lineal.gps
            gps_hover = (
                f"<br><span style='color:#58d68d'>&#128225; GPS</span><br>"
                f"LAT: <b>{g.lat_e7}</b><br>"
                f"LON: <b>{g.lon_e7}</b>"
            )
        hover = (
            f"<b>{nombre}</b><br>"
            f"X = {torre.posicion_x:.0f} m<br>"
            f"Y = {torre.posicion_y:.3f} m<br>"
            f"{cont_txt}"
            f"{gps_hover}"
            f"<extra></extra>"
        )

        borde_color = "#3fb950" if cont_cerrado else "#484f58"

        if isinstance(torre, Torre_Guia):
            if _en_slow_down:
                if cont_cerrado:
                    estado_txt, estado_color = "Motor ON  ·  (sigue rápido)", "#e3b341"
                else:
                    estado_txt, estado_color = "Motor OFF  ·  (sigue rápido)", "#8b949e"
            else:
                estado_txt   = f"Speed {torre.contactor.duty_cycle*100:.0f}%  {'ON' if cont_cerrado else 'OFF'}"
                estado_color = color
        else:
            if cont_cerrado:
                estado_txt, estado_color = "Corrigiendo  ·  Motor ON", "#e3b341"
            else:
                estado_txt, estado_color = "Alineada  ·  Motor OFF", "#3fb950"

        traces.append(go.Scatter(
            x=[torre.posicion_x], y=[torre.posicion_y], mode="markers",
            marker=dict(color=color, size=sz + 14, opacity=0.18, symbol=sym),
            hoverinfo="skip", showlegend=False))

        traces.append(go.Scatter(
            x=[torre.posicion_x], y=[torre.posicion_y],
            mode="markers",
            marker=dict(color=color, size=sz, symbol=sym,
                        line=dict(color=borde_color, width=2)),
            hovertemplate=hover,
            showlegend=False))

        # Patrón fijo: par → arriba, impar → abajo. Nunca cambia con la posición Y.
        ay_off = -90 if i % 2 == 0 else 90
        if i == gps_idx:
            ay_off = 90    # GPS sube (ay=-100) → etiqueta de esta torre baja para no solapar
        annotations.append(dict(
            x=torre.posicion_x, y=torre.posicion_y,
            xref="x", yref="y",
            text=f"<b>{label}</b>  X={torre.posicion_x:.2f} m  Y={torre.posicion_y:.2f} m<br>{estado_txt}",
            showarrow=True,
            arrowhead=2, arrowwidth=1.5, arrowsize=0.7,
            arrowcolor=color,
            ax=0, ay=ay_off,
            font=dict(color=estado_color, size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor=estado_color, borderwidth=1, borderpad=10,
            align="center",
        ))

    # GPS: halo + marcador + anotacion
    if lineal.gps is not None:
        gps    = lineal.gps
        gx, gy = gps.torre.posicion_x, gps.torre.posicion_y

        traces.append(go.Scatter(
            x=[gx], y=[gy], mode="markers",
            marker=dict(color="#58d68d", size=42, opacity=0.15, symbol="circle"),
            hoverinfo="skip", showlegend=False,
        ))
        traces.append(go.Scatter(
            x=[gx], y=[gy], mode="markers",
            marker=dict(color="#58d68d", size=12, symbol="circle-cross-open",
                        line=dict(color="#58d68d", width=2.5)),
            hovertemplate=(
                f"<b>GPS</b><br>"
                f"LAT: <b>{gps.lat_e7}</b><br>"
                f"LON: <b>{gps.lon_e7}</b><br>"
                f"{gps.latitud:.7f}°,  {gps.longitud:.7f}°"
                f"<extra></extra>"
            ),
            showlegend=False,
        ))
        annotations.append(dict(
            x=gx, y=gy, xref="x", yref="y",
            text=f"<b>GPS</b><br>{gps.latitud:.5f}°<br>{gps.longitud:.5f}°",
            showarrow=True,
            arrowhead=2, arrowwidth=1.5, arrowsize=0.7, arrowcolor="#58d68d",
            ax=0, ay=-100,  # sube sobre el marcador, lejos del span y de las anotaciones de tramos
            font=dict(color="#58d68d", size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor="#58d68d", borderwidth=1, borderpad=10,
            align="center",
        ))

    # Ticks Y: solo desde 0 hasta fh, sin negativos ni sobrepasar el campo
    _nice_steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
    _tick_step  = next((s for s in _nice_steps if fh / s <= 15), 1000)
    _tickvals   = list(range(0, int(fh) + _tick_step + 1, _tick_step))

    fig = go.Figure(data=traces)
    _yaxis = dict(
        title=dict(text="Norte  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False,
        range=[y_lo, y_hi],
        tickmode="array", tickvals=_tickvals,
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    _xaxis = dict(
        title=dict(text="Oeste  —  Este  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False,
        range=[-pad_x, fw + pad_x],
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    if use_scaleanchor:
        _yaxis["scaleanchor"] = "x"
        _yaxis["scaleratio"]  = 1
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0a1f10",
        height=fig_height,
        margin=dict(l=70, r=40, t=90, b=50),
        xaxis=_xaxis,
        yaxis=_yaxis,
        shapes=shapes,
        annotations=annotations,
        hovermode="closest",
        dragmode="pan",
    )
    return fig


# Panel principal: fragment que se refresca cada segundo (sidebar permanece estable)
@st.fragment(run_every=1)
def panel_principal():
    state          = st.session_state
    lineal: Lineal | None = state.lineal
    longitud_campo = state.longitud_campo

    if lineal is not None:
        lineal.set_speed(state.get("k_vpct", 50))
        _ruido_live = _TERRENOS.get(state.get("k_terreno", "Normal"), 0.012)
        lineal.guia_izquierda.ruido_lateral = _ruido_live
        lineal.guia_derecha.ruido_lateral   = _ruido_live

    # Caja de interfaz: procesa comandos del algoritmo de guiado GPS
    if state.running and lineal is not None and lineal.caja_interfaz:
        caja  = lineal.caja_interfaz
        prev  = state.caja_slow_prev

        # Detectar cambios de slow_down y registrarlos en el log
        if caja.slow_down_cart != prev["cart"]:
            prev["cart"] = caja.slow_down_cart
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_CART ON — Cart ralentizado, giro gradual hacia izquierda"
                        if caja.slow_down_cart else "SLOW_DOWN_CART OFF — Cart a velocidad normal"),
            })
        if caja.slow_down_end_tower != prev["end"]:
            prev["end"] = caja.slow_down_end_tower
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_END_TOWER ON — End-tower ralentizado, giro gradual hacia derecha"
                        if caja.slow_down_end_tower else "SLOW_DOWN_END_TOWER OFF — End-tower a velocidad normal"),
            })

        # Propagar los flags de la caja al modelo para que avanza() los lea
        lineal.slow_down_cart      = caja.slow_down_cart
        lineal.slow_down_end_tower = caja.slow_down_end_tower

        if not caja.safety_ok and prev["safety"]:
            prev["safety"] = False
            lineal.stop()
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "CRIT",
                "msg": "SAFETY_FAIL — parada de emergencia",
            })
            state.running = False
            state.paused  = True
        elif caja.safety_ok and not prev["safety"]:
            prev["safety"] = True
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "OK",
                "msg": "SAFETY_OK — seguridad restaurada (reanuda manualmente)",
            })

    # Avance de simulacion
    if state.running and not state.finished and lineal is not None:
        sim_spd_val = state.get("k_simspd", 60)
        lineal.avanza(sim_spd_val, transmitir_gps=False)
        # GPS: el hilo background (iniciado en INICIAR) transmite por su cuenta

        # Registro de trayectorias para el renderizado
        if state.tower_trails is not None and len(state.tower_trails) == len(lineal.torres):
            for _ti, _torre in enumerate(lineal.torres):
                state.tower_trails[_ti].append((_torre.posicion_x, _torre.posicion_y))
            if len(state.tower_trails[0]) > 2000:
                state.tower_trails = [tr[-2000:] for tr in state.tower_trails]

        # Velocidad real (m/min) entre este frame y el anterior
        state.vel_real = (lineal.posicion_norte - state.pos_prev) / (sim_spd_val / 60.0)
        state.pos_prev = lineal.posicion_norte

        # Fila para CSV
        fila = {
            "tiempo_s":        lineal.tiempo_total_segundos,
            "tiempo":          lineal._tiempo_formateado(),
            "posicion_norte":  round(lineal.posicion_norte, 3),
            "alineado":        lineal.esta_alineado,
        }
        for j, t in enumerate(lineal.torres):
            fila[f"torre_{j}_y"] = round(t.posicion_y, 3)
        if lineal.gps:
            fila["lat_e7"] = lineal.gps.lat_e7
            fila["lon_e7"] = lineal.gps.lon_e7
        state.historial.append(fila)

        # GPS track (últimas 20 lecturas)
        if lineal.gps:
            state.gps_track.append({
                "Tiempo":    lineal._tiempo_formateado(),
                "LAT ×10⁷": lineal.gps.lat_e7,
                "LON ×10⁷": lineal.gps.lon_e7,
                "Lat (°)":   round(lineal.gps.latitud, 7),
                "Lon (°)":   round(lineal.gps.longitud, 7),
            })
            if len(state.gps_track) > 20:
                state.gps_track = state.gps_track[-20:]

        # Log: detectar cambios de alineacion en tramos
        tramos_ok = [t.esta_alineado for t in lineal.tramos]
        if state.tramos_ok_prev is not None:
            for j, (prev, curr) in enumerate(zip(state.tramos_ok_prev, tramos_ok)):
                if prev and not curr:
                    state.log.append({
                        "t":    lineal._tiempo_formateado(),
                        "tipo": "CRIT",
                        "msg":  f"Tramo {j+1} desalineado  ({lineal.tramos[j].desviacion_norte:+.3f} m)",
                    })
                elif not prev and curr:
                    state.log.append({
                        "t":    lineal._tiempo_formateado(),
                        "tipo": "OK",
                        "msg":  f"Tramo {j+1} recuperado",
                    })
        state.tramos_ok_prev = tramos_ok

        # Límites del campo: auto-reverse o parada normal
        _ar_on   = state.get("k_auto_reverse", False)
        _ar_ymin = float(state.get("k_ar_ymin", 0))
        _ar_ymax = float(state.get("k_ar_ymax", longitud_campo))

        if _ar_on:
            # Comprobamos ambos extremos independientemente de la dirección actual
            # para capturar el caso en que la velocidad de simulación es alta y
            # el centroide del lineal ya está al otro lado cuando se evalúa el tick.
            _pos = lineal.posicion_norte
            if not lineal.en_marcha_atras and _pos >= _ar_ymax:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▼  ({_pos:.1f} m ≥ {_ar_ymax:.0f} m)  "
                            f"— pasada #{state.ar_pasadas}",
                })
            elif lineal.en_marcha_atras and _pos <= _ar_ymin:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▲  ({_pos:.1f} m ≤ {_ar_ymin:.0f} m)  "
                            f"— pasada #{state.ar_pasadas}",
                })
        else:
            if lineal.posicion_norte >= longitud_campo:
                lineal.stop()
                if lineal.gps:
                    lineal.gps.detener_transmision_background()
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "FIN",
                    "msg":  f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}",
                })
                state.running  = False
                state.finished = True
                st.rerun()
                return

    # CABECERA
    st.markdown("# Gemelo Digital Lineal")

    if state.finished:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:10px;"
            f"background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.25);"
            f"border-radius:20px;padding:6px 16px;margin:4px 0'>"
            f"<span style='color:#3fb950;font-size:1rem'>✓</span>"
            f"<span style='color:#3fb950;font-weight:600;letter-spacing:1px;font-size:0.85rem'>RIEGO COMPLETADO</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal._tiempo_formateado()}</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal.ciclo_actual} ciclos</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal.posicion_norte:.1f} m</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif state.running:
        _en_atras  = lineal is not None and lineal.en_marcha_atras
        _ar_active = state.get("k_auto_reverse", False)
        _badge_color  = "#ff7b72" if _en_atras else "#3fb950"
        _badge_bg     = "rgba(255,123,114,0.08)" if _en_atras else "rgba(63,185,80,0.08)"
        _badge_border = "rgba(255,123,114,0.25)" if _en_atras else "rgba(63,185,80,0.25)"
        _badge_label  = "&#9660; MARCHA ATRÁS" if _en_atras else "&#9650; EN MARCHA"
        _ar_suffix = (
            f"&nbsp;<span style='color:#8b949e;font-weight:400;font-size:0.75rem;letter-spacing:1px'>"
            f"AUTO-REVERSE · {state.ar_pasadas} inv.</span>"
            if _ar_active else ""
        )
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:8px;"
            f"background:{_badge_bg};border:1px solid {_badge_border};"
            f"border-radius:20px;padding:5px 14px;margin:4px 0'>"
            f"<span style='width:8px;height:8px;border-radius:50%;background:{_badge_color};"
            f"display:inline-block;box-shadow:0 0 6px {_badge_color}'></span>"
            f"<span style='color:{_badge_color};font-weight:600;letter-spacing:2px;font-size:0.85rem'>"
            f"{_badge_label}</span>"
            f"{_ar_suffix}"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif state.paused:
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(227,179,65,0.08);border:1px solid rgba(227,179,65,0.25);"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#e3b341;"
            "display:inline-block'></span>"
            "<span style='color:#e3b341;font-weight:600;letter-spacing:2px;font-size:0.85rem'>PAUSADO</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(139,148,158,0.06);border:1px solid #21262d;"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#484f58;"
            "display:inline-block'></span>"
            "<span style='color:#8b949e;letter-spacing:1px;font-size:0.85rem'>"
            "Configura el lineal en el panel izquierdo y pulsa INICIAR</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    # METRICAS
    cols_m = st.columns(10)
    if lineal:
        porcentaje  = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        vel_teorica = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        vel_real    = state.get("vel_real", 0.0)
        delta_vel   = vel_real - vel_teorica
        cols_m[0].metric("Tiempo campo",    lineal._tiempo_formateado())
        cols_m[1].metric("Ciclo",           str(lineal.ciclo_actual))
        cols_m[2].metric("Posición media",  f"{lineal.posicion_norte:.2f} m")
        cols_m[3].metric("Recorrido",       f"{porcentaje:.1f} %")
        cols_m[4].metric("Alineación",      "OK" if lineal.esta_alineado else "Corrigiendo")
        _slow_c = lineal.slow_down_cart
        _slow_e = lineal.slow_down_end_tower
        _cart_val = ("★ ON" if lineal.guia_izquierda.contactor.esta_cerrado else "★ OFF") if _slow_c else \
                    ("ON"   if lineal.guia_izquierda.contactor.esta_cerrado else "OFF")
        _end_val  = ("★ ON" if lineal.guia_derecha.contactor.esta_cerrado   else "★ OFF") if _slow_e else \
                    ("ON"   if lineal.guia_derecha.contactor.esta_cerrado   else "OFF")
        cols_m[5].metric("Guia Izq (Cart)", _cart_val,
                          help="★ = en slow_down, sigue al motor rápido" if _slow_c else None)
        cols_m[6].metric("End-tower",       _end_val,
                          help="★ = en slow_down, sigue al motor rápido" if _slow_e else None)
        cols_m[7].metric("Vel. real",       f"{vel_real:.2f} m/min",
                          delta=f"{delta_vel:+.2f} vs teórica",
                          delta_color="normal")
        cols_m[8].metric("Motor ★ activo",  f"{lineal.motor_rapido_pct_on:.0f} %",
                          help="% del último ciclo completo (60 s sim.) con el motor rápido encendido")
        cols_m[9].metric("Dirección",
                          "▼ ATRÁS" if lineal.en_marcha_atras else "▲ ADELANTE",
                          help="S = alternar marcha atrás / avance normal")
    else:
        for col in cols_m:
            col.metric("—", "—")

    # BARRA DE PROGRESO
    if lineal:
        _ar_on_bar  = state.get("k_auto_reverse", False)
        _ar_ymin_b  = float(state.get("k_ar_ymin", 0))
        _ar_ymax_b  = float(state.get("k_ar_ymax", longitud_campo))

        if _ar_on_bar:
            # Barra bidireccional: muestra posición dentro del rango [ymin, ymax]
            _ar_span      = max(_ar_ymax_b - _ar_ymin_b, 1.0)
            _pos_clamped  = max(_ar_ymin_b, min(_ar_ymax_b, lineal.posicion_norte))
            _pct_bar      = (_pos_clamped - _ar_ymin_b) / _ar_span * 100.0
            # El indicador de "cabeza" es un marcador deslizante en vez de relleno progresivo
            _bar_color    = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
            _dir_arrow    = "▼" if lineal.en_marcha_atras else "▲"
            _pasadas_txt  = f"{state.ar_pasadas} inversiones"
            _rango_label  = f"{_ar_ymin_b:.0f} m — {_ar_ymax_b:.0f} m"
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
                f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
                f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
                f"margin-bottom:10px'>"
                f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;"
                f"text-transform:uppercase;font-family:monospace'>"
                f"Auto-reverse  ·  {_rango_label}</span>"
                f"<span style='color:{_bar_color};font-size:1.5rem;font-weight:700;"
                f"font-family:monospace;line-height:1'>"
                f"{_dir_arrow}&nbsp;{lineal.posicion_norte:.1f}"
                f"<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
                f"</div>"
                # Pista de fondo gris + posición del lineal como marcador deslizante
                f"<div style='position:relative;background:#21262d;border-radius:4px;"
                f"height:8px;margin-bottom:8px'>"
                f"<div style='position:absolute;left:0;top:0;"
                f"background:rgba(63,185,80,0.12);border-radius:4px;"
                f"width:{_pct_bar:.2f}%;height:100%'></div>"
                f"<div style='position:absolute;top:-3px;"
                f"left:calc({_pct_bar:.2f}% - 7px);width:14px;height:14px;"
                f"border-radius:50%;background:{_bar_color};"
                f"box-shadow:0 0 6px {_bar_color}'></div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='color:{_bar_color};font-size:0.82rem;font-weight:600;"
                f"font-family:monospace'>{_pasadas_txt}</span>"
                f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>"
                f"rango {_ar_span:.0f} m</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
                f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
                f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
                f"margin-bottom:10px'>"
                f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;"
                f"text-transform:uppercase;font-family:monospace'>Recorrido del campo</span>"
                f"<span style='color:#e6edf3;font-size:1.5rem;font-weight:700;font-family:monospace;"
                f"line-height:1'>{porcentaje:.1f}"
                f"<span style='color:#8b949e;font-size:0.9rem'>%</span></span>"
                f"</div>"
                f"<div style='background:#21262d;border-radius:4px;height:6px;overflow:hidden;"
                f"margin-bottom:8px'>"
                f"<div style='background:linear-gradient(90deg,#238636 0%,#3fb950 100%);"
                f"width:{porcentaje:.2f}%;height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='color:#3fb950;font-size:0.82rem;font-weight:600;font-family:monospace'>"
                f"{lineal.posicion_norte:.1f} m avanzados</span>"
                f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>"
                f"meta {longitud_campo:.0f} m</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

    # METRICAS GPS
    if lineal and lineal.gps:
        gps     = lineal.gps
        gps_idx = lineal.torres.index(gps.torre)
        cg      = st.columns(4)
        # Derivar lat/lon del entero ×10⁷ → exactamente lo que viaja por el serie
        ui_lat = gps.lat_e7 / 1e7
        ui_lon = gps.lon_e7 / 1e7
        prev    = state.gps_prev
        delta_lat = round(ui_lat - prev["lat"], 7) if prev else None
        delta_lon = round(ui_lon - prev["lon"], 7) if prev else None
        cg[0].metric("GPS · Torre",  f"Intermedia {gps_idx}")
        cg[1].metric("Latitud",      f"{ui_lat:.7f}°",
                     delta=f"{delta_lat:+.7f}°" if delta_lat is not None else None)
        cg[2].metric("Longitud",     f"{ui_lon:.7f}°",
                     delta=f"{delta_lon:+.7f}°" if delta_lon is not None else None)
        cg[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")
        state.gps_prev = {"lat": ui_lat, "lon": ui_lon}

    # CAJA DE INTERFAZ — estado en tiempo real
    if lineal and lineal.caja_interfaz:
        caja    = lineal.caja_interfaz
        caja_idx = lineal.torres.index(caja.torre)
        # Colores de estado: verde = OK / activo, rojo = FAIL / activo
        _c_safe = "#3fb950" if caja.safety_ok else "#f85149"
        _c_gps  = "#3fb950" if caja.gps_ok    else "#f85149"
        _c_cart = "#ffa657" if caja.slow_down_cart      else "#484f58"
        _c_end  = "#ffa657" if caja.slow_down_end_tower else "#484f58"
        cc = st.columns(6)
        cc[0].metric("Caja · Torre GPS",    f"Intermedia {caja_idx}")
        cc[1].metric("GPS enviado",
                     f"{caja.lat_e7} / {caja.lon_e7}",
                     help=f"{caja.latitud:.7f}°  {caja.longitud:.7f}°  Carr {caja.carr}")
        cc[2].metric("Safety",     "OK" if caja.safety_ok else "FAIL")
        cc[3].metric("GPS status", "OK" if caja.gps_ok    else "FAIL")
        cc[4].metric("Slow Cart",  "ON" if caja.slow_down_cart      else "—")
        cc[5].metric("Slow EndT",  "ON" if caja.slow_down_end_tower else "—")
        # Colorear los estados con CSS inline
        st.markdown(
            f"<div style='display:flex;gap:8px;margin:-12px 0 8px 0;flex-wrap:wrap'>"
            f"<span style='font-size:0.72rem;color:{_c_safe};font-family:monospace'>"
            f"&#9679; SAFETY {'OK' if caja.safety_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.72rem;color:{_c_gps};font-family:monospace'>"
            f"&#9679; GPS {'OK' if caja.gps_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.72rem;color:{_c_cart};font-family:monospace'>"
            f"&#9679; SLOW_CART {'ON' if caja.slow_down_cart else 'OFF'}</span>"
            f"<span style='font-size:0.72rem;color:{_c_end};font-family:monospace'>"
            f"&#9679; SLOW_END_TWR {'ON' if caja.slow_down_end_tower else 'OFF'}</span>"
            f"<span style='font-size:0.72rem;color:#484f58;font-family:monospace'>"
            f"último msg: {caja.ultimo_mensaje or '—'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # FILA COMPACTA: CSV · LOG · GPS TRACK  (encima del campo, sin scroll)
    if lineal:
        col_csv, col_log, col_gps = st.columns([1, 2, 4])

        with col_csv:
            if state.historial:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=list(state.historial[0].keys()))
                writer.writeheader()
                writer.writerows(state.historial)
                st.download_button(
                    label="⬇ CSV",
                    data=buf.getvalue(),
                    file_name="simulacion_lineal.csv",
                    mime="text/csv",
                    width="stretch",
                )

        with col_log:
            _TIPO_COLOR = {
                "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
                "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
            }
            entradas = state.log[-60:][::-1]
            with st.expander(f"Log  ({len(state.log)} entradas)", expanded=False):
                for e in entradas:
                    c = _TIPO_COLOR.get(e["tipo"], "#8b949e")
                    st.markdown(
                        f"<code style='color:#484f58;font-size:0.75rem'>{e['t']}</code>&nbsp;"
                        f"<span style='background:{c}22;color:{c};border-radius:4px;"
                        f"padding:1px 7px;font-size:0.68rem;font-family:monospace;"
                        f"font-weight:700'>{e['tipo']}</span>&nbsp;"
                        f"<span style='color:#e6edf3;font-size:0.82rem'>{e['msg']}</span>",
                        unsafe_allow_html=True,
                    )

        with col_gps:
            if state.gps_track:
                with st.expander(f"Track GPS — {len(state.gps_track)} lecturas", expanded=False):
                    st.dataframe(
                        state.gps_track[::-1],
                        hide_index=True,
                        width="stretch",
                    )

    # FIGURA
    _col_tog, _ = st.columns([1, 5])
    with _col_tog:
        st.toggle(
            "Vista general",
            key="k_vista_general",
            help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo",
        )
    _pos = lineal.posicion_norte if lineal is not None else 0.0
    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, _pos,
            st.session_state.get("k_vista_general", False),
            tower_trails=state.tower_trails,
        ),
        width="stretch",
        key="campo_pivot",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
            "toImageButtonOptions": {"filename": "lineal_fss", "format": "png"},
        },
    )


# Componente de teclado (bidireccional real, iframe persistente).
# Devuelve {left, right, reverse} en cada cambio de tecla.
_key_giro = _giro_kbd(default=None)
if isinstance(_key_giro, dict):

    # Marcha atrás (tecla R)
    _kbd_reverse_now  = _key_giro.get("reverse", False)
    _kbd_reverse_prev = st.session_state.marcha_atras_kbd
    if _kbd_reverse_now != _kbd_reverse_prev:
        st.session_state.marcha_atras_kbd = _kbd_reverse_now
        if st.session_state.lineal and st.session_state.running:
            _lin = st.session_state.lineal
            _lin.invertir_direccion()
            _dir_txt = "MARCHA ATRÁS activada" if _lin.en_marcha_atras else "Avance normal activado"
            st.session_state.log.append({
                "t":    _lin._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  _dir_txt,
            })

    # Ralentización por teclado: < → ralentiza Cart  /  - → ralentiza End-tower
    # Mismo comportamiento que SLOW_DOWN desde la caja Arduino: el extremo ralentizado
    # avanza a SLOW_DOWN_FACTOR × duty_cycle normal; intermedias siguen la diagonal.
    if st.session_state.lineal and st.session_state.running:
        _lin         = st.session_state.lineal
        _slow_c_kbd  = bool(_key_giro.get("left",  False))
        _slow_e_kbd  = bool(_key_giro.get("right", False))

        # Solo actualizar si hay cambio (evita escribir en cada tick sin cambio)
        if _slow_c_kbd != _lin.slow_down_cart or _slow_e_kbd != _lin.slow_down_end_tower:
            _lin.slow_down_cart      = _slow_c_kbd
            _lin.slow_down_end_tower = _slow_e_kbd
            if _slow_c_kbd:
                _msg = "Teclado < — Cart ralentizado, giro gradual hacia izquierda"
            elif _slow_e_kbd:
                _msg = "Teclado - — End-tower ralentizado, giro gradual hacia derecha"
            else:
                _msg = "Teclado liberado — velocidad normal"
            st.session_state.log.append({
                "t":    _lin._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  _msg,
            })

panel_principal()
