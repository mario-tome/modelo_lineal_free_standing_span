import csv, math, os
import streamlit as st
from V2.modelos import Lineal, TramoFinal, TramoIntermedio, AntenaGPS, CajaInterfaz
from V2.logica.constantes import TERRENOS
from V2.logica.estado import get_sim, SimState
from V2.logica.trayectoria import get_origen_latlon, parse_trayectoria, calcular_errores
from V2.ui.figura import build_figure


# MÉTODOS DE AVANCE DE SIMULACIÓN

def _sincronizar_configuracion(sim: SimState, lineal: Lineal) -> list:
    """
    Lee los controles del sidebar y aplica los valores actuales al modelo
    Devuelve los puntos de trayectoria activos (lista vacía si no hay trayectoria)
    """
    ui = st.session_state

    puntos_tray = []
    if ui.get("k_tray_activa", False):
        lat, lon = get_origen_latlon()
        puntos = parse_trayectoria(ui.get("k_tray_input", ""), lat, lon)
        if len(puntos) >= 2:
            sim.trayectoria_activa = True
            sim.trayectoria_puntos = puntos
            puntos_tray = puntos
        else:
            sim.trayectoria_activa = False
            sim.trayectoria_puntos = None
    else:
        sim.trayectoria_activa = False
        sim.trayectoria_puntos = None

    lineal.set_speed(ui.get("k_vpct", 50))
    nivel_patinaje = TERRENOS.get(ui.get("k_terreno", "Normal"), 0.012)
    lineal.tramo_cart.ruido_lateral = nivel_patinaje
    lineal.tramo_end.ruido_lateral  = nivel_patinaje

    interferencia_mm = float(ui.get("k_interferencia_gps_mm", 0))
    if lineal.caja_interfaz:
        lineal.caja_interfaz.interferencia_gps_mm = interferencia_mm

    sim.auto_reverse_activo = bool(ui.get("k_auto_reverse", False))
    sim.limite_sur = float(ui.get("k_ar_ymin", 0))
    sim.limite_norte = float(ui.get("k_ar_ymax", sim.longitud_campo))

    return puntos_tray


def _procesar_mensajes_caja(sim: SimState, lineal: Lineal) -> None:
    """
    Procesa los mensajes recibidos de la caja de interfaz:
    actualiza slow_down, detecta safety/GPS fail y reanuda automáticamente.
    """
    caja = lineal.caja_interfaz
    if not caja:
        return
    previo = sim.estado_previo_caja

    # Cambios en slow_down (solo se registran si la simulación está en marcha)
    if sim.en_marcha:
        if caja.slow_down_cart != previo["cart"]:
            previo["cart"] = caja.slow_down_cart
            sim.registro.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_CART ON — Cart ralentizado, giro gradual hacia izquierda"
                        if caja.slow_down_cart
                        else "SLOW_DOWN_CART OFF — Cart a velocidad normal"),
            })
        if caja.slow_down_end_tower != previo["end"]:
            previo["end"] = caja.slow_down_end_tower
            sim.registro.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_END_TOWER ON — End-tower ralentizado, giro gradual hacia derecha"
                        if caja.slow_down_end_tower
                        else "SLOW_DOWN_END_TOWER OFF — End-tower a velocidad normal"),
            })
        lineal.slow_down_cart      = caja.slow_down_cart
        lineal.slow_down_end_tower = caja.slow_down_end_tower

    if not caja.safety_ok and previo.get("safety", True):
        previo["safety"] = False
        lineal.stop()
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT", "msg": "SAFETY_FAIL — parada de emergencia"})
        sim.en_marcha = False
        sim.pausado = True
        sim.motivo_pausa = "safety_fail"
    elif caja.safety_ok and not previo.get("safety", True):
        previo["safety"] = True
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "OK", "msg": "SAFETY_OK — seguridad restaurada (reanuda manualmente)"})

    # GPS fail → pausa; GPS ok → reanuda automáticamente si fue por pérdida de GPS
    if not caja.gps_ok and previo.get("gps", True):
        previo["gps"] = False
        if sim.en_marcha:
            lineal.stop()
            sim.en_marcha = False
            sim.pausado = True
            sim.motivo_pausa = "gps_fail"
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT", "msg": "GPS_FAIL — señal GPS perdida, simulación pausada"})
    elif caja.gps_ok and not previo.get("gps", True):
        previo["gps"] = True
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "OK", "msg": "GPS_OK — señal GPS restaurada"})
        if sim.pausado and sim.motivo_pausa == "gps_fail":
            lineal.start()
            caja.iniciar()
            sim.en_marcha = True
            sim.pausado = False
            sim.motivo_pausa = None
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "START", "msg": "Reanudación automática tras recuperar GPS"})


