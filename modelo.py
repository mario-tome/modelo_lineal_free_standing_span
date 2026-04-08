import math, random

try:
    import serial as _serial_module
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False


#  CONTACTOR
#  Conecta y desconecta el motor de una torre
#  Hay DOS formas de usarlo según el tipo de torre:
#
#  1. duty cycle (torres guía): el motor arranca y para en ciclos de 60 s para controlar la velocidad media
#  2. alineación (torres intermedias, no hay duty cycle): indicador de alineación: ON cuando la torre está desalineada con su líder, OFF cuando está alineada
class Contactor:

    CERRADO = "CERRADO"   # Motor ON
    ABIERTO  = "ABIERTO"  # Motor OFF

    def __init__(self, velocidad_porcentaje: float = 0.0):
        """
        velocidad_porcentaje : duty cycle en % (solo relevante en torres guía)
        """
        self.duty_cycle = velocidad_porcentaje / 100.0
        self.estado     = self.ABIERTO

    # Uso en torres guía
    def actualizar_duty_cycle(self, segundo_en_ciclo: int, duracion_ciclo: int = 60):
        """Cierra o abre el contactor según el segundo actual dentro del ciclo (duty cycle)"""
        tiempo_activo = self.duty_cycle * duracion_ciclo
        self.estado   = self.CERRADO if segundo_en_ciclo < tiempo_activo else self.ABIERTO

    # Uso en torres intermedias
    def cerrar(self):
        """Motor ON: torre desalineada, activando recuperación de posición"""
        self.estado = self.CERRADO

    def abrir(self):
        """Motor OFF: torre alineada con su líder"""
        self.estado = self.ABIERTO

    @property
    def esta_cerrado(self) -> bool:
        return self.estado == self.CERRADO

    def __repr__(self):
        return f"Contactor(duty={self.duty_cycle * 100:.0f}%, estado={self.estado})"


#  TORRE (clase base)
#  Posición X : fija durante toda la simulación (posición a lo ancho)
#  Posición Y : avanza hacia el norte cuando el motor está en marcha
#
#  El patinaje simula irregularidades del terreno (cada torre tiene su propio valor)
class Torre:

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0):
        """
        posicion_x      : posición fija en el eje X (metros)
        posicion_y      : posición inicial en el eje Y / norte (metros)
        longitud_tramo  : longitud del tramo que parte de esta torre (metros)
        velocidad_nominal: velocidad de avance cuando el motor está ON (m/min)
        """
        self.posicion_x        = posicion_x
        self.posicion_y        = posicion_y
        self.longitud_tramo    = longitud_tramo
        self.velocidad_nominal = velocidad_nominal
        self.porcentaje_patinaje = random.uniform(0.0, 5.0)  # imperfección única por torre

    def avanzar(self, segundos: float) -> float:
        """
        Mueve la torre hacia el norte durante 'segundos' a velocidad nominal
        El patinaje reduce ligeramente la velocidad según el terreno
        Devuelve los metros avanzados
        """
        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = self.velocidad_nominal * (segundos / 60.0) * factor_patinaje
        self.posicion_y += metros_avanzados
        return metros_avanzados

    @property
    def posicion(self) -> tuple:
        return (self.posicion_x, self.posicion_y)

    def __repr__(self):
        return f"{self.__class__.__name__}(x={self.posicion_x:.0f}m, y={self.posicion_y:.3f}m)"


#  TORRE_GUIA
#  Las dos torres de los extremos del lineal: izquierda (Cart) y derecha (Guía)
#
#  Son las únicas con contactor de DUTY CYCLE
#  El motor arranca y para en ciclos de 60 s: esto controla la velocidad media de avance de todo el lineal.
class Torre_Guia(Torre):

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 velocidad_porcentaje: float = 50.0):
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor = Contactor(velocidad_porcentaje)

    def avanzar(self, segundos: float) -> float:
        """Avanza a velocidad nominal únicamente cuando el contactor está CERRADO"""
        if self.contactor.esta_cerrado:
            return super().avanzar(segundos)
        return 0.0

    def __repr__(self):
        return (f"Torre_Guia(x={self.posicion_x:.0f}m, y={self.posicion_y:.3f}m,"
                f" contactor={self.contactor.estado})")


