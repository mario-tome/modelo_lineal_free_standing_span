import math, os
from datetime import datetime
import streamlit as st
from V2.modelos import Lineal
from V2.logica.constantes import TERRENOS, get_defaults
from V2.logica.estado import get_sim, SimState, CLAVES_SIMULACION
from V2.logica.trayectoria import get_origen_latlon, parse_trayectoria

_DIR_EXPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")

try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

SIN_CAJA_PUERTO = "— Selecciona puerto —"


# SIDEBAR PARA EL MODO OBSERVADOR (solo lectura)

def _renderizar_sidebar_observador(sim: SimState) -> None:
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
    col_iz, col_de = st.columns(2)
    col_iz.metric("N° tramos", lineal.numero_tramos)
    col_de.metric("Long. tramo", f"{lineal.longitud_tramo} m")
    col_iz.metric("Vel. nominal", f"{lineal.velocidad_nominal} m/min")
    col_de.metric("Campo total", f"{sim.longitud_campo} m")

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
        st.markdown("<span style='color:#e6edf3;font-size:0.85rem'>Caja de interfaz GPS — 2 Arduinos I2C (115 200 baud)</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span style='color:#8b949e;font-size:0.85rem'>Sin conexión externa</span>", unsafe_allow_html=True)

    if sim.auto_reverse_activo:
        st.divider()
        st.markdown("##### Auto-reverse")
        st.markdown(
            f"<span style='color:#e6edf3;font-size:0.85rem'>"
            f"Activo · {sim.limite_sur:.0f} m — {sim.limite_norte:.0f} m · "
            f"<b>{sim.numero_inversiones}</b> inversiones</span>",
            unsafe_allow_html=True,
        )

    if sim.trayectoria_activa and sim.trayectoria_puntos:
        st.divider()
        st.markdown("##### Trayectoria objetivo GPS")
        numero_puntos = len(sim.trayectoria_puntos)
        st.markdown(
            f"<span style='color:#e6edf3;font-size:0.85rem'>"
            f"Activa · {numero_puntos} puntos · {numero_puntos - 1} segmentos</span>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("##### Teclado")
    st.caption("Control exclusivo del operador")
    _renderizar_referencia_teclado(activo=False)
    st.divider()


# ACCIONES DE CONTROL: iniciar, reiniciar, configurar GPS y caja Arduino, gestionar trayectoria GPS

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
    sim.registro.append({"t": "00h 00m 00s", "tipo": "START", "msg": "Sistema iniciado"})

    if state.get("k_conexion_modo") == "caja":
        puerto_path    = state.get("k_caja_puerto_path", "")
        puerto_heading = state.get("k_caja_puerto_heading", "")
        if puerto_path and puerto_path != SIN_CAJA_PUERTO:
            sim.lineal.asignar_caja(
                indice_tramo   = state.get("k_caja_tramo", 0),
                metros_path    = float(state.get("k_caja_metros_path", longitud_tramo * 0.25)),
                metros_heading = float(state.get("k_caja_metros_heading", longitud_tramo * 0.75)),
                lat_origen     = state.get("k_caja_lat_e7", 404168000) / 1e7,
                lon_origen     = state.get("k_caja_lon_e7", -37038000) / 1e7,
                puerto_path    = puerto_path,
                puerto_heading = puerto_heading if puerto_heading and puerto_heading != SIN_CAJA_PUERTO else puerto_path,
            )
            sim.lineal.caja_interfaz.iniciar()

    sim.longitud_campo = longitud_campo
    sim.en_marcha = True
    sim.completado = False
    sim.pausado = False
    sim.estado_previo_caja = {"cart": False, "end": False, "safety": True, "gps": True}
    sim.rastros_secciones = [[] for _ in range(len(sim.lineal.secciones))]

    os.makedirs(_DIR_EXPORTS, exist_ok=True)
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    sim.csv_ruta = os.path.join(_DIR_EXPORTS, f"simulacion_{marca_tiempo}.csv")
    sim.csv_filas_escritas = 0

    state["es_operador"] = True


def _limpiar_y_resetear() -> None:
    sim = get_sim()
    if sim.lineal and sim.lineal.caja_interfaz:
        sim.lineal.caja_interfaz.detener()
    valores_iniciales = get_defaults()
    for clave in CLAVES_SIMULACION:
        sim[clave] = valores_iniciales[clave]
    st.session_state["tecla_reversa_activa"] = False
    st.session_state["es_operador"]          = False


# BLOQUES DE CONFIGURACIÓN DE CONEXIÓN GPS, CAJA ARDUINO Y TRAYECTORIA GPS OBJETIVO

def _renderizar_referencia_teclado(activo: bool = True) -> None:
    for tecla, desc in [
        ("< (mantener)", "Ralentiza Cart"),
        ("- (mantener)", "Ralentiza End-tower"),
        ("R (pulsar)", "Marcha atrás / avance normal"),
    ]:
        color_tecla = "#e6edf3" if activo else "#484f58"
        st.markdown(
            f"<code style='background:#161b22;border:1px solid #30363d;border-radius:4px;"
            f"padding:1px 6px;font-size:0.78rem;color:{color_tecla}'>{tecla}</code>"
            f"<span style='color:#8b949e;font-size:0.78rem;margin-left:6px'>{desc}</span>",
            unsafe_allow_html=True,
        )


def _renderizar_seccion_conexion_caja(numero_tramos: int, longitud_tramo: float,
                                       bloqueado: bool, puertos: list) -> None:
    state = st.session_state
    state["k_caja_carr"] = 2  # Carr=2 significa RTK FIX (la caja Arduino solo acepta este modo de posicionamiento)

    col_lat, col_lon = st.columns(2)
    col_lat.number_input("Lat. origen (×10⁷)", value=404168000, step=1, key="k_caja_lat_e7", disabled=bloqueado)
    col_lon.number_input("Lon. origen (×10⁷)", value=-37038000, step=1, key="k_caja_lon_e7", disabled=bloqueado)

    st.selectbox(
        "Tramo con los GPS",
        options=list(range(numero_tramos)),
        key="k_caja_tramo", disabled=bloqueado,
        format_func=lambda i: f"Tramo {i + 1}  (secciones {i} → {i + 1})",
    )

    col_pm, col_hm = st.columns(2)
    col_pm.number_input(
        "GPS Path — metros desde inicio tramo",
        min_value=0.0, max_value=float(longitud_tramo),
        value=round(longitud_tramo * 0.25, 1), step=0.5,
        key="k_caja_metros_path", disabled=bloqueado,
        help="Distancia desde el inicio del tramo donde se monta la antena Path (guiado).",
    )
    col_hm.number_input(
        "GPS Heading — metros desde inicio tramo",
        min_value=0.0, max_value=float(longitud_tramo),
        value=round(longitud_tramo * 0.75, 1), step=0.5,
        key="k_caja_metros_heading", disabled=bloqueado,
        help="Distancia desde el inicio del tramo donde se monta la antena Heading (referencia).",
    )

    st.markdown('<p style="font-size:0.875rem;margin:4px 0 4px 0">Puerto Arduino Path (slow_down)</p>', unsafe_allow_html=True)
    col_pp, col_r1 = st.columns([6, 1])
    with col_pp:
        st.selectbox("Puerto path", options=puertos if puertos else [SIN_CAJA_PUERTO],
                     key="k_caja_puerto_path", disabled=bloqueado, label_visibility="collapsed")
    with col_r1:
        if st.button("↺", help="Actualizar puertos", disabled=bloqueado, width="stretch", key="btn_ref_path"):
            st.rerun()

    st.markdown('<p style="font-size:0.875rem;margin:4px 0 4px 0">Puerto Arduino Heading (referencia)</p>', unsafe_allow_html=True)
    col_ph, col_r2 = st.columns([6, 1])
    with col_ph:
        st.selectbox("Puerto heading", options=puertos if puertos else [SIN_CAJA_PUERTO],
                     key="k_caja_puerto_heading", disabled=bloqueado, label_visibility="collapsed")
    with col_r2:
        if st.button("↺", help="Actualizar puertos", disabled=bloqueado, width="stretch", key="btn_ref_heading"):
            st.rerun()

    st.caption("2 Arduinos comunicados por I2C · Carr=2 (RTK FIX) · 115 200 baud")


def _renderizar_seccion_trayectoria(bloqueado: bool) -> None:
    state = st.session_state

    if not state.get("k_tray_activa", False):
        return

    if "k_tray_puntos" not in state:
        state.k_tray_puntos = []
    if "k_tray_punto_contador" not in state:
        state.k_tray_punto_contador = 0

    lat_defecto = state.get("k_caja_lat_e7", 404168000)
    lon_defecto = state.get("k_caja_lon_e7", -37038000)

    puntos = state.k_tray_puntos
    if puntos:
        col_cab_lat, col_cab_lon, _ = st.columns([44, 44, 12])
        col_cab_lat.caption("Lat ×10⁷")
        col_cab_lon.caption("Lon ×10⁷")

    id_a_eliminar = None
    for punto in puntos:
        pid = punto["id"]
        col_lat, col_lon, col_eliminar = st.columns([44, 44, 12])
        with col_lat:
            st.number_input(f"Lat {pid}", value=punto["lat"], step=1, key=f"k_tray_lat_{pid}", label_visibility="collapsed")
        with col_lon:
            st.number_input(f"Lon {pid}", value=punto["lon"], step=1, key=f"k_tray_lon_{pid}", label_visibility="collapsed")
        with col_eliminar:
            if st.button("✕", key=f"k_tray_del_{pid}", help="Eliminar punto"):
                id_a_eliminar = pid

    if id_a_eliminar is not None:
        state.k_tray_puntos = [p for p in state.k_tray_puntos if p["id"] != id_a_eliminar]
        st.rerun()

    if st.button("＋ Añadir punto", key="btn_tray_add"):
        nuevo_id = state.k_tray_punto_contador
        state.k_tray_punto_contador += 1
        state.k_tray_puntos.append({"id": nuevo_id, "lat": lat_defecto, "lon": lon_defecto})
        st.rerun()

    # Construye el texto de trayectoria y lo almacena para que el panel lo lea
    lineas = [
        f"{state.get('k_tray_lat_' + str(p['id']), p['lat'])} {state.get('k_tray_lon_' + str(p['id']), p['lon'])}"
        for p in puntos
    ]
    state["k_tray_input"] = "\n".join(lineas)

    lat_sb, lon_sb = get_origen_latlon()
    pts_sb = parse_trayectoria(state.get("k_tray_input", ""), lat_sb, lon_sb)
    if len(pts_sb) >= 2:
        st.caption(f"{len(pts_sb)} puntos válidos  ·  {len(pts_sb) - 1} segmentos")
    elif len(pts_sb) == 1:
        st.caption("Mínimo 2 puntos para definir un segmento")
    else:
        st.caption("Sin puntos — pulsa ＋ para añadir")



# FUNCION PRINCIPAL PARA RENDERIZAR EL SIDEBAR COMPLETO

def renderizar_sidebar():
    with st.sidebar:
        st.markdown("## Gemelo Digital")

        sim = get_sim()
        state = st.session_state
        bloqueado = sim.lineal is not None

        # Selector de tipo de sistema (el primer control del sidebar)
        tipo_gemelo = st.selectbox(
            "Tipo de sistema",
            options=["Lineal", "Pívot", "Corner"],
            disabled=bloqueado,
            key="k_tipo_gemelo",
            help="Pívot y Corner estarán disponibles en la próxima versión.",
        )
        st.divider()

        # Modo observador: muestra info de solo lectura y sale
        if not state.get("es_operador", False) and bloqueado:
            _renderizar_sidebar_observador(sim)
            return

        # Tipos aún no implementados
        if tipo_gemelo != "Lineal":
            st.info(
                f"**{tipo_gemelo}** estará disponible próximamente.\n\n"
                f"Actualmente solo el Lineal FSS está implementado."
            )
            return

        # Configuración del Lineal FSS
        st.caption("Configura tu Lineal FSS")

        st.markdown("##### Geometría")
        if bloqueado:
            st.markdown(
                "<span style='color:#484f58;font-size:0.72rem'>Simulación activa — parámetros bloqueados</span>",
                unsafe_allow_html=True,
            )
        col_tramos, col_tlen = st.columns(2)
        numero_tramos = col_tramos.number_input("N° de tramos", 3, 20, 5, 1, disabled=bloqueado, key="k_tramos")
        longitud_tramo = col_tlen.number_input("Long. tramo (m)", 5, 500, 50, 5, disabled=bloqueado, key="k_tlen")
        col_vnom, col_campo = st.columns(2)
        velocidad_nominal = col_vnom.number_input("Vel. nominal (m/min)", 0.5, 10.0, 3.0, 0.5, disabled=bloqueado, key="k_vnom")
        longitud_campo = col_campo.number_input("Campo total (m)", 100, 5000,  800,  50, disabled=bloqueado, key="k_campo")

        st.markdown("##### Panel speed")
        velocidad_porcentaje = st.slider(
            "Panel speed  (Duty cycle %)", 1, 100, 50,
            key="k_vpct", format="%d %%",
            help="Porcentaje de la velocidad máxima a la que avanza el lineal.",
        )
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
            "Factor de escala temporal",
            1, 600, 60, key="k_simspd", format="x%d",
            help="Cuántos segundos de simulación avanza el modelo entre cada refresco.",
        )
        st.caption(f"Cada refresco = **{segundos_por_refresco} s** simulados")

        st.divider()
        st.markdown("##### Terreno")
        terreno = st.selectbox(
            "Tipo de patinaje",
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
            help="El lineal rebota automáticamente entre los límites configurados.",
        )
        if auto_reverse_activo:
            limite_norte_defecto = int(state.get("k_campo", 800))
            col_ymin, col_ymax = st.columns(2)
            col_ymin.number_input("Y mín (m)", min_value=0, max_value=limite_norte_defecto, value=state.get("k_ar_ymin", 0), step=5, key="k_ar_ymin")
            col_ymax.number_input("Y máx (m)", min_value=0, max_value=int(longitud_campo), value=state.get("k_ar_ymax", limite_norte_defecto), step=5, key="k_ar_ymax")
            st.caption(
                f"Rebota entre **{state.get('k_ar_ymin', 0)} m** y **{state.get('k_ar_ymax', limite_norte_defecto)} m**"
                + (f"  ·  **{sim.numero_inversiones}** inversiones" if sim.en_marcha else "")
            )

        st.divider()
        st.markdown("##### Conexión externa")
        st.radio(
            "Modo de conexión",
            options=["ninguno", "caja"],
            format_func=lambda k: {
                "ninguno": "Sin conexión",
                "caja":    "Caja de interfaz GPS  (2 Arduinos, I2C, 115 200 baud)",
            }[k],
            key="k_conexion_modo", disabled=bloqueado,
            label_visibility="collapsed",
        )
        modo_conexion = state.get("k_conexion_modo", "ninguno")
        puertos = [p.device for p in _list_ports.comports()] if _SERIAL_DISPONIBLE else []

        if modo_conexion == "caja":
            _renderizar_seccion_conexion_caja(numero_tramos, longitud_tramo, bloqueado, puertos)

        if modo_conexion == "caja":
            st.divider()
            st.markdown("##### Interferencia GPS simulada")
            interferencia = st.slider(
                "Desvío aleatorio por emisión (mm)",
                min_value=0, max_value=15, value=0, step=1,
                key="k_interferencia_gps_mm",
                help="±X mm de error aleatorio añadido a cada coordenada enviada.",
            )
            st.caption(
                f"Enviando coordenada con ±{interferencia} mm de ruido" if interferencia > 0
                else "Sin interferencia — coordenada perfecta"
            )

        st.divider()
        st.markdown("##### Trayectoria objetivo GPS")
        st.toggle("Activar trayectoria", key="k_tray_activa", help="Define puntos de guiado para la sección GPS. Se calcula error de distancia y rumbo.")
        _renderizar_seccion_trayectoria(bloqueado)

        st.divider()

        # Botones de control
        if sim.lineal is None:
            if st.button("INICIAR", key="btn_iniciar", type="primary", width="stretch"):
                _iniciar_simulacion(numero_tramos, longitud_tramo, velocidad_porcentaje, velocidad_nominal, longitud_campo)
                st.rerun()

        elif sim.en_marcha:
            if st.button("STOP", key="btn_stop", width="stretch"):
                sim.lineal.stop()
                if sim.lineal.caja_interfaz:
                    sim.lineal.caja_interfaz.detener()
                sim.registro.append({"t": sim.lineal._tiempo_formateado(), "tipo": "STOP", "msg": f"Sistema pausado en {sim.lineal.posicion_norte:.2f} m"})
                sim.en_marcha = False
                sim.pausado = True
                sim.motivo_pausa = "manual"
                st.rerun()

        elif sim.pausado and not sim.completado:
            caja = sim.lineal.caja_interfaz
            safety_fail = caja is not None and not caja.safety_ok
            gps_fail = caja is not None and not caja.gps_ok
            continuar_bloqueado = safety_fail or gps_fail

            col_continuar, col_reset = st.columns(2)
            if col_continuar.button("CONTINUAR", key="btn_start", type="primary", width="stretch", disabled=continuar_bloqueado):
                sim.lineal.start()
                if sim.lineal.caja_interfaz:
                    sim.lineal.caja_interfaz.iniciar()
                sim.registro.append({"t": sim.lineal._tiempo_formateado(), "tipo": "START", "msg": f"Sistema reanudado desde {sim.lineal.posicion_norte:.2f} m"})
                sim.en_marcha = True
                sim.pausado = False
                sim.motivo_pausa = None
                st.rerun()
            if col_reset.button("RESET", key="btn_reset", width="stretch"):
                _limpiar_y_resetear()
                st.rerun()

            if safety_fail:
                st.error("SAFETY FAIL activo — resuelve el problema antes de continuar")
            elif gps_fail:
                st.warning("GPS FAIL activo — esperando que se restaure la señal GPS")

        elif sim.completado:
            if st.button("REINICIAR", key="btn_reiniciar", type="primary", width="stretch"):
                _limpiar_y_resetear()
                st.rerun()

        st.divider()
        st.markdown("##### Teclado (simulación activa)")
        _renderizar_referencia_teclado(activo=True)
        st.divider()