def _actualizar_errores_trayectoria(sim: SimState, lineal: Lineal, puntos_tray: list) -> None:
    """Calcula y almacena los errores de distancia y rumbo respecto a la trayectoria"""
    if not (sim.trayectoria_activa and puntos_tray):
        sim.error_distancia_mm = None
        sim.error_rumbo_grados = None
        return

    tramo_gps, indice_gps = _get_tramo_gps(lineal)
    if tramo_gps is None:
        sim.error_distancia_mm = None
        sim.error_rumbo_grados = None
        return

    posiciones_pasadas = (sim.rastros_secciones[indice_gps]
                          if sim.rastros_secciones and indice_gps < len(sim.rastros_secciones)
                          else [])
    error_dist, error_rumbo = calcular_errores(
        tramo_gps.posicion_x, tramo_gps.posicion_y,
        puntos_tray, posiciones_pasadas, lineal.en_marcha_atras,
    )
    sim.error_distancia_mm = error_dist
    sim.error_rumbo_grados = error_rumbo


def _avanzar_tick(sim: SimState, lineal: Lineal, segundos: int, puntos_tray: list) -> None:
    """
    Avanza el modelo un tick y actualiza todos los datos derivados:
    rastros de posición, velocidad real, errores de trayectoria, CSV, historial GPS y log de alineación
    """
    lineal.avanza(segundos)

    if sim.rastros_secciones and len(sim.rastros_secciones) == len(lineal.secciones):
        for idx, sec in enumerate(lineal.secciones):
            rastro = sim.rastros_secciones[idx]
            xn, yn = sec.posicion_x, sec.posicion_y
            if not rastro or math.hypot(xn - rastro[-1][0], yn - rastro[-1][1]) >= 0.5:
                rastro.append((xn, yn))
        if len(sim.rastros_secciones[0]) > 20_000:
            sim.rastros_secciones = [r[-20_000:] for r in sim.rastros_secciones]

    sim.velocidad_real = (lineal.posicion_norte - sim.posicion_norte_previa) / (segundos / 60.0)
    sim.posicion_norte_previa = lineal.posicion_norte

    # Errores de trayectoria (antes de escribir CSV para que la fila tenga los valores actualizados)
    _actualizar_errores_trayectoria(sim, lineal, puntos_tray)

    _escribir_fila_csv(sim, _construir_fila_csv(sim, lineal))


    # Log de alineación: detecta desalineamientos y recuperaciones tramo a tramo
    alineacion_actual = [lineal.get_span_alineado(j) for j in range(lineal.numero_tramos)]
    if sim.alineacion_previa is not None:
        for j, (previo, actual) in enumerate(zip(sim.alineacion_previa, alineacion_actual)):
            if previo and not actual:
                sp = lineal.get_span_info(j)
                sim.registro.append({
                    "t": lineal._tiempo_formateado(), "tipo": "CRIT",
                    "msg": f"Tramo {j+1} desalineado  ({sp['desviacion_norte']:+.3f} m)",
                })
            elif not previo and actual:
                sim.registro.append({
                    "t": lineal._tiempo_formateado(), "tipo": "OK",
                    "msg": f"Tramo {j+1} recuperado",
                })
    sim.alineacion_previa = alineacion_actual