#  TORRE_INTERMEDIA
#  Su contactor NO tiene duty cycle: es un indicador de alineación ON/OFF.
#    - ABIERTO (OFF) → torre alineada con su líder inmediato, motor parado
#    - CERRADO (ON)  → torre desalineada, motor activo para recuperar posición
#
#  Su motor es más potente que el de las torres guía para recuperar posición rápido.
#
#  La torre en el extremo DERECHO del tramo rígido tiene el motor MÁS RÁPIDO de todo el lineal, 
#  porque al corregir la rotación del tramo rígido debe recorrer más distancia angular en el mismo tiempo
class Torre_Intermedia(Torre):

    FACTOR_SOBREVELOCIDAD        = 1.5   # motor intermedio normal: ×1.5 la velocidad nominal
    FACTOR_SOBREVELOCIDAD_RAPIDA = 2.0   # motor rápido (extremo der. tramo rígido): ×2.0
    UMBRAL_ARRANQUE              = 0.15  # desalineación mínima (metros) para activar el motor

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 es_motor_rapido: bool = False):
        """
        es_motor_rapido : True únicamente para la torre del extremo derecho del tramo rígido
        """
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor      = Contactor()   # contactor de alineación (sin duty cycle)
        self.es_motor_rapido = es_motor_rapido

    @property
    def factor_sobrevelocidad(self) -> float:
        return (self.FACTOR_SOBREVELOCIDAD_RAPIDA
                if self.es_motor_rapido
                else self.FACTOR_SOBREVELOCIDAD)

    def seguir(self, posicion_y_lider: float, segundos: float) -> float:
        """
        Avanza hacia la posición Y de su torre líder inmediata (la torre de su izquierda)

        El contactor (indicador de alineación) se gestiona aquí:
          diferencia < UMBRAL_ARRANQUE = contactor ABIERTO, motor parado
          diferencia ≥ UMBRAL_ARRANQUE = contactor CERRADO, motor activo a sobrevelocidad

        Nunca retrocede ni supera la posición del líder
        Devuelve los metros avanzados.
        """
        diferencia = posicion_y_lider - self.posicion_y

        if diferencia < self.UMBRAL_ARRANQUE:
            self.contactor.abrir()
            return 0.0

        self.contactor.cerrar()
        factor_patinaje       = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        velocidad_recuperacion = self.velocidad_nominal * self.factor_sobrevelocidad
        capacidad_por_segundo  = velocidad_recuperacion * (segundos / 60.0) * factor_patinaje
        metros_avanzados       = min(diferencia, capacidad_por_segundo)

        self.posicion_y += metros_avanzados
        return metros_avanzados

    def __repr__(self):
        rapido_txt = " [MOTOR RAPIDO]" if self.es_motor_rapido else ""
        return (f"Torre_Intermedia(x={self.posicion_x:.0f}m, y={self.posicion_y:.3f}m,"
                f" contactor={self.contactor.estado}){rapido_txt}")


#  TRAMO
#  Mide la inclinación respecto al eje horizontal
#    0°  : tramo perpendicular al avance → lineal perfectamente alineado
#    +X° : torre derecha más adelantada al norte
#    -X° → torre izquierda más adelantada al norte
#
#  es_rigido : True en el tramo central (Free Standing Span).
#              Este tramo no puede doblarse: sus dos torres se mueven como un bloque.
class Tramo:

    TOLERANCIA_ALINEACION = 0.05  # diferencia máxima para considerarse alineado (metros)

    def __init__(self, torre_izquierda: Torre, torre_derecha: Torre,
                 es_rigido: bool = False):
        self.torre_izquierda = torre_izquierda
        self.torre_derecha   = torre_derecha
        self.es_rigido       = es_rigido

    @property
    def longitud_horizontal(self) -> float:
        """Distancia fija en X entre las dos torres del tramo (metros)"""
        return abs(self.torre_derecha.posicion_x - self.torre_izquierda.posicion_x)

    @property
    def desviacion_norte(self) -> float:
        """
        Diferencia en Y entre torre derecha e izquierda
          0.0 → alineado
          > 0 → torre derecha más adelantada
          < 0 → torre izquierda más adelantada
        """
        return self.torre_derecha.posicion_y - self.torre_izquierda.posicion_y

    @property
    def angulo_grados(self) -> float:
        """Ángulo de inclinación del tramo respecto al eje horizontal"""
        if self.longitud_horizontal == 0:
            return 0.0
        return math.degrees(math.atan2(self.desviacion_norte, self.longitud_horizontal))

    @property
    def esta_alineado(self) -> bool:
        """True si la desviación está dentro de la tolerancia (5 cm)"""
        return abs(self.desviacion_norte) < self.TOLERANCIA_ALINEACION

    def __repr__(self):
        rigido_txt = " [RIGIDO]" if self.es_rigido else ""
        return (f"Tramo(x={self.torre_izquierda.posicion_x:.0f}m"
                f"->{self.torre_derecha.posicion_x:.0f}m,"
                f" desv={self.desviacion_norte:+.3f}m,"
                f" angulo={self.angulo_grados:+.3f}grd){rigido_txt}")


