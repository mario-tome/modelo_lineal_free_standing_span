import math
from .componentes import (
    TramoFinal,
    TramoIntermedio,
    FreeStandingSpan,
    AntenaGPS,
    CajaInterfaz,
)

class Lineal:

    DURACION_CICLO = 60 # segundos por ciclo de duty cycle

    def __init__(self,
                 numero_tramos: int = 5,
                 longitud_tramo: float = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float = 3.0,
                 ruido_lateral: float = 0.0):

        if numero_tramos < 3:
            raise ValueError("El lineal FSS necesita mínimo 3 tramos")

        self.numero_tramos = numero_tramos
        self.longitud_tramo = longitud_tramo
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal = velocidad_nominal

        self.indice_fss_izq = numero_tramos // 2 # tramo izquierdo del FSS
        self.indice_fss_der = numero_tramos // 2 + 1 # tramo derecho del FSS (motor rápido)

        # TramoFinal (Cart) + TramoIntermedio × N-1 + TramoFinal (End-tower)
        self.secciones: list = []

        self.secciones.append(TramoFinal(
            posicion_x=0.0, posicion_y=0.0,
            longitud_tramo=longitud_tramo,
            velocidad_nominal=velocidad_nominal,
            velocidad_porcentaje=velocidad_porcentaje,
            ruido_lateral=ruido_lateral,
        ))

        for i in range(1, numero_tramos):
            self.secciones.append(TramoIntermedio(
                posicion_x=longitud_tramo * i,
                posicion_y=0.0,
                longitud_tramo=longitud_tramo,
                velocidad_nominal=velocidad_nominal,
            ))

        self.secciones.append(TramoFinal(
            posicion_x=longitud_tramo * numero_tramos,
            posicion_y=0.0,
            longitud_tramo=longitud_tramo,
            velocidad_nominal=velocidad_nominal,
            velocidad_porcentaje=velocidad_porcentaje,
            ruido_lateral=ruido_lateral,
        ))

        self.fss = FreeStandingSpan(
            tramo_izq=self.secciones[self.indice_fss_izq],
            tramo_der=self.secciones[self.indice_fss_der],
            longitud=longitud_tramo,
        )

        self.tramo_cart = self.secciones[0] # TramoFinal Cart (izquierda)
        self.tramo_end = self.secciones[-1] # TramoFinal End-tower (derecha)
        self.torre_rapida = self.secciones[self.indice_fss_der] # TramoIntermedio con motor rápido

        self.tiempo_total_segundos = 0
        self.ciclo_actual = 0
        self._segundo_en_ciclo = 0
        self._en_marcha = False

        self._segundos_motor_rapido_on = 0
        self.motor_rapido_pct_on = 0.0

        self.direccion: int = 1  # 1 = adelante, -1 = atrás
        self.slow_down_cart: bool = False
        self.slow_down_end_tower: bool = False

        self.caja_interfaz: CajaInterfaz | None = None

        self._angulo_referencia_grados: float = 0.0  # atan2(dy, dx) del eje Cart - End Tower

    @property
    def posicion_norte(self) -> float:
        return sum(s.posicion_y for s in self.secciones) / len(self.secciones)

    @property
    def longitud_total(self) -> float:
        return self.numero_tramos * self.longitud_tramo

    @property
    def esta_alineado(self) -> bool:
        return all(self.get_span_alineado(j) for j in range(self.numero_tramos))

    @property
    def en_marcha_atras(self) -> bool:
        return self.direccion == -1

    @property
    def rumbo(self) -> float:
        """Rumbo del lineal en radianes desde el norte (0 = norte, π/2 = este)"""
        dx = self.tramo_end.posicion_x - self.tramo_cart.posicion_x
        dy = self.tramo_end.posicion_y - self.tramo_cart.posicion_y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        return math.atan2(-dy, dx)

    def start(self):
        self._en_marcha = True

    def stop(self):
        self._en_marcha = False
        self.tramo_cart.motor_activo = False
        self.tramo_end.motor_activo = False

    def invertir_direccion(self):
        self.direccion *= -1

    def set_speed(self, velocidad_porcentaje: float):
        self.velocidad_porcentaje = max(0.0, min(100.0, velocidad_porcentaje))
        self.tramo_cart.velocidad_porcentaje = self.velocidad_porcentaje
        self.tramo_end.velocidad_porcentaje = self.velocidad_porcentaje

    def asignar_caja(self, indice_tramo: int,
                     metros_path: float,
                     metros_heading: float,
                     lat_origen: float,
                     lon_origen: float,
                     puerto_path: str,
                     puerto_heading: str,
                     carr: int = 2):
        """
        Configura la caja de guiado con los dos GPS en el tramo indicado
        metros_path / metros_heading: distancia desde el inicio del tramo donde va cada antena
        """
        if not (0 <= indice_tramo < self.numero_tramos):
            raise ValueError(f"indice_tramo debe estar entre 0 y {self.numero_tramos - 1}")
        inicio = self.secciones[indice_tramo]
        fin = self.secciones[indice_tramo + 1]
        self.caja_interfaz = CajaInterfaz(
            antena_path = AntenaGPS(inicio, fin, metros_path, lat_origen, lon_origen),
            antena_heading = AntenaGPS(inicio, fin, metros_heading, lat_origen, lon_origen),
            puerto_path = puerto_path,
            puerto_heading = puerto_heading,
            carr = carr,
        )

    def avanza(self, segundos: int = 1):
        """Avanza la simulación tick a tick (1 s por iteración interna)"""
        for _ in range(segundos):
            self.tiempo_total_segundos += 1
            self._segundo_en_ciclo = self.tiempo_total_segundos % self.DURACION_CICLO

            if self._segundo_en_ciclo == 0:
                self.ciclo_actual += 1
                self.motor_rapido_pct_on = (
                    self._segundos_motor_rapido_on / self.DURACION_CICLO * 100.0
                )
                self._segundos_motor_rapido_on = 0

            if not self._en_marcha:
                continue

            rumbo = self.rumbo
            ralentizar_cart = self.slow_down_cart
            ralentizar_end = self.slow_down_end_tower

            # Actualizar motor de cada guía según su duty cycle
            self.tramo_cart.actualizar_motor(self._segundo_en_ciclo, self.DURACION_CICLO)
            self.tramo_end.actualizar_motor(self._segundo_en_ciclo, self.DURACION_CICLO)

            # En slow_down, la guía ralentizada copia el ritmo del motor rápido en vez del duty cycle
            if ralentizar_cart and not ralentizar_end:
                self.tramo_cart.motor_activo = self.torre_rapida.motor_activo
                self.tramo_cart.avanzar(1, self.direccion, rumbo)
                self.tramo_end.avanzar(1, self.direccion, rumbo)

            elif ralentizar_end and not ralentizar_cart:
                self.tramo_end.motor_activo = self.torre_rapida.motor_activo
                self.tramo_end.avanzar(1, self.direccion, rumbo)
                self.tramo_cart.avanzar(1, self.direccion, rumbo)

            else:
                self.tramo_cart.avanzar(1, self.direccion, rumbo)
                self.tramo_end.avanzar(1, self.direccion, rumbo)

            x_cart = self.tramo_cart.posicion_x
            y_cart = self.tramo_cart.posicion_y
            x_end = self.tramo_end.posicion_x
            y_end = self.tramo_end.posicion_y
            numero_intervalos = len(self.secciones) - 1

            # CASCADA IZQUIERDA: cada sección sigue a la anterior (Cart - FSS izq)
            for i in range(1, self.indice_fss_izq + 1):
                pivote = self.secciones[i - 1]
                x_obj = x_cart + (x_end - x_cart) * i / numero_intervalos
                y_obj = y_cart + (y_end - y_cart) * i / numero_intervalos
                self.secciones[i].seguir(
                    x_obj, y_obj, 1, self.direccion,
                    pivote.posicion_x, pivote.posicion_y, rumbo,
                )

            # CASCADA DERECHA: cada sección sigue a la siguiente (End-tower - FSS der)
            for i in range(numero_intervalos - 1, self.indice_fss_der - 1, -1):
                pivote = self.secciones[i + 1]
                x_obj = x_cart + (x_end - x_cart) * i / numero_intervalos
                y_obj = y_cart + (y_end - y_cart) * i / numero_intervalos
                self.secciones[i].seguir(
                    x_obj, y_obj, 1, self.direccion,
                    pivote.posicion_x, pivote.posicion_y, rumbo,
                )

            # FSS: corrige posición de sus tramos flanqueantes al eje Cart - End Tower
            self._angulo_referencia_grados = self.fss.actualizar(x_cart, y_cart, x_end, y_end)

            if self.torre_rapida.motor_activo:
                self._segundos_motor_rapido_on += 1

    def get_span_info(self, indice: int) -> dict:
        """Información geométrica y de alineación del tramo entre secciones[indice] y secciones[indice+1]."""
        izq = self.secciones[indice]
        der = self.secciones[indice + 1]
        dx = der.posicion_x - izq.posicion_x
        dy = der.posicion_y - izq.posicion_y

        distancia_horizontal = abs(dx)
        longitud_real = math.hypot(dx, dy)

        angulo_absoluto = math.degrees(math.atan2(dy, distancia_horizontal)) if distancia_horizontal > 0 else 0.0
        angulo_referencia = self._angulo_referencia_grados
        angulo_relativo = (angulo_absoluto - angulo_referencia + 180) % 360 - 180

        if distancia_horizontal > 0:
            dy_esperado = math.tan(math.radians(angulo_referencia)) * distancia_horizontal
            desv_relativa = dy - dy_esperado
        else:
            desv_relativa = dy

        return {
            "x0": izq.posicion_x, "y0": izq.posicion_y,
            "x1": der.posicion_x, "y1": der.posicion_y,
            "longitud": longitud_real,
            "desviacion_norte": dy,
            "desviacion_norte_relativa": desv_relativa,
            "angulo_grados": angulo_absoluto,
            "angulo_relativo_grados": angulo_relativo,
            "esta_alineado": abs(desv_relativa) < FreeStandingSpan.TOLERANCIA_ALINEACION,
            "es_rigido": (indice == self.indice_fss_izq),
        }

    def get_span_alineado(self, indice: int) -> bool:
        return self.get_span_info(indice)["esta_alineado"]

    def _tiempo_formateado(self) -> str:
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"

    def _validar_seccion_intermedia(self, indice_seccion: int) -> TramoIntermedio:
        """Valida que el índice apunte a un TramoIntermedio y lo devuelve"""
        if not (1 <= indice_seccion <= self.numero_tramos - 1):
            raise ValueError(f"indice_seccion debe estar entre 1 y {self.numero_tramos - 1}")
        seccion = self.secciones[indice_seccion]
        if not isinstance(seccion, TramoIntermedio):
            raise ValueError(f"La sección {indice_seccion} no es un TramoIntermedio")
        return seccion