def _gestionar_limites(sim: SimState, lineal: Lineal) -> None:
    """Detecta si el lineal llegó al límite del campo y aplica auto-reverse o detiene"""
    if sim.auto_reverse_activo:
        posicion = lineal.posicion_norte
        if not lineal.en_marcha_atras and posicion >= sim.limite_norte:
            lineal.invertir_direccion()
            sim.numero_inversiones += 1
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "INFO", "msg": f"Auto-reverse ▼  ({posicion:.1f} m ≥ {sim.limite_norte:.0f} m)  — pasada #{sim.numero_inversiones}"})
        elif lineal.en_marcha_atras and posicion <= sim.limite_sur:
            lineal.invertir_direccion()
            sim.numero_inversiones += 1
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "INFO", "msg": f"Auto-reverse ▲  ({posicion:.1f} m ≤ {sim.limite_sur:.0f} m)  — pasada #{sim.numero_inversiones}"})
    else:
        if lineal.posicion_norte >= sim.longitud_campo:
            lineal.stop()
            if lineal.caja_interfaz:
                lineal.caja_interfaz.detener()
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "FIN", "msg": f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}"})
            sim.en_marcha  = False
            sim.completado = True
            st.rerun()


def _avanzar_simulacion(sim: SimState) -> None:
    """Orquesta un tick completo: sincroniza config → procesa caja → avanza → gestiona límites"""
    lineal = sim.lineal
    if lineal is None:
        sim.trayectoria_activa = False
        sim.trayectoria_puntos = None
        return

    puntos_tray = _sincronizar_configuracion(sim, lineal)
    _procesar_mensajes_caja(sim, lineal)

    if sim.en_marcha and not sim.completado:
        segundos_por_tick = st.session_state.get("k_simspd", 60)
        _avanzar_tick(sim, lineal, segundos_por_tick, puntos_tray)
        _gestionar_limites(sim, lineal)
    else:
        # Aunque esté pausado, mantenemos los errores de trayectoria actualizados
        _actualizar_errores_trayectoria(sim, lineal, puntos_tray)


# MÉTODOS DE CSV

def _construir_fila_csv(sim: SimState, lineal: Lineal) -> dict:
    """Construye la fila de datos del tick actual para exportar al CSV."""
    fila = {
        "tiempo_s": lineal.tiempo_total_segundos,
        "tiempo": lineal._tiempo_formateado(),
        "posicion_norte": round(lineal.posicion_norte, 3),
        "slow_cart": lineal.slow_down_cart,
        "slow_end_tower": lineal.slow_down_end_tower,
    }
    for j, sec in enumerate(lineal.secciones):
        fila[f"seccion_{j}_x"] = round(sec.posicion_x, 4)
        fila[f"seccion_{j}_y"] = round(sec.posicion_y, 4)
        if j < lineal.numero_tramos:
            sp = lineal.get_span_info(j)
            fila[f"tramo_{j+1}_longitud_m"] = round(sp["longitud"], 4)
            fila[f"tramo_{j+1}_deformacion"] = round(lineal.longitud_tramo - sp["longitud"], 4)
            fila[f"tramo_{j+1}_desv_norte"] = round(sp["desviacion_norte"], 4)
            fila[f"tramo_{j+1}_rumbo_deg"] = round(sp["angulo_grados"], 4)

    if lineal.caja_interfaz:
        fila["path_lat_e7"]    = lineal.caja_interfaz.antena_path.lat_e7
        fila["path_lon_e7"]    = lineal.caja_interfaz.antena_path.lon_e7
        fila["heading_lat_e7"] = lineal.caja_interfaz.antena_heading.lat_e7
        fila["heading_lon_e7"] = lineal.caja_interfaz.antena_heading.lon_e7
    else:
        fila["path_lat_e7"] = fila["path_lon_e7"] = None
        fila["heading_lat_e7"] = fila["heading_lon_e7"] = None
    fila["error_distancia_mm"] = round(sim.error_distancia_mm, 1) if sim.error_distancia_mm is not None else None
    fila["error_rumbo_deg"] = round(sim.error_rumbo_grados, 2) if sim.error_rumbo_grados is not None else None
    return fila


