import math, os
from datetime import datetime
import streamlit as st
from V2.modelos import Lineal
from V2.logica.constantes import TERRENOS, get_defaults
from V2.logica.estado import get_sim, SIM_KEYS
from V2.logica.trayectoria import get_origen_latlon, parse_trayectoria

_DIR_EXPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")

try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

SIN_PUERTO = "— Sin puerto (solo consola) —"
SIN_CAJA_PUERTO = "— Selecciona puerto —"


def _renderizar_sidebar_observador(sim):
    st.markdown(
        "<div style='display:inline-flex;align-items:center;gap:8px;"
        "background:rgba(88,166,255,0.08);border:1px solid rgba(88,166,255,0.25);"
        "border-radius:20px;padding:5px 14px;margin:4px 0 12px 0'>"
        "<span style='width:8px;height:8px;border-radius:50%;background:#58a6ff;"
        "display:inline-block'></span>"
        "<span style='color:#58a6ff;font-weight:600;letter-spacing:1px;"
        "font-size:0.85rem'>OBSERVADOR — solo lectura</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if sim.lineal is None:
        st.info("Esperando que el operador inicie la simulación…")
        return

    lineal = sim.lineal
    st.markdown("##### Configuración activa")
    c1, c2 = st.columns(2)
    c1.metric("N° tramos", lineal.numero_tramos)
    c2.metric("Long. tramo", f"{lineal.longitud_tramo} m")
    c1.metric("Vel. nominal", f"{lineal.velocidad_nominal} m/min")
    c2.metric("Campo total",  f"{sim.longitud_campo} m")

    velocidad_media = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
    st.markdown(
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
        f"padding:8px 12px;margin:2px 0 10px 0;display:flex;justify-content:space-between'>"
        f"<span><span style='color:#8b949e;font-size:0.7rem'>Panel speed </span>"
        f"<b style='color:#e6edf3;font-family:monospace'>{lineal.velocidad_porcentaje} %</b></span>"
        f"<span><span style='color:#8b949e;font-size:0.7rem'>MEDIA </span>"
        f"<b style='color:#3fb950;font-family:monospace'>{velocidad_media:.2f} m/min</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("##### Conexión")
    if lineal.caja_interfaz:
        st.markdown("<span style='color:#e6edf3;font-size:0.85rem'>Caja de interfaz Arduino (115 200 baud)</span>",
                    unsafe_allow_html=True)
    elif lineal.gps:
        st.markdown("<span style='color:#e6edf3;font-size:0.85rem'>GPS directo (9 600 baud)</span>",
                    unsafe_allow_html=True)
    else:
        st.markdown("<span style='color:#8b949e;font-size:0.85rem'>Sin conexión externa</span>",
                    unsafe_allow_html=True)

    if sim.sim_auto_reverse:
        st.divider()
        st.markdown("##### Auto-reverse")
        st.markdown(
            f"<span style='color:#e6edf3;font-size:0.85rem'>"
            f"Activo · {sim.sim_ar_ymin:.0f} m — {sim.sim_ar_ymax:.0f} m · "
            f"<b>{sim.ar_pasadas}</b> inversiones</span>",
            unsafe_allow_html=True,
        )

    if sim.trayectoria_activa and sim.trayectoria_puntos_xy:
        st.divider()
        st.markdown("##### Trayectoria objetivo GPS")
        numero_puntos = len(sim.trayectoria_puntos_xy)
        st.markdown(
            f"<span style='color:#e6edf3;font-size:0.85rem'>"
            f"Activa · {numero_puntos} puntos · {numero_puntos - 1} segmentos</span>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("##### Teclado")
    st.caption("Control exclusivo del operador")
    for tecla, desc in [
        ("< (mantener)", "Ralentiza Cart"),
        ("- (mantener)", "Ralentiza End-tower"),
        ("R (pulsar)",   "Marcha atrás / avance normal"),
    ]:
        st.markdown(
            f"<code style='background:#161b22;border:1px solid #30363d;border-radius:4px;"
            f"padding:1px 6px;font-size:0.78rem;color:#484f58'>{tecla}</code>"
            f"<span style='color:#484f58;font-size:0.78rem;margin-left:6px'>{desc}</span>",
            unsafe_allow_html=True,
        )
    st.divider()


def _iniciar_simulacion(
    numero_tramos: int,
    longitud_tramo: float,
    velocidad_porcentaje: int,
    velocidad_nominal: float,
    longitud_campo: float,
) -> None:
    sim = get_sim()
    state = st.session_state
    nivel_patinaje = TERRENOS.get(state.get("k_terreno", "Normal"), 0.012)

    sim.lineal = Lineal(
        numero_tramos=numero_tramos,
        longitud_tramo=longitud_tramo,
        velocidad_porcentaje=velocidad_porcentaje,
        velocidad_nominal=velocidad_nominal,
        ruido_lateral=nivel_patinaje,
    )
    sim.lineal.start()
    sim.log.append({"t": "00h 00m 00s", "tipo": "START", "msg": "Sistema iniciado"})

    modo = state.get("k_conexion_modo", "ninguno")
    if modo == "gps":
        puerto_raw = state.get("k_gps_puerto", SIN_PUERTO)
        puerto = None if puerto_raw == SIN_PUERTO else puerto_raw
        sim.lineal.asignar_gps(
            indice_seccion  = state.get("k_gps_torre", 1),
            lat_origen      = state.get("k_gps_lat_e7", 404168000) / 1e7,
            lon_origen      = state.get("k_gps_lon_e7", -37038000) / 1e7,
            puerto_serial   = puerto,
            verbose_consola = (puerto is None),
        )
        sim.lineal.gps.iniciar_transmision_background()

    if modo == "caja":
        puerto_caja = state.get("k_caja_puerto", "")
        if puerto_caja and puerto_caja != SIN_CAJA_PUERTO:
            sim.lineal.asignar_caja(
                indice_seccion = state.get("k_caja_torre", 1),
                lat_origen     = state.get("k_caja_lat_e7", 404168000) / 1e7,
                lon_origen     = state.get("k_caja_lon_e7", -37038000) / 1e7,
                puerto_serial  = puerto_caja,
                carr           = state.get("k_caja_carr", 2),
            )
            sim.lineal.caja_interfaz.iniciar()

    sim.longitud_campo      = longitud_campo
    sim.running             = True
    sim.finished            = False
    sim.paused              = False
    sim.caja_slow_prev      = {"cart": False, "end": False, "safety": True, "gps": True}
    sim.tower_trails        = [[] for _ in range(len(sim.lineal.secciones))]

    os.makedirs(_DIR_EXPORTS, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sim.csv_ruta           = os.path.join(_DIR_EXPORTS, f"simulacion_{ts}.csv")
    sim.csv_filas_escritas = 0

    st.session_state["_is_operator"] = True


def _limpiar_y_resetear() -> None:
    sim = get_sim()
    if sim.lineal and sim.lineal.gps:
        sim.lineal.gps.detener_transmision_background()
    if sim.lineal and sim.lineal.caja_interfaz:
        sim.lineal.caja_interfaz.detener()
    fresh = get_defaults()
    for clave in SIM_KEYS:
        sim[clave] = fresh[clave]
    st.session_state["marcha_atras_kbd"] = False
    st.session_state["_is_operator"]     = False


def renderizar_sidebar():
    with st.sidebar:
        st.markdown("## LINEAL")
        st.caption("Configura tu Gemelo Digital")
        st.divider()

        sim   = get_sim()
        state = st.session_state
        bloqueado = sim.lineal is not None

        if not state.get("_is_operator", False) and bloqueado:
            _renderizar_sidebar_observador(sim)
            return

        st.markdown("##### Geometría del Lineal")
        if bloqueado:
            st.markdown(
                "<span style='color:#484f58;font-size:0.72rem'>"
                "Simulación activa — parámetros bloqueados</span>",
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)
        numero_tramos  = c1.number_input("N° de tramos",    3, 20,   5,  1,   disabled=bloqueado, key="k_tramos")
        longitud_tramo = c2.number_input("Long. tramo (m)", 5, 500, 50,  5,   disabled=bloqueado, key="k_tlen")
        c3, c4 = st.columns(2)
        velocidad_nominal = c3.number_input("Vel. nominal (m/min)", 0.5, 10.0, 3.0, 0.5, disabled=bloqueado, key="k_vnom")
        longitud_campo    = c4.number_input("Campo total (m)",      100, 5000, 800,  50,  disabled=bloqueado, key="k_campo")

        st.markdown("##### Panel speed")
        velocidad_porcentaje = st.slider("Panel speed  (Duty cycle %)", 1, 100, 50,
                                         key="k_vpct", format="%d %%",
                                         help="Porcentaje de la velocidad máxima a la que avanza el lineal.")
        velocidad_media = velocidad_porcentaje / 100 * velocidad_nominal
        st.markdown(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
            f"padding:8px 12px;margin:2px 0 10px 0;display:flex;justify-content:space-between'>"
            f"<span><span style='color:#8b949e;font-size:0.7rem'>ON </span>"
            f"<b style='color:#e6edf3;font-family:monospace'>{velocidad_porcentaje * 60 / 100:.0f} s</b>"
            f"<span style='color:#8b949e;font-size:0.7rem'> / 60 s</span></span>"
            f"<span><span style='color:#8b949e;font-size:0.7rem'>MEDIA </span>"
            f"<b style='color:#3fb950;font-family:monospace'>{velocidad_media:.2f} m/min</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("##### Simulación")
        segundos_por_refresco = st.slider(
            "Factor de escala temporal x veces real",
            1, 600, 60, key="k_simspd", format="x%d",
            help="Cuántos segundos de simulación avanza el modelo entre cada refresco.",
        )
        st.caption(f"Cada refresco = **{segundos_por_refresco} s** avanza")

        st.divider()
        st.markdown("##### Grados de patinaje por terreno")
        terreno = st.selectbox(
            "Elige el tipo de patinaje",
            options=list(TERRENOS.keys()), index=2,
            key="k_terreno", disabled=bloqueado,
            help="Modela la deriva lateral natural de las secciones guía según el terreno.",
        )
        nivel_patinaje = TERRENOS[terreno]
        if nivel_patinaje > 0.0:
            deriva_estimada_cm = (
                nivel_patinaje
                * (3.0 / 60.0)
                * (state.get("k_vpct", 50) / 100.0)
                * (state.get("k_campo", 800) ** 0.5)
                * 60.0
            )
            st.caption(f"Deriva acumulada estimada al final del campo: **±{deriva_estimada_cm:.0f} cm**")

        st.divider()
        st.markdown("##### Auto-reverse")
        auto_reverse_activo = st.toggle(
            "Activar auto-reverse", key="k_auto_reverse",
            help="El lineal rebota automáticamente entre los límites Y configurados.",
        )
        if auto_reverse_activo:
            limite_norte_defecto = int(state.get("k_campo", 800))
            c_ar1, c_ar2 = st.columns(2)
            c_ar1.number_input("Y mín (m)", min_value=0, max_value=limite_norte_defecto,
                               value=state.get("k_ar_ymin", 0), step=5, key="k_ar_ymin")
            c_ar2.number_input("Y máx (m)", min_value=0, max_value=int(longitud_campo),
                               value=state.get("k_ar_ymax", limite_norte_defecto), step=5, key="k_ar_ymax")
            st.caption(
                f"Rebota entre **{state.get('k_ar_ymin', 0)} m** y **{state.get('k_ar_ymax', limite_norte_defecto)} m**"
                + (f"  ·  **{sim.ar_pasadas}** inversiones" if sim.running else "")
            )

        st.divider()
        st.markdown("##### Conexión externa")
        st.radio(
            "Modo de conexión",
            options=["ninguno", "gps", "caja"],
            format_func=lambda k: {
                "ninguno": "Sin conexión",
                "gps":     "GPS directo  (cable cruzado, 9 600 baud)",
                "caja":    "Caja de interfaz Arduino  (115 200 baud)",
            }[k],
            key="k_conexion_modo", disabled=bloqueado,
            label_visibility="collapsed",
        )
        modo_conexion = state.get("k_conexion_modo", "ninguno")
        es_modo_gps   = (modo_conexion == "gps")
        es_modo_caja  = (modo_conexion == "caja")

        puertos = [p.device for p in _list_ports.comports()] if _SERIAL_DISPONIBLE else []

        if es_modo_gps:
            st.selectbox("TramoIntermedio con el GPS",
                         options=list(range(1, numero_tramos)),
                         key="k_gps_torre", disabled=bloqueado,
                         format_func=lambda i: f"TramoIntermedio {i}")
            c_lat, c_lon = st.columns(2)
            c_lat.number_input("Lat. origen (×10⁷)", value=404168000, step=1, key="k_gps_lat_e7", disabled=bloqueado)
            c_lon.number_input("Lon. origen (×10⁷)", value=-37038000, step=1, key="k_gps_lon_e7", disabled=bloqueado)
            st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie</p>', unsafe_allow_html=True)
            c_p, c_r = st.columns([6, 1])
            with c_p:
                st.selectbox("Puerto", options=[SIN_PUERTO] + puertos,
                             key="k_gps_puerto", disabled=bloqueado, label_visibility="collapsed")
            with c_r:
                if st.button("↺", help="Actualizar puertos", disabled=bloqueado, width="stretch"):
                    st.rerun()

        if es_modo_caja:
            st.session_state["k_caja_carr"] = 2
            c_lc, c_loc = st.columns(2)
            c_lc.number_input("Lat. origen (×10⁷)", value=404168000, step=1, key="k_caja_lat_e7", disabled=bloqueado)
            c_loc.number_input("Lon. origen (×10⁷)", value=-37038000, step=1, key="k_caja_lon_e7", disabled=bloqueado)

            lat_origen_e7          = state.get("k_caja_lat_e7", 404168000)
            lon_origen_e7          = state.get("k_caja_lon_e7", -37038000)
            longitud_tramo_config  = state.get("k_tlen", 50)
            metros_por_grado_lon   = 111320.0 * math.cos(math.radians(lat_origen_e7 / 1e7))

            def _etiqueta_seccion_caja(i):
                lon_i = round((lon_origen_e7 / 1e7 + longitud_tramo_config * i / metros_por_grado_lon) * 1e7)
                return f"TramoIntermedio {i}  ({lat_origen_e7} / {lon_i})"

            st.selectbox("TramoIntermedio GPS",
                         options=list(range(1, numero_tramos)),
                         key="k_caja_torre", disabled=bloqueado,
                         format_func=_etiqueta_seccion_caja,
                         help="Sección cuya posición se envía al Arduino como coordenada GPS.")
            st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie Arduino</p>',
                        unsafe_allow_html=True)
            c_pc, c_rc = st.columns([6, 1])
            with c_pc:
                st.selectbox("Puerto caja",
                             options=puertos if puertos else [SIN_CAJA_PUERTO],
                             key="k_caja_puerto", disabled=bloqueado, label_visibility="collapsed")
            with c_rc:
                if st.button("↺", help="Actualizar puertos", disabled=bloqueado,
                             width="stretch", key="btn_ref_caja"):
                    st.rerun()
            st.caption("Arduino conectado a este PC · cable USB normal · Carr=2 (RTK FIX) fijo")

        if es_modo_gps or es_modo_caja:
            st.divider()
            st.markdown("##### Interferencia GPS simulada")
            interferencia = st.slider(
                "Desvío aleatorio por emisión (mm)",
                min_value=0, max_value=15, value=0, step=1,
                key="k_interferencia_gps_mm",
                help="±X mm de error aleatorio añadido a cada coordenada enviada al Arduino.",
            )
            if interferencia > 0:
                st.caption(f"Enviando coordenada con ±{interferencia} mm de ruido aleatorio")
            else:
                st.caption("Sin interferencia — coordenada perfecta")

        st.divider()
        st.markdown("##### Trayectoria objetivo GPS")
        st.toggle("Activar trayectoria", key="k_tray_activa",
                  help="Define puntos de guiado para la sección GPS. Se calcula EΔd y EΔrumbo.")

        if state.get("k_tray_activa", False):
            if "k_tray_puntos" not in state:
                state.k_tray_puntos = []
            if "k_tray_punto_contador" not in state:
                state.k_tray_punto_contador = 0

            modo_conexion_actual = state.get("k_conexion_modo", "ninguno")
            lat_origen_defecto = (
                state.get("k_caja_lat_e7", 404168000) if modo_conexion_actual == "caja" else
                state.get("k_gps_lat_e7",  404168000) if modo_conexion_actual == "gps"  else
                404168000
            )
            lon_origen_defecto = (
                state.get("k_caja_lon_e7", -37038000) if modo_conexion_actual == "caja" else
                state.get("k_gps_lon_e7",  -37038000) if modo_conexion_actual == "gps"  else
                -37038000
            )

            puntos_trayectoria = state.k_tray_puntos
            if puntos_trayectoria:
                col_cabecera_lat, col_cabecera_lon, _ = st.columns([44, 44, 12])
                col_cabecera_lat.caption("Lat ×10⁷")
                col_cabecera_lon.caption("Lon ×10⁷")

            id_punto_a_eliminar = None
            for punto in puntos_trayectoria:
                id_punto = punto["id"]
                col_lat, col_lon, col_eliminar = st.columns([44, 44, 12])
                with col_lat:
                    st.number_input(f"Lat {id_punto}", value=punto["lat"], step=1,
                                    key=f"k_tray_lat_{id_punto}", label_visibility="collapsed")
                with col_lon:
                    st.number_input(f"Lon {id_punto}", value=punto["lon"], step=1,
                                    key=f"k_tray_lon_{id_punto}", label_visibility="collapsed")
                with col_eliminar:
                    if st.button("✕", key=f"k_tray_del_{id_punto}", help="Eliminar punto"):
                        id_punto_a_eliminar = id_punto

            if id_punto_a_eliminar is not None:
                state.k_tray_puntos = [p for p in state.k_tray_puntos if p["id"] != id_punto_a_eliminar]
                st.rerun()

            if st.button("＋ Añadir punto", key="btn_tray_add"):
                nuevo_id = state.k_tray_punto_contador
                state.k_tray_punto_contador += 1
                state.k_tray_puntos.append({"id": nuevo_id, "lat": lat_origen_defecto, "lon": lon_origen_defecto})
                st.rerun()

            lineas_trayectoria = []
            for punto in puntos_trayectoria:
                id_punto = punto["id"]
                lat_punto = state.get(f"k_tray_lat_{id_punto}", punto["lat"])
                lon_punto = state.get(f"k_tray_lon_{id_punto}", punto["lon"])
                lineas_trayectoria.append(f"{lat_punto} {lon_punto}")
            state["k_tray_input"] = "\n".join(lineas_trayectoria)

            lat_sb, lon_sb = get_origen_latlon()
            pts_sb = parse_trayectoria(state.get("k_tray_input", ""), lat_sb, lon_sb)
            if len(pts_sb) >= 2:
                st.caption(f"{len(pts_sb)} puntos válidos  ·  {len(pts_sb) - 1} segmentos")
            elif len(pts_sb) == 1:
                st.caption("Mínimo 2 puntos para definir un segmento")
            else:
                st.caption("Sin puntos — pulsa ＋ para añadir")

        if state.get("_is_operator", False):
            if state.get("k_tray_activa", False):
                lat_p, lon_p = get_origen_latlon()
                pts = parse_trayectoria(state.get("k_tray_input", ""), lat_p, lon_p)
                if len(pts) >= 2:
                    sim.trayectoria_activa    = True
                    sim.trayectoria_puntos_xy = pts
                else:
                    sim.trayectoria_activa    = False
                    sim.trayectoria_puntos_xy = None
            else:
                sim.trayectoria_activa    = False
                sim.trayectoria_puntos_xy = None

        st.divider()

        if sim.lineal is None:
            if st.button("INICIAR", key="btn_iniciar", type="primary", width="stretch"):
                _iniciar_simulacion(numero_tramos, longitud_tramo, velocidad_porcentaje, velocidad_nominal, longitud_campo)
                st.rerun()

        elif sim.running:
            if st.button("STOP", key="btn_stop", width="stretch"):
                sim.lineal.stop()
                if sim.lineal.gps:
                    sim.lineal.gps.detener_transmision_background()
                if sim.lineal.caja_interfaz:
                    sim.lineal.caja_interfaz.detener()
                sim.log.append({"t": sim.lineal._tiempo_formateado(), "tipo": "STOP",
                                 "msg": f"Sistema pausado en {sim.lineal.posicion_norte:.2f} m"})
                sim.running = False; sim.paused = True; sim.motivo_pausa = "manual"
                st.rerun()

        elif sim.paused and not sim.finished:
            caja = sim.lineal.caja_interfaz
            safety_fail     = caja is not None and not caja.safety_ok
            gps_fail        = caja is not None and not caja.gps_ok
            continuar_bloqueado = safety_fail or gps_fail
            bc1, bc2 = st.columns(2)
            if bc1.button("CONTINUAR", key="btn_start", type="primary", width="stretch", disabled=continuar_bloqueado):
                sim.lineal.start()
                if sim.lineal.gps:
                    sim.lineal.gps.iniciar_transmision_background()
                if sim.lineal.caja_interfaz:
                    sim.lineal.caja_interfaz.iniciar()
                sim.log.append({"t": sim.lineal._tiempo_formateado(), "tipo": "START",
                                 "msg": f"Sistema reanudado desde {sim.lineal.posicion_norte:.2f} m"})
                sim.running = True; sim.paused = False; sim.motivo_pausa = None
                st.rerun()
            if bc2.button("RESET", key="btn_reset", width="stretch"):
                _limpiar_y_resetear(); st.rerun()

            if safety_fail:
                st.error("SAFETY FAIL activo — resuelve el problema antes de continuar")
            elif gps_fail:
                st.warning("GPS FAIL activo — esperando que se restaure la señal GPS")

        elif sim.finished:
            if st.button("REINICIAR", key="btn_reiniciar", type="primary", width="stretch"):
                _limpiar_y_resetear(); st.rerun()

        st.divider()
        st.markdown("##### Teclado (simulación activa)")
        for tecla, desc in [
            ("< (mantener)", "Ralentiza Cart — sigue motor rápido, giro gradual izquierda"),
            ("- (mantener)", "Ralentiza End-tower — sigue motor rápido, giro gradual derecha"),
            ("R (pulsar)",   "Marcha atrás / avance normal"),
        ]:
            st.markdown(
                f"<code style='background:#161b22;border:1px solid #30363d;border-radius:4px;"
                f"padding:1px 6px;font-size:0.78rem;color:#e6edf3'>{tecla}</code>"
                f"<span style='color:#8b949e;font-size:0.78rem;margin-left:6px'>{desc}</span>",
                unsafe_allow_html=True,
            )
        st.divider()
