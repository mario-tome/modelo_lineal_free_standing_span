import math, os
from datetime import datetime
import streamlit as st
from modelos import Lineal
from logica.constantes import TERRENOS, get_defaults
from logica.estado import get_sim, SimState, CLAVES_SIMULACION
from logica.trayectoria import get_origen_latlon, parse_trayectoria

_DIR_EXPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")

try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

SIN_CAJA_PUERTO = "— Selecciona puerto —"


def _seccion(titulo: str) -> None:
    """Encabezado de sección del sidebar: blanco, legible, con peso visual claro."""
    st.markdown(
        f"<p style='color:#e6edf3;font-size:0.95rem;font-weight:600;"
        f"margin:8px 0 2px 0;letter-spacing:0.3px'>{titulo}</p>",
        unsafe_allow_html=True,
    )


# SIDEBAR PARA EL MODO OBSERVADOR (solo lectura)

def _punto_estado(etiqueta: str, activo: bool, color_activo: str, color_inactivo: str = "#484f58") -> str:
    """Fila de estado con punto de color: · Safety OK · GPS FAIL etc."""
    color = color_activo if activo else color_inactivo
    return (
        f"<div style='display:flex;align-items:center;gap:6px;margin:3px 0'>"
        f"<span style='width:7px;height:7px;border-radius:50%;background:{color};"
        f"flex-shrink:0'></span>"
        f"<span style='color:{color};font-size:0.82rem;font-family:monospace;font-weight:600'>"
        f"{etiqueta}</span>"
        f"</div>"
    )


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

    # Configuración del lineal en marcha
    _seccion("Lineal activo")
    longitud_total = lineal.numero_tramos * lineal.longitud_tramo
    st.markdown(
        f"<p style='color:#e6edf3;font-size:0.88rem;margin:2px 0 8px 0'>"
        f"{lineal.numero_tramos} tramos · {lineal.longitud_tramo} m/tramo · "
        f"<b>{longitud_total} m</b> totales</p>",
        unsafe_allow_html=True,
    )

    velocidad_media = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
    st.markdown(
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:12px 16px;margin:4px 0 10px 0;"
        f"display:grid;grid-template-columns:1fr 1fr;gap:4px'>"
        f"<div>"
        f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
        f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Panel speed</div>"
        f"<div style='color:#e6edf3;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{lineal.velocidad_porcentaje}"
        f"<span style='color:#8b949e;font-size:0.82rem;font-weight:400'> %</span></div>"
        f"</div>"
        f"<div>"
        f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
        f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Vel. media</div>"
        f"<div style='color:#3fb950;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{velocidad_media:.2f}"
        f"<span style='color:#8b949e;font-size:0.82rem;font-weight:400'> m/min</span></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Conexión GPS: tramo, formato y estado en tiempo real
    st.divider()
    _seccion("Conexión GPS")

    if lineal.caja_interfaz:
        caja = lineal.caja_interfaz

        try:
            indice_tramo = lineal.secciones.index(caja.antena_path.seccion_inicio)
            etiqueta_tramo = f"Tramo {indice_tramo + 1}  (secciones {indice_tramo} → {indice_tramo + 1})"
        except ValueError:
            etiqueta_tramo = "Tramo —"

        nombre_formato = "Geográfico  (Lat/Lon ×10⁷)" if caja.modo_coordenadas == "geo" else "Cartesiano  (X/Y mm)"

        st.markdown(
            f"<p style='color:#e6edf3;font-size:0.85rem;margin:4px 0 2px 0'>{etiqueta_tramo}</p>"
            f"<p style='color:#8b949e;font-size:0.80rem;margin:0 0 8px 0'>{nombre_formato}</p>",
            unsafe_allow_html=True,
        )

        col_izq, col_der = st.columns(2)
        with col_izq:
            st.markdown(_punto_estado("Safety OK",  caja.safety_ok,           "#3fb950", "#f85149"), unsafe_allow_html=True)
            st.markdown(_punto_estado("Slow Cart",  caja.slow_down_cart,      "#ffa657"), unsafe_allow_html=True)
        with col_der:
            st.markdown(_punto_estado("GPS OK",     caja.gps_ok,              "#3fb950", "#f85149"), unsafe_allow_html=True)
            st.markdown(_punto_estado("Slow EndT",  caja.slow_down_end_tower, "#ffa657"), unsafe_allow_html=True)
    else:
        st.markdown(
            "<p style='color:#8b949e;font-size:0.85rem;margin:4px 0'>Sin conexión externa</p>",
            unsafe_allow_html=True,
        )

    # Trayectoria: error de distancia y rumbo en tiempo real
    if sim.trayectoria_activa and sim.trayectoria_puntos:
        st.divider()
        _seccion("Trayectoria objetivo")

        numero_puntos = len(sim.trayectoria_puntos)
        texto_distancia = f"{sim.error_distancia_mm:.0f} mm" if sim.error_distancia_mm is not None else "—"
        texto_rumbo     = f"{sim.error_rumbo_grados:+.1f}°"  if sim.error_rumbo_grados  is not None else "—"

        st.markdown(
            f"<p style='color:#8b949e;font-size:0.80rem;margin:4px 0 8px 0'>"
            f"{numero_puntos} puntos · {numero_puntos - 1} segmentos</p>"
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
            f"padding:12px 16px;display:grid;grid-template-columns:1fr 1fr;gap:4px'>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Error dist.</div>"
            f"<div style='color:#e6edf3;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
            f"{texto_distancia}</div>"
            f"</div>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Error rumbo</div>"
            f"<div style='color:#e6edf3;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
            f"{texto_rumbo}</div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Auto-reverse
    if sim.auto_reverse_activo:
        st.divider()
        _seccion("Auto-reverse")
        st.markdown(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
            f"padding:12px 16px;display:grid;grid-template-columns:1fr 1fr;gap:4px'>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Rango</div>"
            f"<div style='color:#e6edf3;font-size:0.92rem;font-weight:600;font-family:monospace'>"
            f"{sim.limite_sur:.0f} — {sim.limite_norte:.0f} m</div>"
            f"</div>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Inversiones</div>"
            f"<div style='color:#e6edf3;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
            f"{sim.numero_inversiones}</div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

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
                indice_tramo      = state.get("k_caja_tramo", 0),
                metros_path       = float(state.get("k_caja_metros_path", longitud_tramo * 0.25)),
                metros_heading    = float(state.get("k_caja_metros_heading", longitud_tramo * 0.75)),
                lat_origen        = state.get("k_caja_lat_e7", 404168000) / 1e7,
                lon_origen        = state.get("k_caja_lon_e7", -37038000) / 1e7,
                puerto_path       = puerto_path,
                puerto_heading    = puerto_heading if puerto_heading and puerto_heading != SIN_CAJA_PUERTO else puerto_path,
                modo_coordenadas  = state.get("k_caja_modo_coordenadas", "geo"),
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
    st.session_state["es_operador"] = False


# BLOQUES DE CONFIGURACIÓN DE CONEXIÓN GPS, CAJA ARDUINO Y TRAYECTORIA GPS OBJETIVO


def _renderizar_seccion_conexion_caja(numero_tramos: int, longitud_tramo: float,
                                       bloqueado: bool, puertos: list) -> None:
    state = st.session_state
    state["k_caja_carr"] = 2  # Carr=2 significa RTK FIX (la caja Arduino solo acepta este modo de posicionamiento)

    st.radio(
        "Formato de coordenadas",
        options=["geo", "cartesiana"],
        format_func=lambda k: {
            "geo":        "Geográficas  (Lat/Lon ×10⁷)",
            "cartesiana": "Cartesianas  (X/Y en mm)",
        }[k],
        key="k_caja_modo_coordenadas",
        disabled=bloqueado,
        help="Geográficas: protocolo GPS estándar · Cartesianas: coordenadas locales del campo en milímetros.",
    )
    modo = state.get("k_caja_modo_coordenadas", "geo")

    col_lat, col_lon = st.columns(2)
    col_lat.number_input("Lat. origen (×10⁷)", value=404168000, step=1, key="k_caja_lat_e7", disabled=bloqueado or modo == "cartesiana")
    col_lon.number_input("Lon. origen (×10⁷)", value=-37038000, step=1, key="k_caja_lon_e7", disabled=bloqueado or modo == "cartesiana")

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
        st.markdown(
            "<p style='color:#e6edf3;font-size:1.45rem;font-weight:700;"
            "margin:4px 0 6px 0;letter-spacing:-0.2px'>"
            "Gemelo <span style='color:#3fb950'>Digital</span></p>",
            unsafe_allow_html=True,
        )

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
        st.markdown(
            "<p style='color:#e6edf3;font-size:1.0rem;font-weight:400;margin:0 0 12px 0'>"
            "Configura tu Lineal FSS</p>",
            unsafe_allow_html=True,
        )

        _seccion("Geometría")
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

        _seccion("Panel speed")
        velocidad_porcentaje = st.slider(
            "Panel speed  (Duty cycle %)", 1, 100, 50,
            key="k_vpct", format="%d %%",
            help="Porcentaje de la velocidad máxima a la que avanza el lineal.",
        )
        velocidad_media = velocidad_porcentaje / 100 * velocidad_nominal
        st.markdown(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
            f"padding:12px 16px;margin:4px 0 10px 0;"
            f"display:grid;grid-template-columns:1fr 1fr;gap:4px'>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Tiempo ON</div>"
            f"<div style='color:#e6edf3;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
            f"{velocidad_porcentaje * 60 / 100:.0f}"
            f"<span style='color:#8b949e;font-size:0.82rem;font-weight:400'> s / 60 s</span></div>"
            f"</div>"
            f"<div>"
            f"<div style='color:#8b949e;font-size:0.72rem;letter-spacing:1.5px;"
            f"text-transform:uppercase;font-family:monospace;margin-bottom:4px'>Vel. media</div>"
            f"<div style='color:#3fb950;font-size:1.1rem;font-weight:700;font-family:monospace;line-height:1'>"
            f"{velocidad_media:.2f}"
            f"<span style='color:#8b949e;font-size:0.82rem;font-weight:400'> m/min</span></div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        _seccion("Simulación")
        segundos_por_refresco = st.slider(
            "Factor de escala temporal",
            1, 600, 60, key="k_simspd", format="x%d",
            help="Cuántos segundos de simulación avanza el modelo entre cada refresco.",
        )
        st.caption(f"Cada refresco = **{segundos_por_refresco} s** simulados")

        st.divider()
        _seccion("Terreno")
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
        _seccion("Auto-reverse")
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
        _seccion("Conexión externa")
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
            _seccion("Ruido de posición simulado")
            interferencia = st.slider(
                "Desvío aleatorio por emisión (mm)",
                min_value=0, max_value=15, value=0, step=1,
                key="k_interferencia_gps_mm",
                help="±X mm de error aleatorio añadido a cada coordenada enviada, independientemente del formato.",
            )
            st.caption(
                f"Enviando coordenada con ±{interferencia} mm de ruido" if interferencia > 0
                else "Sin ruido — coordenada exacta"
            )

        st.divider()
        _seccion("Trayectoria objetivo GPS")
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
                sim.estado_previo_caja = {"cart": False, "end": False, "safety": True, "gps": True}
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