def _escribir_fila_csv(sim: SimState, fila: dict) -> None:
    ruta = sim.get("csv_ruta")
    if not ruta:
        return
    primera_vez = (sim.csv_filas_escritas == 0)
    with open(ruta, "a", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila.keys()), restval="", extrasaction="ignore")
        if primera_vez:
            escritor.writeheader()
        escritor.writerow(fila)
    sim.csv_filas_escritas += 1


# MÉTODOS DEL GPS

def _get_tramo_gps(lineal: Lineal) -> tuple[AntenaGPS | None, int]:
    """
    Devuelve (antena_path, indice_de_seccion_inicio) o (None, -1) si no hay caja configurada.
    La antena_path es la que guía (la que genera slow_down) y tiene posicion_x/y en tiempo real.
    """
    if not lineal.caja_interfaz:
        return None, -1
    antena = lineal.caja_interfaz.antena_path
    try:
        return antena, lineal.secciones.index(antena.seccion_inicio)
    except ValueError:
        return None, -1


# BLOQUES HTML REUTILIZABLES

def _html_barra_progreso_auto_reverse(
    lineal: Lineal, limite_sur: float, limite_norte: float, numero_inversiones: int
) -> str:
    amplitud = max(limite_norte - limite_sur, 1.0)
    posicion_acotada = max(limite_sur, min(limite_norte, lineal.posicion_norte))
    porcentaje_barra = (posicion_acotada - limite_sur) / amplitud * 100.0
    color_barra = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
    simbolo = "▼" if lineal.en_marcha_atras else "▲"
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0;"
        f"height:130px;box-sizing:border-box'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px'>"
        f"<span style='color:#e6edf3;font-size:0.88rem;letter-spacing:2px;text-transform:uppercase;font-family:monospace;font-weight:600'>"
        f"Auto-reverse  ·  {limite_sur:.0f} m — {limite_norte:.0f} m</span>"
        f"<span style='color:{color_barra};font-size:1.5rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{simbolo}&nbsp;{lineal.posicion_norte:.1f}<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
        f"</div>"
        f"<div style='position:relative;background:#21262d;border-radius:4px;height:8px;margin-bottom:8px'>"
        f"<div style='position:absolute;left:0;top:0;background:rgba(63,185,80,0.12);border-radius:4px;width:{porcentaje_barra:.2f}%;height:100%'></div>"
        f"<div style='position:absolute;top:-3px;left:calc({porcentaje_barra:.2f}% - 7px);width:14px;height:14px;"
        f"border-radius:50%;background:{color_barra};box-shadow:0 0 6px {color_barra}'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:#e6edf3;font-size:0.88rem;font-weight:600;font-family:monospace'>{numero_inversiones} inversiones</span>"
        f"<span style='color:#e6edf3;font-size:0.88rem;font-family:monospace'>rango {amplitud:.0f} m</span>"
        f"</div></div>"
    )


def _html_barra_progreso_lineal(posicion_norte: float, longitud_campo: float) -> str:
    porcentaje = min(posicion_norte / longitud_campo * 100.0, 100.0)
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0;"
        f"height:130px;box-sizing:border-box'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px'>"
        f"<span style='color:#e6edf3;font-size:0.88rem;letter-spacing:2px;text-transform:uppercase;font-family:monospace;font-weight:600'>Recorrido del campo</span>"
        f"<span style='color:#e6edf3;font-size:1.5rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{porcentaje:.1f}<span style='color:#8b949e;font-size:0.9rem'>%</span></span>"
        f"</div>"
        f"<div style='background:#21262d;border-radius:4px;height:6px;overflow:hidden;margin-bottom:8px'>"
        f"<div style='background:linear-gradient(90deg,#238636 0%,#3fb950 100%);width:{porcentaje:.2f}%;height:100%;border-radius:4px'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:#e6edf3;font-size:0.88rem;font-weight:600;font-family:monospace'>{posicion_norte:.1f} m avanzados</span>"
        f"<span style='color:#e6edf3;font-size:0.88rem;font-family:monospace'>meta {longitud_campo:.0f} m</span>"
        f"</div></div>"
    )


