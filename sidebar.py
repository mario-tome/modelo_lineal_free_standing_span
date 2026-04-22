import streamlit as st
from modelo import Lineal
from constantes import TERRENOS, get_defaults

try:
    import serial.tools.list_ports as _list_ports
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

SIN_PUERTO      = "— Sin puerto (solo consola) —"
SIN_CAJA_PUERTO = "— Selecciona puerto —"


def _iniciar_simulacion(tramos, t_len, vel_pct, v_nom, campo):
    state = st.session_state
    ruido_terreno = TERRENOS.get(state.get("k_terreno", "Normal"), 0.012)
    state.lineal = Lineal(
        numero_tramos        = tramos,
        longitud_tramo       = t_len,
        velocidad_porcentaje = vel_pct,
        velocidad_nominal    = v_nom,
        ruido_lateral        = ruido_terreno,
    )
    state.lineal.start()
    state.log.append({"t": "00h 00m 00s", "tipo": "START", "msg": "Sistema iniciado"})

    modo_conexion = state.get("k_conexion_modo", "ninguno")
    if modo_conexion == "gps":
        puerto_raw = state.get("k_gps_puerto", SIN_PUERTO)
        puerto = None if (puerto_raw == SIN_PUERTO) else puerto_raw
        state.lineal.asignar_gps(
            indice_torre    = state.get("k_gps_torre", 1),
            lat_origen      = state.get("k_gps_lat_e7", 404168000) / 1e7,
            lon_origen      = state.get("k_gps_lon_e7", -37038000) / 1e7,
            puerto_serial   = puerto,
            verbose_consola = (puerto is None),
        )
        state.lineal.gps.iniciar_transmision_background()

    if modo_conexion == "caja":
        puerto_caja = state.get("k_caja_puerto", "")
        if puerto_caja and puerto_caja != SIN_CAJA_PUERTO:
            state.lineal.asignar_caja(
                indice_torre  = state.get("k_caja_torre", 1),
                lat_origen    = state.get("k_caja_lat_e7", 404168000) / 1e7,
                lon_origen    = state.get("k_caja_lon_e7", -37038000) / 1e7,
                puerto_serial = puerto_caja,
                carr          = state.get("k_caja_carr", 2),
            )
            state.lineal.caja_interfaz.iniciar()

    state.longitud_campo  = campo
    state.running         = True
    state.finished        = False
    state.paused          = False
    state.caja_slow_prev  = {"cart": False, "end": False, "safety": True}
    state.tower_trails    = [[] for _ in range(len(state.lineal.torres))]


def _limpiar_y_resetear():
    state = st.session_state
    if state.lineal and state.lineal.gps:
        state.lineal.gps.detener_transmision_background()
    if state.lineal and state.lineal.caja_interfaz:
        state.lineal.caja_interfaz.detener()
    valores_defecto = get_defaults()
    for clave, valor in valores_defecto.items():
        state[clave] = valor