#  GPS
#  Unidad GPS asignada a una Torre_Intermedia.
#
#  Convierte la posición X/Y del modelo (metros) a coordenadas reales lat/lon
#  usando el punto de origen del campo (X=0, Y=0 = posición inicial del Cart)
#  como referencia geográfica.
#
#  Las coordenadas se emiten en formato entero ×10⁷ (estándar hardware GPS):
#    latitud  40.1234567° → 401234567
#    longitud -3.9876543° → -39876543
#
#  La transmisión se realiza cada segundo de simulación a través de puerto USB-serie.
#  Si no hay puerto configurado, los datos se imprimen en consola (modo simulación).
class GPS:

    # 1 grado de latitud ≈ 111 320 m en cualquier punto del globo
    _METROS_POR_GRADO_LAT = 111_320.0

    def __init__(self,
                 torre: "Torre_Intermedia",
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str = None,
                 baudrate: int = 9600):
        """
        torre         : Torre_Intermedia a la que está físicamente fijado el GPS
        lat_origen    : latitud  del punto X=0, Y=0 del lineal (grados decimales)
                        → coordenada GPS real de donde está el Cart al iniciar
        lon_origen    : longitud del punto X=0, Y=0 del lineal (grados decimales)
        puerto_serial : nombre del puerto USB-serie (ej. 'COM3', '/dev/ttyUSB0')
                        None = solo consola (modo simulación sin hardware)
        baudrate      : velocidad del puerto serie (debe coincidir con el receptor)
        """
        self.torre         = torre
        self.lat_origen    = lat_origen
        self.lon_origen    = lon_origen
        self.puerto_serial = puerto_serial
        self.baudrate      = baudrate
        self._conexion     = None   # objeto serial; se abre al primer uso

    # Conversión de coordenadas  X/Y (metros) → lat/lon (grados)
    @property
    def latitud(self) -> float:
        """Latitud actual de la torre en grados decimales"""
        return self.lat_origen + (self.torre.posicion_y / self._METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        """Longitud actual de la torre en grados decimales"""
        metros_por_grado_lon = (self._METROS_POR_GRADO_LAT
                                * math.cos(math.radians(self.lat_origen)))
        return self.lon_origen + (self.torre.posicion_x / metros_por_grado_lon)

    @property
    def lat_e7(self) -> int:
        """Latitud en formato entero ×10⁷ (para hardware GPS)"""
        return int(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        """Longitud en formato entero ×10⁷ (para hardware GPS)"""
        return int(self.longitud * 1e7)

    # Comunicación serie
    def _abrir_puerto(self) -> bool:
        """Intenta abrir el puerto serie. Devuelve True si está listo."""
        if self.puerto_serial is None:
            return False
        if not _SERIAL_DISPONIBLE:
            print("[GPS] pyserial no instalado. Ejecuta: pip install pyserial")
            return False
        try:
            if self._conexion is None or not self._conexion.is_open:
                self._conexion = _serial_module.Serial(
                    self.puerto_serial, self.baudrate, timeout=1
                )
            return True
        except Exception as e:
            print(f"[GPS] Error abriendo {self.puerto_serial}: {e}")
            return False

    def cerrar_puerto(self):
        """Cierra el puerto serie si está abierto."""
        if self._conexion and self._conexion.is_open:
            self._conexion.close()

    def transmitir(self, verbose_consola: bool = True):
        """
        Envía la posición actual de la torre.
        Formato: LAT:<lat_e7>,LON:<lon_e7>\\n

        Si el puerto serie está disponible, transmite por USB siempre.
        En modo consola (sin hardware), imprime solo si verbose_consola=True.
        """
        mensaje = f"LAT:{self.lat_e7},LON:{self.lon_e7}\n"

        if self._abrir_puerto():
            try:
                self._conexion.write(mensaje.encode("utf-8"))
            except Exception as e:
                print(f"[GPS] Error al transmitir: {e}")
        elif verbose_consola:
            print(f"[GPS] {mensaje.strip()}"
                  f"  ({self.latitud:.7f}°, {self.longitud:.7f}°)")

    def __repr__(self):
        puerto_txt = self.puerto_serial if self.puerto_serial else "consola"
        return (f"GPS(torre_x={self.torre.posicion_x:.0f}m,"
                f" lat={self.latitud:.7f}°, lon={self.longitud:.7f}°,"
                f" puerto={puerto_txt})")


#  LINEAL - Free Standing Span
#  Torres Guía (extremos)
#    - Tienen contactor de duty cycle: marcan el ritmo de avance de todo el lineal
#    - Ambas guías tienen el mismo duty cycle y avanzan a la misma velocidad media
#
#  Torres Intermedias
#    - Contactor de alineación ON/OFF: se activa cuando la torre se queda atrás
#    - Motor más potente que las guías para recuperar posición
#    - La torre en el extremo derecho del tramo rígido tiene el motor más rápido de todos
#
#  Tramo Rígido (central)
#    - No se puede doblar: las torres de sus extremos se mueven como un bloque
#
#  El lineal comienza PARADO. Usar start() para ponerlo en marcha
class Lineal:
    """
    Uso básico:
        lineal = Lineal(numero_tramos=5, longitud_tramo=50, velocidad_porcentaje=50)
        lineal.start()
        lineal.avanza(60)
        lineal.estado()
    """

    DURACION_CICLO = 60  # segundos por ciclo de duty cycle de las torres guía

    def __init__(self,
                 numero_tramos: int        = 5,
                 longitud_tramo: float     = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float  = 3.0):
        """
        numero_tramos        : número de tramos del lineal (mínimo 3)
                               Torres totales = numero_tramos + 1
                               1 guía izquierda + (numero_tramos - 1) intermedias + 1 guía derecha

        longitud_tramo       : longitud de cada tramo en metros

        velocidad_porcentaje : duty cycle de las torres guía en %
                               % del tiempo que el motor de las guías está ON en cada ciclo de 60 s
                               Velocidad media = velocidad_nominal × (velocidad_porcentaje / 100)

        velocidad_nominal    : velocidad de avance de cualquier motor cuando está ON (m/min)
        """
        if numero_tramos < 3:
            raise ValueError(
                "El lineal Free Standing Span necesita mínimo 3 tramos"
            )

        self.numero_tramos        = numero_tramos
        self.longitud_tramo       = longitud_tramo
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal    = velocidad_nominal

        # Tramo rígido: el tramo central del lineal
        self.indice_tramo_rigido = numero_tramos // 2

        # Torre más rápida: extremo DERECHO del tramo rígido
        self.indice_torre_motor_rapido = self.indice_tramo_rigido + 1

        # Crear torres
        # Índice 0             : Torre Guía izquierda (Cart)
        # Índices 1..N-1       : Torres Intermedias
        # Índice N             : Torre Guía derecha
        self.torres = []

        self.torres.append(Torre_Guia(
            posicion_x           = 0.0,
            posicion_y           = 0.0,
            longitud_tramo       = longitud_tramo,
            velocidad_nominal    = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje
        ))

        for i in range(1, numero_tramos):
            es_rapida = (i == self.indice_torre_motor_rapido)
            self.torres.append(Torre_Intermedia(
                posicion_x        = longitud_tramo * i,
                posicion_y        = 0.0,
                longitud_tramo    = longitud_tramo,
                velocidad_nominal = velocidad_nominal,
                es_motor_rapido   = es_rapida
            ))

        self.torres.append(Torre_Guia(
            posicion_x           = longitud_tramo * numero_tramos,
            posicion_y           = 0.0,
            longitud_tramo       = longitud_tramo,
            velocidad_nominal    = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje
        ))

        # Crear tramos
        self.tramos = []
        for i in range(numero_tramos):
            es_rigido = (i == self.indice_tramo_rigido)
            self.tramos.append(Tramo(self.torres[i], self.torres[i + 1], es_rigido=es_rigido))

        # Accesos directos
        self.guia_izquierda = self.torres[0]    # Cart (extremo izquierdo)
        self.guia_derecha   = self.torres[-1]   # Guía (extremo derecho)

        # Contadores de simulación
        self.tiempo_total_segundos = 0
        self.ciclo_actual          = 0
        self._segundo_en_ciclo     = 0
        self._en_marcha            = False   # el lineal comienza PARADO

        # GPS (se asigna después con asignar_gps())
        self.gps: GPS | None = None


    # GPS
    def asignar_gps(self,
                    indice_torre: int,
                    lat_origen: float,
                    lon_origen: float,
                    puerto_serial: str = None,
                    baudrate: int = 9600):
        """
        Asigna una unidad GPS a una torre intermedia del lineal.

        indice_torre  : índice de la torre intermedia (entre 1 y numero_tramos-1 inclusive)
        lat_origen    : latitud  real del punto X=0, Y=0 del lineal (grados decimales)
        lon_origen    : longitud real del punto X=0, Y=0 del lineal (grados decimales)
        puerto_serial : puerto USB-serie (ej. 'COM3'). None = solo consola
        baudrate      : velocidad del puerto serie

        Ejemplo:
            lineal.asignar_gps(indice_torre=2,
                               lat_origen=40.4168,
                               lon_origen=-3.7038,
                               puerto_serial='COM3')
        """
        if not (1 <= indice_torre <= self.numero_tramos - 1):
            raise ValueError(
                f"indice_torre debe estar entre 1 y {self.numero_tramos - 1} "
                f"(solo torres intermedias)"
            )
        torre = self.torres[indice_torre]
        if not isinstance(torre, Torre_Intermedia):
            raise ValueError(f"La torre {indice_torre} no es una Torre_Intermedia")

        self.gps = GPS(torre, lat_origen, lon_origen, puerto_serial, baudrate)

    # Control del lineal
    def start(self):
        """Pone el lineal en marcha"""
        self._en_marcha = True

    def stop(self):
        """
        Detiene el lineal
        Las torres guía abren su contactor (motor OFF)
        El tiempo sigue corriendo pero ninguna torre avanza
        """
        self._en_marcha = False
        self.guia_izquierda.contactor.abrir()
        self.guia_derecha.contactor.abrir()

    def set_speed(self, velocidad_porcentaje: float):
        """Cambia el duty cycle de ambas torres guía en % durante la simulación"""
        self.velocidad_porcentaje = max(0.0, min(100.0, velocidad_porcentaje))
        dc = self.velocidad_porcentaje / 100.0
        self.guia_izquierda.contactor.duty_cycle = dc
        self.guia_derecha.contactor.duty_cycle   = dc


    def avanza(self, segundos: int = 1):
        for _ in range(segundos):
            self.tiempo_total_segundos += 1
            self._segundo_en_ciclo      = self.tiempo_total_segundos % self.DURACION_CICLO

            if self._segundo_en_ciclo == 0:
                self.ciclo_actual += 1

            if not self._en_marcha:
                continue  # el tiempo pasa pero las torres no se mueven

            # 1. Torres guía: actualizar contactor (duty cycle) y avanzar
            self.guia_izquierda.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)
            self.guia_derecha.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)
            self.guia_izquierda.avanzar(1)
            self.guia_derecha.avanzar(1)

            snapshot_y = [t.posicion_y for t in self.torres]
            k = self.indice_tramo_rigido          # índice torre borde izquierdo del tramo rígido
            N = len(self.torres) - 1              # índice guía derecha

            # 2. Cascada izquierda (izq → der): torres 1..k siguen a su vecina izquierda
            for i in range(1, k + 1):
                self.torres[i].seguir(snapshot_y[i - 1], 1)

            # 3. Cascada derecha (der → izq): torres k+1..N-1 siguen a su vecina derecha
            for i in range(N - 1, k, -1):
                self.torres[i].seguir(snapshot_y[i + 1], 1)

            # 4. GPS: emitir posición una vez por segundo de simulación
            # Con hardware (puerto serie): transmite siempre cada segundo
            # Sin hardware (consola):      imprime cada 30 s para no saturar la pantalla
            if self.gps is not None:
                verbose = (self.gps.puerto_serial is not None
                           or self.tiempo_total_segundos % 30 == 0)
                self.gps.transmitir(verbose_consola=verbose)


    # Propiedades de estado
    @property
    def posicion_norte(self) -> float:
        """Posición media del lineal en el eje norte (metros)"""
        return sum(t.posicion_y for t in self.torres) / len(self.torres)

    @property
    def longitud_total(self) -> float:
        """Longitud total del lineal de extremo a extremo (metros)"""
        return self.numero_tramos * self.longitud_tramo

    @property
    def esta_alineado(self) -> bool:
        """True si todos los tramos están dentro de la tolerancia de alineación (5 cm)"""
        return all(t.esta_alineado for t in self.tramos)


    def estado(self):
        """Imprime un resumen detallado del estado actual del lineal"""
        vel_media    = self.velocidad_nominal * (self.velocidad_porcentaje / 100.0)
        alineado_txt = "Correcto" if self.esta_alineado else "Corrigiendo desviacion..."
        estado_txt   = "EN MARCHA" if self._en_marcha else "PARADO"

        print()
        print(f"  Sistema de Riego Lineal / Free Standing Span ")
        print(f"  Estado               : {estado_txt}")
        print(f"  Tiempo transcurrido  : {self._tiempo_formateado()}   Ciclo #{self.ciclo_actual}")
        print()
        print(f"  Configuracion del lineal")
        print(f"    Tramos             : {self.numero_tramos}  (longitud total: {self.longitud_total:.0f} m)")
        print(f"    Torres             : {len(self.torres)}  "
              f"(guia izq + {self.numero_tramos - 1} intermedias + guia der)")
        print(f"    Tramo rigido       : Tramo {self.indice_tramo_rigido + 1} (tramo central)")
        print(f"    Motor nominal      : {self.velocidad_nominal:.2f} m/min  (cualquier motor cuando esta ON)")
        print(f"    Duty cycle guias   : {self.velocidad_porcentaje:.0f}%  "
              f"->  {vel_media:.2f} m/min velocidad media")
        print()
        print(f"  Posicion y alineacion")
        print(f"    Posicion norte     : {self.posicion_norte:.2f} m")
        print(f"    Alineacion         : {alineado_txt}")
        print()
        print("  Torres")
        for i, torre in enumerate(self.torres):
            if i == 0:
                etiqueta = "Guia Izq (Cart)  "
            elif i == len(self.torres) - 1:
                etiqueta = "Guia Der         "
            elif i == self.indice_torre_motor_rapido:
                etiqueta = f"Intermedia {i} [++] "  # [++] = motor mas rapido
            else:
                etiqueta = f"Intermedia {i}      "
            print(f"    [{etiqueta}]  {torre}")
        print()
        print("  Tramos  (desviacion = diferencia en Y entre torre der e izq del tramo)")
        for i, tramo in enumerate(self.tramos, 1):
            print(f"    [Tramo {i}]  {tramo}")
        print()
        if self.gps is not None:
            print("  GPS")
            print(f"    {self.gps}")
            print()

    def _tiempo_formateado(self) -> str:
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"

    def __repr__(self):
        return (f"Lineal(tramos={self.numero_tramos},"
                f" longitud_tramo={self.longitud_tramo}m,"
                f" duty={self.velocidad_porcentaje}%,"
                f" nominal={self.velocidad_nominal}m/min)")