_COLORES_REGISTRO = {
    "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
    "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
}
_MAX_ENTRADAS_VISIBLES = 500


def _html_registro(registro: list) -> str:
    """
    Panel de log con scroll fijo — mismo estilo visual que las barras de progreso.
    Entradas ilimitadas en memoria; muestra las últimas _MAX_ENTRADAS_VISIBLES más recientes arriba.
    Un único st.markdown() por rerun → O(1) sin importar el volumen.
    """
    total = len(registro)
    entradas = registro[-_MAX_ENTRADAS_VISIBLES:][::-1]
    pie = f"{total}" if total <= _MAX_ENTRADAS_VISIBLES else f"{_MAX_ENTRADAS_VISIBLES} / {total}"

    filas = "".join(
        f"<div style='padding:4px 0;border-bottom:1px solid #21262d;white-space:nowrap;"
        f"overflow:hidden;text-overflow:ellipsis'>"
        f"<code style='color:#e6edf3;font-size:0.78rem'>{e['t']}</code>&nbsp;"
        f"<span style='background:{_COLORES_REGISTRO.get(e['tipo'], '#8b949e')}22;"
        f"color:{_COLORES_REGISTRO.get(e['tipo'], '#8b949e')};"
        f"border-radius:3px;padding:1px 6px;font-size:0.74rem;font-family:monospace;font-weight:700'>"
        f"{e['tipo']}</span>&nbsp;"
        f"<span style='color:#e6edf3;font-size:0.88rem'>{e['msg']}</span>"
        f"</div>"
        for e in entradas
    )

    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0;"
        f"height:130px;box-sizing:border-box'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px'>"
        f"<span style='color:#e6edf3;font-size:0.88rem;letter-spacing:2px;"
        f"text-transform:uppercase;font-family:monospace;font-weight:600'>Logs</span>"
        f"<span style='color:#e6edf3;font-size:0.82rem;font-family:monospace'>{pie}</span>"
        f"</div>"
        f"<div style='height:80px;overflow-y:auto'>"
        f"{filas}"
        f"</div>"
        f"</div>"
    )


def _html_chip_error_trayectoria(etiqueta: str, valor_texto: str) -> str:
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:6px;"
        f"padding:0 12px;display:flex;align-items:center;gap:8px;height:38px;white-space:nowrap'>"
        f"<span style='font-size:0.85rem;color:#8b949e;font-family:monospace'>{etiqueta}</span>"
        f"<span style='font-size:0.85rem;font-weight:700;color:#e6edf3'>{valor_texto}</span>"
        f"</div>"
    )


# PANEL PRINCIPAL 

