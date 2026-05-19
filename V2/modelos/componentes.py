import math, random, threading
import time as _time

try:
    import serial as _serial_module
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

# 1 grado de latitud ≈ 111 320 m
METROS_POR_GRADO_LAT = 111_320.0


def avanzar_en_circunferencia(
    centro_x: float, centro_y: float, radio: float,
    inicio_x: float, inicio_y: float, distancia: float,
) -> tuple:
    """
    Posición final de un móvil que recorre una distancia sobre una circunferencia.
    distancia > 0 = antihorario  ·  distancia < 0 = horario
    """
    angulo_inicial   = math.atan2(inicio_y - centro_y, inicio_x - centro_x)
    angulo_recorrido = distancia / radio
    angulo_final     = angulo_inicial + angulo_recorrido
    return (
        centro_x + radio * math.cos(angulo_final),
        centro_y + radio * math.sin(angulo_final),
    )


class TramoFinal:
    """
    Sección extrema del lineal: Cart (izquierda) o End-tower (derecha).
    Avanza por duty cycle (ciclo ON/OFF de 60 s).
    En modo slow_down abandona su duty cycle y copia el ritmo del motor rápido.
    """

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float,
                 velocidad_nominal: float = 3.0,
                 velocidad_porcentaje: float = 50.0,
                 ruido_lateral: float = 0.0):

        self.posicion_x           = posicion_x
        self.posicion_y           = posicion_y
        self.longitud_tramo       = longitud_tramo
        self.velocidad_nominal    = velocidad_nominal
        self.velocidad_porcentaje = velocidad_porcentaje
        self.ruido_lateral        = ruido_lateral
        self.porcentaje_patinaje  = random.uniform(0.0, 5.0)
        self.motor_activo: bool   = False

    def actualizar_motor(self, segundo_en_ciclo: int, duracion_ciclo: int = 60):
        """Activa o detiene el motor según el segundo actual dentro del ciclo de 60 s."""
        tiempo_activo     = self.velocidad_porcentaje / 100.0 * duracion_ciclo
        self.motor_activo = segundo_en_ciclo < tiempo_activo

    def avanzar(self, segundos: float, direccion: int = 1, rumbo: float = 0.0) -> float:
        """Avanza si el motor está activo. Devuelve los metros recorridos."""
        if not self.motor_activo:
            return 0.0

        factor_patinaje = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros = self.velocidad_nominal * (segundos / 60.0) * factor_patinaje

        self.posicion_x += math.sin(rumbo) * metros * direccion
        self.posicion_y += math.cos(rumbo) * metros * direccion

        if self.ruido_lateral > 0.0:
            ruido = random.gauss(0.0, self.ruido_lateral * metros)
            self.posicion_x += math.cos(rumbo) * ruido
            self.posicion_y -= math.sin(rumbo) * ruido

        return metros


