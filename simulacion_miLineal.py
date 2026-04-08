from modelo import Lineal
import time


# 1. CONFIGURACION DEL LINEAL
NUMERO_TRAMOS        = 5
LONGITUD_TRAMO       = 50     # metros
VELOCIDAD_NOMINAL    = 3.0    # m/min cuando el motor esta ON
VELOCIDAD_PORCENTAJE = 50     # % de tiempo ON  = velocidad media = 3.0 × 50% = 1.5 m/min


# 2. CONFIGURACION GPS
INDICE_TORRE_GPS  = 2        # torre intermedia que lleva el GPS (1..NUMERO_TRAMOS-1)
LAT_ORIGEN        = 40.4168  # latitud  real del punto X=0,Y=0 del campo (grados decimales)
LON_ORIGEN        = -3.7038  # longitud real del punto X=0,Y=0 del campo (grados decimales)
PUERTO_SERIAL_GPS = None     # ej. 'COM3' para hardware real; None = solo consola


# 3. CONFIGURACION DEL CAMPO
LONGITUD_CAMPO = 800    # metros a recorrer
PAUSA_VISUAL   = 0.3    # segundos reales entre pantallas (0 = sin pausa)


# 4. ACCIONES
# Formato: (segundo_simulado, "start" o "stop")
ACCIONES = [
    (0,    "start"),
    # (1800, "stop"),    # para a los 30 min
    # (2400, "start"),   # rearranque a los 40 min
]


# CREACION Y PRESENTACION DEL LINEAL
lineal = Lineal(
    numero_tramos        = NUMERO_TRAMOS,
    longitud_tramo       = LONGITUD_TRAMO,
    velocidad_porcentaje = VELOCIDAD_PORCENTAJE,
    velocidad_nominal    = VELOCIDAD_NOMINAL
)

lineal.asignar_gps(
    indice_torre  = INDICE_TORRE_GPS,
    lat_origen    = LAT_ORIGEN,
    lon_origen    = LON_ORIGEN,
    puerto_serial = PUERTO_SERIAL_GPS,
)

vel_media = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0

print()
print("  Sistema de Riego Lineal - Free Standing Span")
print()
print(f"  Lineal   : {lineal.numero_tramos} tramos  |  {len(lineal.torres)} torres  |  {lineal.longitud_total:.0f} m total")
print(f"            Tramo rigido: Tramo {lineal.indice_tramo_rigido + 1}  |  Motor mas rapido: Torre {lineal.indice_torre_motor_rapido}")
print(f"  Velocidad: {lineal.velocidad_nominal:.1f} m/min nominal  |  {lineal.velocidad_porcentaje:.0f}% duty cycle  ->  {vel_media:.2f} m/min media")
print(f"  Campo    : {LONGITUD_CAMPO} m  |  Tiempo estimado: ~{LONGITUD_CAMPO / vel_media:.0f} min")
print(f"  GPS      : Torre {INDICE_TORRE_GPS}  |  origen ({LAT_ORIGEN}, {LON_ORIGEN})  |  puerto: {PUERTO_SERIAL_GPS or 'consola'}")
print()
print("  Acciones programadas:")
for seg, acc in sorted(ACCIONES, key=lambda a: a[0]):
    print(f"    t = {seg//3600:02d}h {(seg%3600)//60:02d}m {seg%60:02d}s  ->  {acc.upper()}")
print()


# SIMULACION
acciones_pendientes = sorted(ACCIONES, key=lambda a: a[0])
bitacora = []

while lineal.posicion_norte < LONGITUD_CAMPO:

    segundo_actual = lineal.tiempo_total_segundos

    acciones_restantes = []
    for segundo, accion in acciones_pendientes:
        if segundo == segundo_actual:
            if accion == "start":
                lineal.start()
            elif accion == "stop":
                lineal.stop()
            bitacora.append(f"  {accion.upper():<6} t = {lineal._tiempo_formateado()}  posicion = {lineal.posicion_norte:.2f} m")
            print()
            print(f"  {'=' * 42}")
            print(f"  {accion.upper()}   t = {lineal._tiempo_formateado()}")
            print(f"  {'=' * 42}")
            lineal.estado()
            time.sleep(max(PAUSA_VISUAL, 2.0))
        else:
            acciones_restantes.append((segundo, accion))
    acciones_pendientes = acciones_restantes

    lineal.avanza(1)

    if lineal.tiempo_total_segundos % 300 == 0:
        lineal.estado()
        if PAUSA_VISUAL > 0:
            time.sleep(PAUSA_VISUAL)


# RESUMEN FINAL
print()
print("  Riego completado")
print()
print(f"  Tiempo simulado  : {lineal._tiempo_formateado()}")
print(f"  Ciclos           : {lineal.ciclo_actual}")
print(f"  Distancia media  : {lineal.posicion_norte:.2f} m")
print()

if bitacora:
    print("  Acciones ejecutadas:")
    for entrada in bitacora:
        print(entrada)
    print()

print("  Posicion final por torre:")
for i, torre in enumerate(lineal.torres):
    if i == 0:
        etiqueta = "Guia Izq (Cart)"
    elif i == len(lineal.torres) - 1:
        etiqueta = "Guia Der"
    elif i == lineal.indice_torre_motor_rapido:
        etiqueta = f"Intermedia {i} [++]"
    else:
        etiqueta = f"Intermedia {i}"
    print(f"    {etiqueta:<20}  y = {torre.posicion_y:.3f} m")
print()

print("  Desviacion y angulo final por tramo:")
for i, tramo in enumerate(lineal.tramos, 1):
    estado_txt = "ok" if tramo.esta_alineado else "DESVIADO"
    print(f"    Tramo {i}  desv = {tramo.desviacion_norte:+.3f} m  angulo = {tramo.angulo_grados:+.3f} grd  {estado_txt}")
print()