def renderizar_sidebar():
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
        terreno_sel = st.selectbox(
            "Elije el tipo de patinaje",
            options=list(TERRENOS.keys()),
            index=2,
            key="k_terreno",
            disabled=locked,
            help="Modela la deriva lateral natural de las torres guía según las irregularidades del terreno.",
        )
        ruido_val = TERRENOS[terreno_sel]
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
            ar_ymin_def = 0
            ar_ymax_def = int(state.get("k_campo", 800))
            c_ar1, c_ar2 = st.columns(2)
            c_ar1.number_input(
                "Y mín (m)", min_value=0, max_value=ar_ymax_def,
                value=state.get("k_ar_ymin", ar_ymin_def),
                step=5, key="k_ar_ymin",
                help="Posición norte mínima — al llegar aquí en marcha atrás se invierte a avance",
            )
            c_ar2.number_input(
                "Y máx (m)", min_value=0, max_value=int(campo),
                value=state.get("k_ar_ymax", ar_ymax_def),
                step=5, key="k_ar_ymax",
                help="Posición norte máxima — al llegar aquí en avance se invierte a marcha atrás",
            )
            ymin_display  = state.get("k_ar_ymin", ar_ymin_def)
            ymax_display  = state.get("k_ar_ymax", ar_ymax_def)
            pasadas       = state.get("ar_pasadas", 0)
            st.caption(
                f"Rebota entre **{ymin_display} m** y **{ymax_display} m**"
                + (f"  ·  **{pasadas}** inversiones" if state.running else "")
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
            key="k_conexion_modo",
            disabled=locked,
            label_visibility="collapsed",
        )
        modo   = state.get("k_conexion_modo", "ninguno")
        gps_on  = (modo == "gps")
        caja_on = (modo == "caja")

        if _SERIAL_DISPONIBLE:
            puertos_serie = [p.device for p in _list_ports.comports()]
        else:
            puertos_serie = []

        if gps_on:
            st.selectbox(
                "Torre con el GPS",
                options=list(range(1, tramos)),
                key="k_gps_torre",
                disabled=locked,
                format_func=lambda i: f"Intermedia {i}",
            )
            c_lat, c_lon = st.columns(2)
            c_lat.number_input("Lat. origen (×10⁷)", value=404168000, step=1,
                               key="k_gps_lat_e7", disabled=locked)
            c_lon.number_input("Lon. origen (×10⁷)", value=-37038000, step=1,
                               key="k_gps_lon_e7", disabled=locked)
            st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie</p>',
                        unsafe_allow_html=True)
            c_puerto, c_refresh = st.columns([6, 1])
            with c_puerto:
                st.selectbox("Puerto serie",
                             options=[SIN_PUERTO] + puertos_serie,
                             key="k_gps_puerto", disabled=locked, label_visibility="collapsed")
            with c_refresh:
                if st.button("↺", help="Actualizar puertos", disabled=locked, width="stretch"):
                    st.rerun()

        if caja_on:
            st.selectbox(
                "Torre GPS", options=list(range(1, tramos)),
                key="k_caja_torre", disabled=locked,
                format_func=lambda i: f"Intermedia {i}",
                help="Torre cuya posición se envía al Arduino como coordenada GPS.",
            )
            st.session_state["k_caja_carr"] = 2
            c_lat_c, c_lon_c = st.columns(2)
            c_lat_c.number_input("Lat. origen (×10⁷)", value=404168000, step=1,
                                  key="k_caja_lat_e7", disabled=locked)
            c_lon_c.number_input("Lon. origen (×10⁷)", value=-37038000, step=1,
                                  key="k_caja_lon_e7", disabled=locked)
            st.markdown('<p style="font-size:0.875rem;margin:0 0 4px 0">Puerto serie Arduino</p>',
                        unsafe_allow_html=True)
            c_pcaja, c_rcaja = st.columns([6, 1])
            with c_pcaja:
                st.selectbox(
                    "Puerto serie caja",
                    options=puertos_serie if puertos_serie else [SIN_CAJA_PUERTO],
                    key="k_caja_puerto", disabled=locked, label_visibility="collapsed",
                )
            with c_rcaja:
                if st.button("↺", help="Actualizar puertos", disabled=locked,
                             width="stretch", key="btn_ref_caja"):
                    st.rerun()
            st.caption("Arduino conectado a este PC · cable USB normal · Carr=2 (RTK FIX) fijo")

        st.divider()
        st.markdown("##### Trayectoria objetivo GPS")
        st.toggle(
            "Activar trayectoria",
            key="k_tray_activa",
            help="Define los puntos de guiado que debe seguir la torre GPS. "
                 "Se visualiza en el campo y se calculan EΔd y EΔrumbo en tiempo real.",
        )
        if state.get("k_tray_activa", False):
            st.caption("Un punto por línea  ·  formato:  LAT×10⁷  LON×10⁷")
            st.text_area(
                "Puntos de trayectoria",
                key="k_tray_input",
                height=110,
                label_visibility="collapsed",
                placeholder="415191807 -37038000\n415195000 -37030000\n415200000 -37020000",
            )
            from trayectoria import get_origen_latlon, parse_trayectoria
            lat_sb, lon_sb = get_origen_latlon()
            puntos_sb = parse_trayectoria(state.get("k_tray_input", ""), lat_sb, lon_sb)
            if len(puntos_sb) >= 2:
                st.caption(f"{len(puntos_sb)} puntos validos  ·  {len(puntos_sb) - 1} segmentos")
            elif len(puntos_sb) == 1:
                st.caption("Minimo 2 puntos para definir un segmento")
            else:
                st.caption("Introduce puntos en el formato indicado")

        st.divider()

        if state.lineal is None:
            if st.button("INICIAR", key="btn_iniciar", type="primary", width="stretch"):
                _iniciar_simulacion(tramos, t_len, vel_pct, v_nom, campo)
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
                _limpiar_y_resetear()
                st.rerun()

        elif state.finished:
            if st.button("REINICIAR", key="btn_reiniciar", type="primary", width="stretch"):
                _limpiar_y_resetear()
                st.rerun()

        st.divider()
        st.markdown("##### Teclado (simulación activa)")
        for tecla, descripcion in [
            ("< (mantener)", "Ralentiza Cart — sigue motor rápido, giro gradual izquierda"),
            ("- (mantener)", "Ralentiza End-tower — sigue motor rápido, giro gradual derecha"),
            ("R (pulsar)",   "Marcha atrás / avance normal"),
        ]:
            st.markdown(
                f"<code style='background:#161b22;border:1px solid #30363d;border-radius:4px;"
                f"padding:1px 6px;font-size:0.78rem;color:#e6edf3'>{tecla}</code>"
                f"<span style='color:#8b949e;font-size:0.78rem;margin-left:6px'>{descripcion}</span>",
                unsafe_allow_html=True,
            )

        st.divider()