class TramoIntermedio:
    """
    Sección intermedia del lineal.
    Sigue la diagonal Cart→End activando su motor cuando se retrasa respecto al objetivo.
    Su factor de velocidad es 1.5 por defecto
    """

    FACTOR_VELOCIDAD_NORMAL = 1.5   # el motor intermedio avanza ×1.5 sobre la velocidad nominal
    UMBRAL_ARRANQUE         = 0.10  # metros de retraso para activar el motor
    UMBRAL_ADELANTO         = 0.10  # metros de adelanto para detener el motor

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float,
                 velocidad_nominal: float = 3.0,
                 factor_velocidad: float = FACTOR_VELOCIDAD_NORMAL):

        self.posicion_x          = posicion_x
        self.posicion_y          = posicion_y
        self.longitud_tramo      = longitud_tramo
        self.velocidad_nominal   = velocidad_nominal
        self.factor_velocidad    = factor_velocidad
        self.porcentaje_patinaje = random.uniform(0.0, 5.0)
        self.motor_activo: bool  = False

    def seguir(self, objetivo_x: float, objetivo_y: float,
               segundos: float, direccion: int = 1,
               pivot_x: float = None, pivot_y: float = None,
               rumbo: float = 0.0) -> float:
        """
        Sigue el objetivo sobre la diagonal Cart→End.
        Activa el motor si está retrasada; lo detiene si está adelantada.
        Si se pasa pivot_x/pivot_y el movimiento es en arco; si no, en línea recta.
        """
        dx = objetivo_x - self.posicion_x
        dy = objetivo_y - self.posicion_y

        avance_x = math.sin(rumbo)
        avance_y = math.cos(rumbo)
        # + = está retrasada respecto al objetivo  ·  - = está adelantada
        desviacion = (dx * avance_x + dy * avance_y) * direccion

        if desviacion >= self.UMBRAL_ARRANQUE:
            self.motor_activo = True
        elif desviacion <= -self.UMBRAL_ADELANTO:
            self.motor_activo = False

        if not self.motor_activo:
            return 0.0

        factor_patinaje = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros = self.velocidad_nominal * self.factor_velocidad * (segundos / 60.0) * factor_patinaje

        if pivot_x is not None and pivot_y is not None:
            # La dirección del arco depende de si la sección está a la derecha o izquierda del pivot
            derecha_x  = math.cos(rumbo)
            derecha_y  = -math.sin(rumbo)
            dot        = (self.posicion_x - pivot_x) * derecha_x + (self.posicion_y - pivot_y) * derecha_y
            signo_arco = 1 if dot > 0 else -1
            self.posicion_x, self.posicion_y = avanzar_en_circunferencia(
                pivot_x, pivot_y, self.longitud_tramo,
                self.posicion_x, self.posicion_y,
                metros * direccion * signo_arco,
            )
        else:
            self.posicion_x += avance_x * metros * direccion
            self.posicion_y += avance_y * metros * direccion

        return metros


class FreeStandingSpan:
    """
    Tramo central rígido (Free Standing Span).
    Gestiona dos secciones con motores propios:
      - izquierda: ×1.5 (mismo ritmo que el resto de tramos intermedios)
      - derecha:   ×2.0 — motor rápido, esencial para el giro gradual en slow_down
    Tras cada tick recoloca ambas secciones manteniéndolas rígidamente sobre el eje Cart→End.
    """

    FACTOR_MOTOR_IZQUIERDO = 1.5
    FACTOR_MOTOR_RAPIDO    = 2.0  # marca el ritmo en slow_down para girar sin pivotar
    TOLERANCIA_ALINEACION  = 0.05  # metros

    def __init__(self, tramo_izq: "TramoIntermedio", tramo_der: "TramoIntermedio", longitud: float):
        self.tramo_izq = tramo_izq
        self.tramo_der = tramo_der
        self.longitud  = longitud
        self._angulo_referencia_grados: float = 0.0

        tramo_izq.factor_velocidad = self.FACTOR_MOTOR_IZQUIERDO
        tramo_der.factor_velocidad = self.FACTOR_MOTOR_RAPIDO

    @property
    def angulo_referencia_grados(self) -> float:
        return self._angulo_referencia_grados

    @property
    def esta_alineado(self) -> bool:
        dx = self.tramo_der.posicion_x - self.tramo_izq.posicion_x
        dy = self.tramo_der.posicion_y - self.tramo_izq.posicion_y
        return abs(math.hypot(dx, dy) - self.longitud) < self.TOLERANCIA_ALINEACION

    def actualizar(self, cart_x: float, cart_y: float, end_x: float, end_y: float) -> float:
        """
        Recoloca los tramos acompañantes simétricos al centro FSS, paralelos al eje Cart→End.
        Devuelve el ángulo de referencia en grados.
        """
        cx = (self.tramo_izq.posicion_x + self.tramo_der.posicion_x) / 2.0
        cy = (self.tramo_izq.posicion_y + self.tramo_der.posicion_y) / 2.0

        dx            = end_x - cart_x
        dy            = end_y - cart_y
        longitud_eje  = math.hypot(dx, dy)

        if longitud_eje < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux = dx / longitud_eje
            uy = dy / longitud_eje

        media = self.longitud / 2.0
        self.tramo_izq.posicion_x = cx - ux * media
        self.tramo_izq.posicion_y = cy - uy * media
        self.tramo_der.posicion_x = cx + ux * media
        self.tramo_der.posicion_y = cy + uy * media

        self._angulo_referencia_grados = math.degrees(math.atan2(dy, dx))
        return self._angulo_referencia_grados