@st.fragment(run_every=1)
def panel_principal():
    sim = get_sim()
    lineal: Lineal | None = sim.lineal
    longitud_campo = sim.longitud_campo
    es_operador = st.session_state.get("es_operador", False)

    if es_operador:
        _avanzar_simulacion(sim)
        lineal = sim.lineal

    st.markdown(
        "<h1 style='font-size:2rem;margin:0 0 6px 0'>GEMELO DIGITAL "
        "<span style='color:#3fb950'>LINEAL FSS</span></h1>",
        unsafe_allow_html=True,
    )

    # Insignia de estado
    # Barra de progreso + Logs (lado a lado, misma altura) — visión de estado inmediata
    if lineal:
        col_progreso, col_registro = st.columns([7, 3])
        with col_progreso:
            if sim.auto_reverse_activo:
                st.markdown(
                    _html_barra_progreso_auto_reverse(lineal, sim.limite_sur, sim.limite_norte, sim.numero_inversiones),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    _html_barra_progreso_lineal(lineal.posicion_norte, longitud_campo),
                    unsafe_allow_html=True,
                )
        with col_registro:
            if sim.registro:
                st.markdown(_html_registro(sim.registro), unsafe_allow_html=True)

    # Métricas principales
    columnas_metricas = st.columns(10)
    if lineal:
        porcentaje_recorrido = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        velocidad_teorica = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        diferencia_velocidad = sim.velocidad_real - velocidad_teorica
        cart_en_slowdown = lineal.slow_down_cart
        end_en_slowdown = lineal.slow_down_end_tower

        estado_cart = ("★ ON"  if lineal.tramo_cart.motor_activo else "★ OFF") if cart_en_slowdown else \
                      ("ON"    if lineal.tramo_cart.motor_activo else "OFF")
        estado_end  = ("★ ON"  if lineal.tramo_end.motor_activo  else "★ OFF") if end_en_slowdown else \
                      ("ON"    if lineal.tramo_end.motor_activo  else "OFF")

        columnas_metricas[0].metric("Tiempo campo", lineal._tiempo_formateado())
        columnas_metricas[1].metric("Ciclo", str(lineal.ciclo_actual))
        columnas_metricas[2].metric("Posición media", f"{lineal.posicion_norte:.2f} m")
        columnas_metricas[3].metric("Recorrido", f"{porcentaje_recorrido:.1f} %")
        columnas_metricas[4].metric("Alineación", "OK" if lineal.esta_alineado else "Corrigiendo")
        columnas_metricas[5].metric("Cart", estado_cart, help="★ = en slow_down, sigue al motor rápido" if cart_en_slowdown else None)
        columnas_metricas[6].metric("End-tower", estado_end, help="★ = en slow_down, sigue al motor rápido" if end_en_slowdown else None)
        columnas_metricas[7].metric("Vel. real", f"{sim.velocidad_real:.2f} m/min", delta=f"{diferencia_velocidad:+.2f} vs teórica", delta_color="normal")
        columnas_metricas[8].metric("Motor ★ activo", f"{lineal.motor_rapido_pct_on:.0f} %", help="% del último ciclo con el motor rápido encendido")
        columnas_metricas[9].metric("Dirección", "▼ ATRÁS" if lineal.en_marcha_atras else "▲ ADELANTE")
    else:
        for columna in columnas_metricas:
            columna.metric("—", "—")

    # Métricas caja de interfaz GPS (se añaden al bloque de detalle cuando hay conexión)
    if lineal and lineal.caja_interfaz:
        caja = lineal.caja_interfaz
        color_safety = "#3fb950" if caja.safety_ok else "#f85149"
        color_gps_ok = "#3fb950" if caja.gps_ok   else "#f85149"
        color_cart   = "#ffa657" if caja.slow_down_cart      else "#484f58"
        color_end    = "#ffa657" if caja.slow_down_end_tower else "#484f58"

        col_p, col_h, col_sf, col_gk, col_sc, col_se = st.columns(6)
        if caja.modo_coordenadas == "cartesiana":
            col_p.metric("GPS Path",
                         f"{round(caja.antena_path.posicion_x * 1000)} / {round(caja.antena_path.posicion_y * 1000)} mm",
                         help="X / Y en milímetros — modo cartesiano")
            col_h.metric("GPS Heading",
                         f"{round(caja.antena_heading.posicion_x * 1000)} / {round(caja.antena_heading.posicion_y * 1000)} mm",
                         help="X / Y en milímetros — modo cartesiano")
        else:
            col_p.metric("GPS Path",    f"{caja.antena_path.lat_e7} / {caja.antena_path.lon_e7}",
                         help=f"{caja.antena_path.latitud:.7f}°  {caja.antena_path.longitud:.7f}°")
            col_h.metric("GPS Heading", f"{caja.antena_heading.lat_e7} / {caja.antena_heading.lon_e7}",
                         help=f"{caja.antena_heading.latitud:.7f}°  {caja.antena_heading.longitud:.7f}°")
        col_sf.metric("Safety",    "OK" if caja.safety_ok           else "FAIL")
        col_gk.metric("GPS status","OK" if caja.gps_ok              else "FAIL")
        col_sc.metric("Slow Cart", "ON" if caja.slow_down_cart      else "—")
        col_se.metric("Slow EndT", "ON" if caja.slow_down_end_tower else "—")
        st.markdown(
            f"<div style='display:flex;gap:12px;margin:-12px 0 8px 0;flex-wrap:wrap;align-items:center'>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_safety};font-family:monospace'>"
            f"&#9679; SAFETY {'OK' if caja.safety_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_gps_ok};font-family:monospace'>"
            f"&#9679; GPS {'OK' if caja.gps_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_cart};font-family:monospace'>"
            f"&#9679; SLOW_CART {'ON' if caja.slow_down_cart else 'OFF'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_end};font-family:monospace'>"
            f"&#9679; SLOW_END_TWR {'ON' if caja.slow_down_end_tower else 'OFF'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:#e6edf3;font-family:monospace'>"
            f"último msg: {caja.ultimo_mensaje or '—'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Barra de herramientas: toggle, errores, CSV
    trayectoria_visible = sim.trayectoria_activa or st.session_state.get("k_tray_activa", False)

    if trayectoria_visible:
        col_toggle, col_error_dist, col_error_rumbo, col_csv, _esp = st.columns([1, 1, 1, 1, 6])
    else:
        col_toggle, col_csv, _esp = st.columns([1, 1, 7])
        col_error_dist = col_error_rumbo = None

    with col_toggle:
        st.toggle("Vista general", key="k_vista_general", help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo")

    if trayectoria_visible and col_error_dist is not None:
        texto_distancia = f"{sim.error_distancia_mm:.0f} mm" if sim.error_distancia_mm is not None else "—"
        texto_rumbo = f"{sim.error_rumbo_grados:+.1f}°" if sim.error_rumbo_grados is not None else "—"
        with col_error_dist:
            st.markdown(_html_chip_error_trayectoria("Δd", texto_distancia), unsafe_allow_html=True)
        with col_error_rumbo:
            st.markdown(_html_chip_error_trayectoria("Δrumbo", texto_rumbo), unsafe_allow_html=True)

    if lineal:
        with col_csv:
            tiene_datos = sim.csv_ruta and sim.csv_filas_escritas > 0
            if tiene_datos and not sim.en_marcha:
                with open(sim.csv_ruta, "rb") as archivo_csv:
                    st.download_button(
                        label="⬇ CSV", data=archivo_csv.read(),
                        file_name=os.path.basename(sim.csv_ruta),
                        mime="text/csv", width="stretch",
                    )


    # Figura Plotly del campo
    posicion_norte = lineal.posicion_norte if lineal is not None else 0.0

    if st.session_state.get("k_tray_activa", False) and lineal is not None:
        lat_fig, lon_fig = get_origen_latlon()
        pts_fig = parse_trayectoria(st.session_state.get("k_tray_input", ""), lat_fig, lon_fig)
        puntos_figura = pts_fig if len(pts_fig) >= 2 else None
    else:
        puntos_figura = sim.trayectoria_puntos

    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, posicion_norte,
            st.session_state.get("k_vista_general", False),
            rastros_secciones=sim.rastros_secciones,
            trayectoria_xy=puntos_figura,
        ),
        width="stretch",
        key="campo_lineal_v2",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
            "toImageButtonOptions": {"filename": "lineal_fss_v2", "format": "png"},
        },
    )
