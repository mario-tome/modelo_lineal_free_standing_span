import math
import plotly.graph_objects as go
from V2.modelos import Lineal, TramoFinal, TramoIntermedio

def _nombre_seccion_corto(lineal: Lineal, indice: int) -> str:
    if indice == 0:
        return "CART"
    if indice == len(lineal.secciones) - 1:
        return "END"
    sec = lineal.secciones[indice]
    if sec is lineal.torre_rapida:
        return f"I{indice}★"
    return f"I{indice}"


def _color_span(span_info: dict) -> str:
    if not span_info["esta_alineado"]:
        return "#f85149"
    if abs(span_info["angulo_relativo_grados"]) < 0.5:
        return "#3fb950"
    return "#e3b341"


def _estilo_seccion(lineal: Lineal, i: int):
    sec = lineal.secciones[i]
    n = len(lineal.secciones)
    if i == 0:
        return "#f78166", "square", "CART", 20
    if i == n - 1:
        return "#d2a8ff", "square", "END", 20
    if sec is lineal.torre_rapida:
        return "#ffa657", "star", f"I{i}★", 18
    if i <= lineal.indice_fss_izq:
        return "#58a6ff", "circle", f"I{i}", 14
    return "#56d364", "circle", f"I{i}", 14


def _hex_a_rgba(hex_color: str, alpha: float) -> str:
    """Convierte #rrggbb a rgba(r,g,b,alpha) para usar como fillcolor de Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _geometria_viga(x0: float, y0: float, x1: float, y1: float,
                    semi_ancho: float, n_outline: int = 20, n_celdas: int = 6
                    ) -> tuple[list, list, list, list]:
    """
    Calcula la silueta y la celosía interior de una viga estructural entre dos extremos.
    La sección transversal es sinusoidal: ancha en el centro, apuntada en los extremos.
    Devuelve (outline_xs, outline_ys, lat_xs, lat_ys) para construir trazos Plotly.
    """
    dx, dy = x1 - x0, y1 - y0
    longitud = math.hypot(dx, dy)
    if longitud < 1e-6:
        return [], [], [], []

    px, py = -dy / longitud, dx / longitud  # vector perpendicular unitario

    def punto(t: float, lado: float) -> tuple[float, float]:
        cx, cy = x0 + t * dx, y0 + t * dy
        w = semi_ancho * math.sin(math.pi * t)
        return cx + lado * w * px, cy + lado * w * py

    # Silueta exterior: arco superior de A→B, arco inferior de B→A, cierra en A
    ts = [i / (n_outline - 1) for i in range(n_outline)]
    top = [punto(t, +1) for t in ts]
    bot = [punto(t, -1) for t in ts]
    outline_xs = [p[0] for p in top] + [p[0] for p in reversed(bot)] + [top[0][0]]
    outline_ys = [p[1] for p in top] + [p[1] for p in reversed(bot)] + [top[0][1]]

    # Celosía interna: diagonales cruzadas entre nodos equidistantes
    ts_div = [i / n_celdas for i in range(n_celdas + 1)]
    pts_t = [punto(t, +1) for t in ts_div]
    pts_b = [punto(t, -1) for t in ts_div]
    lat_xs, lat_ys = [], []
    for i in range(n_celdas):
        # Diagonal ↗: nodo inferior izq → nodo superior der
        lat_xs += [pts_b[i][0], pts_t[i + 1][0], None]
        lat_ys += [pts_b[i][1], pts_t[i + 1][1], None]
        # Diagonal ↘: nodo superior izq → nodo inferior der
        lat_xs += [pts_t[i][0], pts_b[i + 1][0], None]
        lat_ys += [pts_t[i][1], pts_b[i + 1][1], None]

    return outline_xs, outline_ys, lat_xs, lat_ys


def build_figure(lineal: Lineal | None, longitud_campo: float,
                 posicion_norte: float = 0.0,
                 vista_general: bool = False,
                 rastros_secciones: list | None = None,
                 trayectoria_xy: list | None = None) -> go.Figure:
    """Construye la figura Plotly del campo con secciones y tramos"""

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

    ancho_campo = lineal.longitud_total
    alto_campo = longitud_campo
    trazos, formas, anotaciones = [], [], []

    _ANCHO_INTERIOR_PX = 960
    _ALTO_INTERIOR_PX = 660
    _MARGEN_VERTICAL = 140

    pad_x = ancho_campo * 0.06
    pad_y = max(20.0, ancho_campo * 0.05)

    if not vista_general:
        rango_x_metros = ancho_campo + 2 * pad_x
        alto_viewport = rango_x_metros * _ALTO_INTERIOR_PX / _ANCHO_INTERIOR_PX - 2 * pad_y
        alto_viewport = max(alto_viewport, ancho_campo * 0.25)
        rango_total_y = alto_viewport + 2 * pad_y

        if rango_total_y >= alto_campo + 2 * pad_y:
            y_lo = -pad_y
            y_hi = alto_campo + pad_y
        else:
            y_lo = posicion_norte - alto_viewport * 0.30 - pad_y
            y_hi = y_lo + rango_total_y
            if y_lo < -pad_y:
                y_lo = -pad_y
                y_hi = y_lo + rango_total_y
            if y_hi > alto_campo + pad_y:
                y_hi = alto_campo + pad_y
                y_lo = y_hi - rango_total_y

        rango_y_metros = y_hi - y_lo
        altura_figura = int(_ANCHO_INTERIOR_PX * rango_y_metros / rango_x_metros) + _MARGEN_VERTICAL
        altura_figura = max(400, min(altura_figura, 950))
        usar_scaleanchor = True
    else:
        y_lo = -alto_campo * 0.20
        y_hi = alto_campo + alto_campo * 0.20
        altura_figura = 620
        usar_scaleanchor = False

    formas.append(dict(type="rect", xref="x", yref="y",
        x0=0, y0=0, x1=ancho_campo, y1=alto_campo,
        fillcolor="#0a1f10", line=dict(color="#30363d", width=1), layer="below"))

    min_y = min(s.posicion_y for s in lineal.secciones)
    if min_y > 0.1:
        formas.append(dict(type="rect", xref="x", yref="y",
            x0=0, y0=0, x1=ancho_campo, y1=min_y,
            fillcolor="rgba(63,185,80,0.10)", line=dict(width=0), layer="below"))

    # Cuadrícula horizontal
    paso_filas = max(2, int((y_hi - y_lo) / 40))
    xs_cuad, ys_cuad = [], []
    for y in range(0, int(alto_campo) + 1, paso_filas):
        xs_cuad += [0, ancho_campo, None]
        ys_cuad += [y, y, None]
    trazos.append(go.Scatter(x=xs_cuad, y=ys_cuad, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1),
        hoverinfo="skip", showlegend=False))

    # Columnas verticales por tramo
    xs_col, ys_col = [], []
    for i in range(lineal.numero_tramos + 1):
        xv = i * lineal.longitud_tramo
        xs_col += [xv, xv, None]
        ys_col += [0, alto_campo, None]
    trazos.append(go.Scatter(x=xs_col, y=ys_col, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False))

    # Rastros históricos de cada sección
    if rastros_secciones:
        for idx_sec in range(len(lineal.secciones)):
            trail = rastros_secciones[idx_sec] if idx_sec < len(rastros_secciones) else []
            if len(trail) < 2:
                continue
            color_sec, _, _, _ = _estilo_seccion(lineal, idx_sec)
            trazos.append(go.Scatter(
                x=[p[0] for p in trail], y=[p[1] for p in trail],
                mode="lines",
                line=dict(color=color_sec, width=1.5),
                opacity=0.35,
                hoverinfo="skip", showlegend=False,
            ))

    # Trayectoria objetivo GPS
    COLOR_TRAY = "#79c0ff"
    if trayectoria_xy and len(trayectoria_xy) >= 2:
        tx = [p[0] for p in trayectoria_xy]
        ty = [p[1] for p in trayectoria_xy]
        trazos.append(go.Scatter(x=tx, y=ty, mode="lines",
            line=dict(color=COLOR_TRAY, width=2, dash="dot"),
            hoverinfo="skip", showlegend=False))
        trazos.append(go.Scatter(
            x=tx, y=ty, mode="markers+text",
            text=[f"P{i+1}" for i in range(len(trayectoria_xy))],
            textposition="top center",
            textfont=dict(color=COLOR_TRAY, size=11, family="monospace"),
            marker=dict(color=COLOR_TRAY, size=10, symbol="diamond", line=dict(color="#0d1117", width=1.5)),
            hovertemplate=[
                f"<b>P{i+1}</b><br>X = {p[0]:.1f} m<br>Y = {p[1]:.1f} m<extra></extra>"
                for i, p in enumerate(trayectoria_xy)
            ],
            showlegend=False,
        ))

    # Tramos (spans entre secciones adyacentes)
    for idx in range(lineal.numero_tramos):
        sp = lineal.get_span_info(idx)
        color = _color_span(sp)
        nombre_izq = _nombre_seccion_corto(lineal, idx)
        nombre_der = _nombre_seccion_corto(lineal, idx + 1)

        hover = (
            f"<b>Tramo {idx + 1}</b>  {nombre_izq} → {nombre_der}<br>"
            f"Angulo rel: <b>{sp['angulo_relativo_grados']:+.3f} grd</b><br>"
            f"Desviacion rel: {sp['desviacion_norte_relativa']:+.3f} m<br>"
            f"Estado: {'OK' if sp['esta_alineado'] else 'DESVIADO'}"
            f"<extra></extra>"
        )

        longitud_span = math.hypot(sp["x1"] - sp["x0"], sp["y1"] - sp["y0"])
        # FSS más ancho para reflejar su mayor rigidez estructural
        semi_ancho = longitud_span * (0.070 if sp["es_rigido"] else 0.055)
        outline_xs, outline_ys, lat_xs, lat_ys = _geometria_viga(
            sp["x0"], sp["y0"], sp["x1"], sp["y1"], semi_ancho
        )
        if outline_xs:
            # Cuerpo de la viga: polígono relleno, hover en toda el área
            trazos.append(go.Scatter(
                x=outline_xs, y=outline_ys, mode="lines",
                fill="toself", fillcolor=_hex_a_rgba(color, 0.13),
                line=dict(color=color, width=1.5),
                hoveron="fills", hovertemplate=hover,
                showlegend=False,
            ))
        if lat_xs:
            # Celosía interior (diagonales X — sin hover)
            trazos.append(go.Scatter(
                x=lat_xs, y=lat_ys, mode="lines",
                line=dict(color=color, width=0.9), opacity=0.50,
                hoverinfo="skip", showlegend=False,
            ))

        mx, my = (sp["x0"] + sp["x1"]) / 2, (sp["y0"] + sp["y1"]) / 2
        if sp["es_rigido"]:
            texto_ano = f"<b>T{idx+1}  FSS</b>"
        else:
            texto_ano = (
                f"<b>T{idx+1}</b>  {nombre_izq}→{nombre_der}<br>"
                f"{sp['angulo_relativo_grados']:+.2f}°  /  {sp['desviacion_norte_relativa']:+.3f} m"
            )
        anotaciones.append(dict(
            x=mx, y=my, text=texto_ano, showarrow=False,
            font=dict(color=color, size=11, family="monospace"),
            bgcolor="rgba(13,17,23,0.82)", bordercolor=color,
            borderwidth=1, borderpad=5, xref="x", yref="y", align="center",
        ))

    # Eje transversal de rodaje de cada sección (vista cenital del tren de ruedas)
    xs_ejes, ys_ejes = [], []
    for sec in lineal.secciones:
        # Las torres guía (Cart/End) tienen un tren más ancho que las intermedias
        ancho_eje = (lineal.longitud_tramo * 0.110 if isinstance(sec, TramoFinal)
                     else lineal.longitud_tramo * 0.075)
        xs_ejes += [sec.posicion_x - ancho_eje, sec.posicion_x + ancho_eje, None]
        ys_ejes += [sec.posicion_y, sec.posicion_y, None]
    trazos.append(go.Scatter(
        x=xs_ejes, y=ys_ejes, mode="lines",
        line=dict(color="#555d68", width=5),
        opacity=0.80,
        hoverinfo="skip", showlegend=False,
    ))

    # Secciones (puntos con etiquetas)
    total_secciones = len(lineal.secciones)
    indice_seccion_gps = -1
    if lineal.gps:
        try:
            indice_seccion_gps = lineal.secciones.index(lineal.gps.tramo)
        except ValueError:
            pass

    for i, sec in enumerate(lineal.secciones):
        color, simbolo, etiqueta, tamanio = _estilo_seccion(lineal, i)

        if i == 0:
            nombre = "TramoFinal (Cart)"
        elif i == total_secciones - 1:
            nombre = "TramoFinal (End-tower)"
        elif sec is lineal.torre_rapida:
            nombre = f"TramoIntermedio {i}  [Motor Rápido ★]"
        elif i <= lineal.indice_fss_izq:
            nombre = f"TramoIntermedio {i}  [cascada izquierda]"
        else:
            nombre = f"TramoIntermedio {i}  [cascada derecha]"

        motor_activo = sec.motor_activo

        en_slow_down = (
            isinstance(sec, TramoFinal) and (
                (i == 0 and lineal.slow_down_cart) or
                (i == total_secciones - 1 and lineal.slow_down_end_tower)
            )
        )

        if isinstance(sec, TramoFinal):
            if en_slow_down:
                texto_motor = f"Motor: {'ON' if motor_activo else 'OFF'}  (sigue motor rápido)"
            else:
                texto_motor = f"Motor: {'ON' if motor_activo else 'OFF'}  (duty cycle {sec.velocidad_porcentaje:.0f}%)"
        else:
            texto_motor = f"Motor: {'ON — corrigiendo' if motor_activo else 'OFF — alineada'}"

        hover_gps = ""
        if i == indice_seccion_gps:
            g = lineal.gps
            hover_gps = (
                f"<br><span style='color:#58d68d'>&#128225; GPS</span><br>"
                f"LAT: <b>{g.lat_e7}</b><br>LON: <b>{g.lon_e7}</b>"
            )
        hover = (
            f"<b>{nombre}</b><br>"
            f"X = {sec.posicion_x:.0f} m<br>Y = {sec.posicion_y:.3f} m<br>"
            f"{texto_motor}{hover_gps}<extra></extra>"
        )

        color_borde_contactor = "#3fb950" if motor_activo else "#484f58"

        if isinstance(sec, TramoFinal):
            if en_slow_down:
                texto_estado = f"Motor {'ON' if motor_activo else 'OFF'}  · (sigue rápido)"
                color_estado = "#e3b341"
            else:
                texto_estado = f"Speed {sec.velocidad_porcentaje:.0f}%  {'ON' if motor_activo else 'OFF'}"
                color_estado = color
        else:
            if motor_activo:
                texto_estado, color_estado = "Corrigiendo  ·  Motor ON", "#e3b341"
            else:
                texto_estado, color_estado = "Alineada  ·  Motor OFF", "#3fb950"

        trazos.append(go.Scatter(
            x=[sec.posicion_x], y=[sec.posicion_y], mode="markers",
            marker=dict(color=color, size=tamanio + 14, opacity=0.18, symbol=simbolo),
            hoverinfo="skip", showlegend=False))
        trazos.append(go.Scatter(
            x=[sec.posicion_x], y=[sec.posicion_y], mode="markers",
            marker=dict(color=color, size=tamanio, symbol=simbolo, line=dict(color=color_borde_contactor, width=2)),
            hovertemplate=hover, showlegend=False))

        desplazamiento_anotacion = -90 if i % 2 == 0 else 90
        if i == indice_seccion_gps:
            desplazamiento_anotacion = 90
        anotaciones.append(dict(
            x=sec.posicion_x, y=sec.posicion_y, xref="x", yref="y",
            text=f"<b>{etiqueta}</b>  X={sec.posicion_x:.2f} m  Y={sec.posicion_y:.2f} m<br>{texto_estado}",
            showarrow=True, arrowhead=2, arrowwidth=1.5, arrowsize=0.7,
            arrowcolor=color, ax=0, ay=desplazamiento_anotacion,
            font=dict(color=color_estado, size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor=color_estado, borderwidth=1, borderpad=10,
            align="center",
        ))

    # Halo GPS
    if lineal.gps is not None:
        gps = lineal.gps
        gps_x = gps.tramo.posicion_x
        gps_y = gps.tramo.posicion_y
        trazos.append(go.Scatter(
            x=[gps_x], y=[gps_y], mode="markers",
            marker=dict(color="#58d68d", size=42, opacity=0.15, symbol="circle"),
            hoverinfo="skip", showlegend=False))
        trazos.append(go.Scatter(
            x=[gps_x], y=[gps_y], mode="markers",
            marker=dict(color="#58d68d", size=12, symbol="circle-cross-open", line=dict(color="#58d68d", width=2.5)),
            hovertemplate=(
                f"<b>GPS</b><br>LAT: <b>{gps.lat_e7}</b><br>LON: <b>{gps.lon_e7}</b><br>"
                f"{gps.latitud:.7f}°,  {gps.longitud:.7f}°<extra></extra>"
            ),
            showlegend=False))
        anotaciones.append(dict(
            x=gps_x, y=gps_y, xref="x", yref="y",
            text=f"<b>GPS</b><br>{gps.latitud:.5f}°<br>{gps.longitud:.5f}°",
            showarrow=True, arrowhead=2, arrowwidth=1.5, arrowsize=0.7,
            arrowcolor="#58d68d", ax=0, ay=-100,
            font=dict(color="#58d68d", size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor="#58d68d", borderwidth=1, borderpad=10, align="center",
        ))

    pasos_nice = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
    paso_ticks = next((s for s in pasos_nice if alto_campo / s <= 15), 1000)
    valores_tick = list(range(0, int(alto_campo) + paso_ticks + 1, paso_ticks))

    fig = go.Figure(data=trazos)
    config_eje_y = dict(
        title=dict(text="Norte  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False, range=[y_lo, y_hi],
        tickmode="array", tickvals=valores_tick,
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    config_eje_x = dict(
        title=dict(text="Oeste  —  Este  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False,
        range=[-pad_x, ancho_campo + pad_x],
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    if usar_scaleanchor:
        config_eje_y["scaleanchor"] = "x"
        config_eje_y["scaleratio"]  = 1
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117", plot_bgcolor="#0a1f10",
        height=altura_figura,
        margin=dict(l=70, r=40, t=90, b=50),
        xaxis=config_eje_x, yaxis=config_eje_y,
        shapes=formas, annotations=anotaciones,
        hovermode="closest", dragmode="pan",
    )
    return fig