def _aplicar_interferencia_gps(lat_e7: int, lon_e7: int, interferencia_mm: float, lat_origen: float) -> tuple:
    """Aplica error aleatorio RTK (±0–15 mm) a las coordenadas enteras ×10⁷."""
    if interferencia_mm == 0.0:
        return lat_e7, lon_e7
    mpg_lon   = METROS_POR_GRADO_LAT * math.cos(math.radians(lat_origen))
    dev_lat_m = random.uniform(-interferencia_mm, interferencia_mm) / 1000.0
    dev_lon_m = random.uniform(-interferencia_mm, interferencia_mm) / 1000.0
    return (
        lat_e7 + round(dev_lat_m / METROS_POR_GRADO_LAT * 1e7),
        lon_e7 + round(dev_lon_m / mpg_lon * 1e7),
    )


class ReferenciaGPS:
    """
    Sensor GPS montado en un TramoIntermedio.
    Convierte la posición cartesiana del tramo a lat/lon y la emite por puerto serie cada segundo:
    "LAT:<lat_e7>,LON:<lon_e7>\\n"
    """

    def __init__(self, tramo: TramoIntermedio,
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str = None,
                 baudrate: int = 9600,
                 verbose_consola: bool = False):

        self.tramo            = tramo
        self.lat_origen       = lat_origen
        self.lon_origen       = lon_origen
        self.puerto_serial    = puerto_serial
        self.baudrate         = baudrate
        self.verbose_consola  = verbose_consola
        self.interferencia_gps_mm: float = 0.0

        self._hilo   = None
        self._activo = False

    @property
    def latitud(self) -> float:
        return self.lat_origen + (self.tramo.posicion_y / METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        mpg_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen))
        return self.lon_origen + (self.tramo.posicion_x / mpg_lon)

    @property
    def lat_e7(self) -> int:
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        return round(self.longitud * 1e7)

    def iniciar_transmision_background(self):
        """Lanza hilo que emite coordenadas 1 vez/segundo por USB o consola."""
        if self.puerto_serial is None and not self.verbose_consola:
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo   = threading.Thread(target=self._bucle_transmision, daemon=True)
        self._hilo.start()

    def detener_transmision_background(self):
        self._activo = False

    def _bucle_transmision(self):
        conexion = None
        if self.puerto_serial is not None:
            try:
                conexion = _serial_module.Serial(
                    self.puerto_serial, self.baudrate,
                    timeout=1, write_timeout=1,
                    rtscts=False, dsrdtr=False, xonxoff=False,
                )
            except Exception as e:
                print(f"ReferenciaGPS: error abriendo {self.puerto_serial}: {e}")
                return

        while self._activo:
            lat_em, lon_em = _aplicar_interferencia_gps(
                self.lat_e7, self.lon_e7,
                self.interferencia_gps_mm, self.lat_origen,
            )
            msg = f"LAT:{lat_em},LON:{lon_em}\n"
            if conexion is not None:
                try:
                    conexion.write(msg.encode("utf-8"))
                    conexion.flush()
                except Exception as e:
                    print(f"ReferenciaGPS: error en transmisión: {e}")
                    break
            if self.verbose_consola:
                print(f"GPS {msg.strip()}  (real: {self.latitud:.7f}°, {self.longitud:.7f}°)")
            _time.sleep(1.0)

        if conexion is not None:
            conexion.close()


class Centro:
    """Punto central de referencia para pívot y corner (uso futuro)."""

    def __init__(self, posicion_x: float = 0.0, posicion_y: float = 0.0):
        self.posicion_x = posicion_x
        self.posicion_y = posicion_y


