"""
Modelo Digital — Lineal Free Standing Span
streamlit run app.py
"""
import csv
import io
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from modelo import Lineal, Torre_Guia, Torre_Intermedia, GPS
try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

st.set_page_config(
    page_title="Lineal FSS — Modelo Digital",
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
    "vel_real":        0.0,    # velocidad media real calculada entre frames
    "pos_prev":        0.0,    # posicion_norte del frame anterior
    "tramos_ok_prev":  None,   # estado de alineacion anterior para detectar cambios
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# SIDEBAR
# El sidebar está FUERA del fragment: no parpadea nunca
with st.sidebar:
    st.markdown("## LINEAL FSS")
    st.caption("Free Standing Span — Modelo Digital")
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

    st.markdown("##### Torres Guia")
    vel_pct = st.slider(
        "Duty cycle  (% ON por ciclo de 60 s)",
        1, 100, 50, key="k_vpct", format="%d %%",
        help="Porcentaje del ciclo de 60 s en que el motor de las guias esta encendido.",
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
        "Segundos simulados por refresco",
        1, 600, 60, key="k_simspd",
        help="Cuantos segundos de simulacion avanza el modelo entre cada refresco de pantalla.",
    )
    st.caption(f"Cada refresco = **{sim_spd} s** simulados  ({sim_spd / 60:.1f} min)")

    st.divider()
    st.markdown("##### GPS")
    gps_on = st.checkbox("Activar GPS en torre intermedia", key="k_gps_on", disabled=locked)
    if gps_on:
        gps_torre = st.selectbox(
            "Torre con GPS",
            options=list(range(1, tramos)),
            key="k_gps_torre",
            disabled=locked,
            format_func=lambda i: f"Intermedia {i}",
        )
        c_lat, c_lon = st.columns(2)
        c_lat.number_input(
            "Lat. origen (°)", value=40.4168, format="%.4f",
            key="k_gps_lat", disabled=locked,
        )
        c_lon.number_input(
            "Lon. origen (°)", value=-3.7038, format="%.4f",
            key="k_gps_lon", disabled=locked,
        )
        # Lista los puertos serie disponibles en el dispositivo
        _SIN_PUERTO = "— Sin puerto (solo consola) —"
        if _SERIAL_DISPONIBLE:
            _puertos = [_SIN_PUERTO] + [p.device for p in _list_ports.comports()]
        else:
            _puertos = [_SIN_PUERTO]
        st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie</p>',
                    unsafe_allow_html=True)
        c_puerto, c_refresh = st.columns([6, 1])
        with c_puerto:
            st.selectbox("Puerto serie", options=_puertos, key="k_gps_puerto",
                         disabled=locked, label_visibility="collapsed")
        with c_refresh:
            if st.button("↺", help="Actualizar lista de puertos",
                         disabled=locked, use_container_width=True):
                st.rerun()

    st.divider()

    # Controles
    if state.lineal is None:
        if st.button("INICIAR", key="btn_iniciar", type="primary", width="stretch"):
            state.lineal = Lineal(
                numero_tramos        = tramos,
                longitud_tramo       = t_len,
                velocidad_porcentaje = vel_pct,
                velocidad_nominal    = v_nom,
            )
            state.lineal.start()
            state.log.append({"t": "00h 00m 00s", "tipo": "START", "msg": "Sistema iniciado"})
            if st.session_state.get("k_gps_on", False):
                _SIN_PUERTO = "— Sin puerto (solo consola) —"
                puerto_raw = st.session_state.get("k_gps_puerto", _SIN_PUERTO)
                puerto = None if (puerto_raw == _SIN_PUERTO) else puerto_raw
                state.lineal.asignar_gps(
                    indice_torre  = st.session_state.get("k_gps_torre", 1),
                    lat_origen    = st.session_state.get("k_gps_lat", 40.4168),
                    lon_origen    = st.session_state.get("k_gps_lon", -3.7038),
                    puerto_serial = puerto,
                )
                # Hilo de fondo: transmite 1 vez/segundo real, independiente de la UI
                if puerto:
                    state.lineal.gps.iniciar_transmision_background()
            state.longitud_campo = campo
            state.running  = True
            state.finished = False
            state.paused   = False
            st.rerun()

    elif state.running:
        if st.button("STOP / PAUSAR", key="btn_stop", width="stretch"):
            state.lineal.stop()
            if state.lineal.gps:
                state.lineal.gps.detener_transmision_background()
            state.log.append({"t": state.lineal._tiempo_formateado(), "tipo": "STOP",
                               "msg": f"Sistema pausado en {state.lineal.posicion_norte:.2f} m"})
            state.running = False
            state.paused  = True
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
            for k, v in defaults.items():
                state[k] = v
            st.rerun()

    elif state.finished:
        if st.button("REINICIAR", key="btn_reiniciar", type="primary", width="stretch"):
            if state.lineal and state.lineal.gps:
                state.lineal.gps.detener_transmision_background()
            for k, v in defaults.items():
                state[k] = v
            st.rerun()

    st.divider()
    st.markdown("##### Leyenda")
    for color, name, desc in [
        ("#f78166", "Guia Izq (Cart)",  "Motor + duty cycle · cascada izq"),
        ("#d2a8ff", "Guia Der",         "Motor + duty cycle · cascada der"),
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


# FUNCIONES DE FIGURA (módulo, no dentro del fragment)
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
        return "#d2a8ff", "square", "GD", 20
    if isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
        return "#ffa657", "star", f"I{i}★", 18
    if i <= lineal.indice_tramo_rigido:
        return "#58a6ff", "circle", f"I{i}", 14
    return "#56d364", "circle", f"I{i}", 14


def build_figure(lineal: Lineal | None, longitud_campo: float) -> go.Figure:
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
    row_step = max(2, int(fh / 40))
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
        x=(rx1 + rx2) / 2, y=fh,
        text="TRAMO RIGIDO",
        showarrow=False,
        font=dict(color="#ffa657", size=10, family="monospace"),
        bgcolor="rgba(13,17,23,0.6)",
        bordercolor="#ffa657", borderwidth=1,
        xref="x", yref="y",
        yshift=14,
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
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            annotations.append(dict(
                x=mx, y=my,
                text=f"{ang:+.2f}°",
                showarrow=False,
                font=dict(color="#ffa657", size=13, family="monospace"),
                bgcolor="rgba(13,17,23,0.75)",
                bordercolor="#ffa657", borderwidth=1,
                xref="x", yref="y",
            ))
        else:
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=14), opacity=0.12,
                hoverinfo="skip", showlegend=False))
            traces.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=4),
                hovertemplate=hover, showlegend=False))

    # Torres
    n       = len(lineal.torres)
    gps_idx = lineal.torres.index(lineal.gps.torre) if lineal.gps else -1
    for i, torre in enumerate(lineal.torres):
        color, sym, label, sz = _torre_style(lineal, i)

        if i == 0:
            nombre = "Guia Izq (Cart)"
        elif i == n - 1:
            nombre = "Guia Der"
        elif isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
            nombre = f"Intermedia {i}  [Motor Rapido — extremo der tramo rigido]"
        elif i <= lineal.indice_tramo_rigido:
            nombre = f"Intermedia {i}  [cascada izquierda]"
        else:
            nombre = f"Intermedia {i}  [cascada derecha]"

        cont_cerrado = torre.contactor.esta_cerrado
        if isinstance(torre, Torre_Guia):
            cont_txt = f"Contactor: {'ON' if cont_cerrado else 'OFF'}  (duty {torre.contactor.duty_cycle*100:.0f}%)"
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
            estado_txt   = f"DC {torre.contactor.duty_cycle*100:.0f}%  {'ON' if cont_cerrado else 'OFF'}"
            estado_color = color
        else:
            if cont_cerrado:
                estado_txt, estado_color = "Corrigiendo", "#e3b341"
            else:
                estado_txt, estado_color = "Alineada", "#3fb950"

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

        ay_off = -68 if i % 2 == 0 else 68
        annotations.append(dict(
            x=torre.posicion_x, y=torre.posicion_y,
            xref="x", yref="y",
            text=f"<b>{label}</b>  Y={torre.posicion_y:.2f} m<br>{estado_txt}",
            showarrow=True,
            arrowhead=2, arrowwidth=1.5, arrowsize=0.7,
            arrowcolor=color,
            ax=0, ay=ay_off,
            font=dict(color=estado_color, size=10, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor=estado_color, borderwidth=1, borderpad=6,
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
            ax=-80, ay=0,
            font=dict(color="#58d68d", size=9, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor="#58d68d", borderwidth=1, borderpad=5,
            align="center",
        ))

    pad_x = fw * 0.06
    pad_y = fh * 0.04
    fig = go.Figure(data=traces)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0a1f10",
        height=620,
        margin=dict(l=70, r=40, t=90, b=50),
        xaxis=dict(
            title=dict(text="Oeste  —  Este  (metros)", font=dict(color="#8b949e", size=12)),
            gridcolor="#1a2332", zeroline=False,
            range=[-pad_x, fw + pad_x],
            tickfont=dict(color="#8b949e"), ticksuffix=" m",
        ),
        yaxis=dict(
            title=dict(text="Norte  (metros)", font=dict(color="#8b949e", size=12)),
            gridcolor="#1a2332", zeroline=False,
            range=[-pad_y, fh + pad_y],
            tickfont=dict(color="#8b949e"), ticksuffix=" m",
        ),
        shapes=shapes,
        annotations=annotations,
        hovermode="closest",
        dragmode="pan",
    )
    return fig


# PANEL PRINCIPAL
# Fragment: solo esta zona se refresca (1 vez/segundo).
# El sidebar queda completamente estable — sin parpadeo.
@st.fragment(run_every=1)
def panel_principal():
    state          = st.session_state
    lineal: Lineal | None = state.lineal
    longitud_campo = state.longitud_campo

    if lineal is not None:
        lineal.set_speed(state.get("k_vpct", 50))

    # Avance de simulacion
    if state.running and not state.finished and lineal is not None:
        sim_spd_val = state.get("k_simspd", 60)
        lineal.avanza(sim_spd_val, transmitir_gps=False)
        # GPS: el hilo background (iniciado en INICIAR) transmite por su cuenta

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

        if lineal.posicion_norte >= longitud_campo:
            lineal.stop()
            if lineal.gps:
                lineal.gps.detener_transmision_background()
            state.log.append({"t": lineal._tiempo_formateado(), "tipo": "FIN",
                               "msg": f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}"})
            state.running  = False
            state.finished = True
            st.rerun()
            return

    # CABECERA
    st.markdown("# Modelo Digital — Lineal Free Standing Span")

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
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.25);"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#3fb950;"
            "display:inline-block;box-shadow:0 0 6px #3fb950'></span>"
            "<span style='color:#3fb950;font-weight:600;letter-spacing:2px;font-size:0.85rem'>EN MARCHA</span>"
            "</div>",
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
    cols_m = st.columns(8)
    if lineal:
        porcentaje  = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        vel_teorica = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        vel_real    = state.get("vel_real", 0.0)
        delta_vel   = vel_real - vel_teorica
        cols_m[0].metric("Tiempo campo",   lineal._tiempo_formateado())
        cols_m[1].metric("Ciclo",          str(lineal.ciclo_actual))
        cols_m[2].metric("Posicion media", f"{lineal.posicion_norte:.2f} m")
        cols_m[3].metric("Recorrido",      f"{porcentaje:.1f} %")
        cols_m[4].metric("Alineacion",     "OK" if lineal.esta_alineado else "Corrigiendo")
        cols_m[5].metric("Guia Izq",       "ON" if lineal.guia_izquierda.contactor.esta_cerrado else "OFF")
        cols_m[6].metric("Guia Der",       "ON" if lineal.guia_derecha.contactor.esta_cerrado else "OFF")
        cols_m[7].metric("Vel. real",      f"{vel_real:.2f} m/min",
                          delta=f"{delta_vel:+.2f} vs teórica",
                          delta_color="normal")
    else:
        for col in cols_m:
            col.metric("—", "—")

    # BARRA DE PROGRESO
    if lineal:
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
        cg[0].metric("GPS · Torre",  f"Intermedia {gps_idx}")
        cg[1].metric("Latitud",      f"{gps.latitud:.7f}°")
        cg[2].metric("Longitud",     f"{gps.longitud:.7f}°")
        cg[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")

    # MINI-TABLA GPS TRACK (últimas 10 lecturas)
    if state.gps_track:
        with st.expander(f"Track GPS — últimas {min(len(state.gps_track), 10)} lecturas", expanded=False):
            st.dataframe(
                state.gps_track[-10:][::-1],
                hide_index=True,
                width="stretch",
            )

    # FIGURA
    st.plotly_chart(
        build_figure(lineal, longitud_campo),
        width="stretch",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
            "toImageButtonOptions": {"filename": "lineal_fss", "format": "png"},
        },
    )

    # PANEL DETALLADO DE TORRES Y TRAMOS
    if lineal:
        st.divider()
        col_t, col_tr = st.columns([1, 2])

        with col_t:
            st.markdown("##### Torres")
            n       = len(lineal.torres)
            gps_idx = lineal.torres.index(lineal.gps.torre) if lineal.gps else -1
            for i, torre in enumerate(lineal.torres):
                if i == 0:
                    color, name = "#f78166", "Guia Izq (Cart)"
                elif i == n - 1:
                    color, name = "#d2a8ff", "Guia Der"
                elif isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
                    color, name = "#ffa657", f"I{i} [Motor rapido]"
                elif i <= lineal.indice_tramo_rigido:
                    color, name = "#58a6ff", f"I{i} [cascada izq]"
                else:
                    color, name = "#56d364", f"I{i} [cascada der]"

                cont = "ON " if torre.contactor.esta_cerrado else ("OFF" if isinstance(torre, Torre_Guia) else "—  ")

                gps_badge = (
                    "<span style='background:#1a3d2b;border:1px solid #58d68d;"
                    "border-radius:4px;padding:1px 6px;font-size:0.65rem;"
                    "color:#58d68d;margin-left:6px;font-family:monospace'>GPS</span>"
                    if i == gps_idx else ""
                )
                st.markdown(
                    f"<span style='display:inline-block;width:8px;height:8px;"
                    f"border-radius:50%;background:{color};margin-right:6px;vertical-align:middle'></span>"
                    f"<b>{name}</b>{gps_badge}&nbsp;"
                    f"<code>y={torre.posicion_y:.3f} m &nbsp; {cont}</code>",
                    unsafe_allow_html=True,
                )

        with col_tr:
            st.markdown("##### Tramos")
            cols_tr = st.columns(len(lineal.tramos))
            for col, (i, tramo) in zip(cols_tr, enumerate(lineal.tramos, 1)):
                ang = tramo.angulo_grados
                if not tramo.esta_alineado:
                    estado, e_color, b_color = "CRIT", "#f85149", "#f85149"
                elif abs(ang) < 0.5:
                    estado, e_color, b_color = "OK",   "#3fb950", "#30363d"
                elif abs(ang) < 1.5:
                    estado, e_color, b_color = "WARN", "#e3b341", "#e3b341"
                else:
                    estado, e_color, b_color = "CRIT", "#f85149", "#f85149"

                fss_badge = (
                    "<span style='color:#ffa657;font-size:0.6rem;letter-spacing:1px'> FSS</span>"
                    if tramo.es_rigido else ""
                )
                col.markdown(
                    f"<div style='background:#161b22;border:1px solid {b_color};"
                    f"border-radius:8px;padding:10px 6px;text-align:center;margin:2px 0'>"
                    f"<div style='color:#8b949e;font-size:0.65rem;letter-spacing:1px;margin-bottom:4px'>"
                    f"TRAMO {i}{fss_badge}</div>"
                    f"<div style='color:{e_color};font-size:1.1rem;font-weight:700;"
                    f"font-family:monospace;line-height:1.2'>{ang:+.3f}°</div>"
                    f"<div style='color:#8b949e;font-size:0.7rem;font-family:monospace;margin-top:3px'>"
                    f"desv {tramo.desviacion_norte:+.3f} m</div>"
                    f"<div style='color:{e_color};font-size:0.6rem;letter-spacing:2px;margin-top:5px;"
                    f"font-weight:600'>{estado}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # LOG DE EVENTOS + EXPORTAR CSV
        st.divider()
        col_log, col_csv = st.columns([3, 1])

        with col_log:
            _TIPO_COLOR = {
                "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
                "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
            }
            entradas = state.log[-60:][::-1]   # últimas 60, más reciente arriba
            with st.expander(f"Log de eventos  ({len(state.log)} entradas)", expanded=False):
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

        with col_csv:
            if state.historial:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=list(state.historial[0].keys()))
                writer.writeheader()
                writer.writerows(state.historial)
                st.download_button(
                    label="Descargar CSV",
                    data=buf.getvalue(),
                    file_name="simulacion_lineal.csv",
                    mime="text/csv",
                    width="stretch",
                )


panel_principal()