class TramoCorner:
    """Sección de esquina para lineal tipo corner (uso futuro)."""

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float,
                 angulo_giro: float = 0.0):
        self.posicion_x     = posicion_x
        self.posicion_y     = posicion_y
        self.longitud_tramo = longitud_tramo
        self.angulo_giro    = angulo_giro


class CajaInterfaz:
    """
    Comunicación bidireccional con la caja de interfaz Arduino (115 200 baud).
    PC → Arduino (1 Hz): "Lat {lat_e7} Lon {lon_e7} Carr {carr}\\n"
    Arduino → PC:
        SLOW_DOWN_CART_ON/OFF  ·  SLOW_DOWN_END_TOWER_ON/OFF
        SAFETY_OK / SAFETY_FAIL  ·  GPS_OK / GPS_FAIL
    carr: calidad RTK  0 = sin RTK  1 = float  2 = FIX
    """

    BAUDRATE = 115_200

    def __init__(self, tramo: TramoIntermedio,
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str,
                 carr: int = 2):

        self.tramo         = tramo
        self.lat_origen    = lat_origen
        self.lon_origen    = lon_origen
        self.puerto_serial = puerto_serial
        self.carr          = carr

        self.slow_down_cart:      bool  = False
        self.slow_down_end_tower: bool  = False
        self.safety_ok:           bool  = True
        self.gps_ok:              bool  = True
        self.ultimo_mensaje:      str   = ""
        self.interferencia_gps_mm: float = 0.0

        self._activo = False
        self._hilo   = None

    @property
    def latitud(self) -> float:
        return self.lat_origen + (self.tramo.posicion_y / METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        mpg_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen))
        return self.lon_origen + (self.tramo.posicion_x / mpg_lon)

    @property
    def lat_e7(self) -> int:
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        return round(self.longitud * 1e7)

    def iniciar(self):
        """Abre el puerto serie y lanza el hilo de comunicación bidireccional."""
        if not _SERIAL_DISPONIBLE:
            print("Pyserial no instalado; ejecuta: pip install pyserial")
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo   = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        self._activo = False

    def _bucle(self):
        try:
            ser = _serial_module.Serial(
                self.puerto_serial, self.BAUDRATE,
                timeout=0.1, write_timeout=1,
                rtscts=False, dsrdtr=False, xonxoff=False,
            )
        except Exception as e:
            print(f"CajaInterfaz: no se pudo abrir {self.puerto_serial}: {e}")
            return

        ultimo_envio = 0.0
        while self._activo:
            ahora = _time.time()
            if ahora - ultimo_envio >= 1.0:
                lat_em, lon_em = _aplicar_interferencia_gps(
                    self.lat_e7, self.lon_e7,
                    self.interferencia_gps_mm, self.lat_origen,
                )
                trama = f"Lat {lat_em} Lon {lon_em} Carr {self.carr}\n"
                try:
                    ser.write(trama.encode("utf-8"))
                    ser.flush()
                    ultimo_envio = ahora
                except Exception as e:
                    print(f"CajaInterfaz: error enviando GPS: {e}")
                    break

            try:
                linea = ser.readline().decode("utf-8", errors="replace").strip()
                if linea:
                    self.ultimo_mensaje = linea
                    self._procesar(linea)
            except Exception as e:
                if self._activo:
                    print(f"CajaInterfaz: error leyendo: {e}")
                break

        ser.close()

    def _procesar(self, msg: str):
        """Actualiza estados internos según el mensaje recibido del Arduino."""
        if   msg == "SLOW_DOWN_CART_ON":       self.slow_down_cart      = True
        elif msg == "SLOW_DOWN_CART_OFF":      self.slow_down_cart      = False
        elif msg == "SLOW_DOWN_END_TOWER_ON":  self.slow_down_end_tower = True
        elif msg == "SLOW_DOWN_END_TOWER_OFF": self.slow_down_end_tower = False
        elif msg == "SAFETY_OK":               self.safety_ok           = True
        elif msg == "SAFETY_FAIL":             self.safety_ok           = False
        elif msg == "GPS_OK":                  self.gps_ok              = True
        elif msg == "GPS_FAIL":                self.gps_ok              = False
