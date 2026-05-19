import math
from .componentes import (
    TramoFinal,
    TramoIntermedio,
    FreeStandingSpan,
    ReferenciaGPS,
    CajaInterfaz,
)


class Lineal:

    DURACION_CICLO = 60  # segundos por ciclo de duty cycle

    def __init__(self,
                 numero_tramos: int = 5,
                 longitud_tramo: float = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float = 3.0,
                 ruido_lateral: float = 0.0):

        if numero_tramos < 3:
            raise ValueError("El lineal FSS necesita mínimo 3 tramos")

        self.numero_tramos        = numero_tramos
        self.longitud_tramo       = longitud_tramo
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal    = velocidad_nominal

        self.indice_fss_izq = numero_tramos // 2      # tramo izquierdo del FSS
        self.indice_fss_der = numero_tramos // 2 + 1  # tramo derecho del FSS (motor rápido)

        # [TramoFinal Cart] + [TramoIntermedio × N-1] + [TramoFinal End-tower]
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
                # factor_velocidad lo asignará FreeStandingSpan al tramo derecho (×2)
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

        self.tramo_cart   = self.secciones[0]                   # TramoFinal Cart (izquierda)
        self.tramo_end    = self.secciones[-1]                  # TramoFinal End-tower (derecha)
        self.torre_rapida = self.secciones[self.indice_fss_der] # TramoIntermedio con motor ×2

        self.tiempo_total_segundos      = 0
        self.ciclo_actual               = 0
        self._segundo_en_ciclo          = 0
        self._en_marcha                 = False

        self._segundos_motor_rapido_on  = 0
        self.motor_rapido_pct_on        = 0.0

        self.direccion:           int  = 1      # 1 = adelante  ·  -1 = atrás
        self.slow_down_cart:      bool = False
        self.slow_down_end_tower: bool = False

        self.gps:           ReferenciaGPS | None = None
        self.caja_interfaz: CajaInterfaz  | None = None

        self._angulo_referencia: float = 0.0  # grados, atan2(dy, dx) del eje Cart→End

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
        """Rumbo del lineal en radianes desde el norte (0 = norte, π/2 = este)."""
        dx = self.tramo_end.posicion_x - self.tramo_cart.posicion_x
        dy = self.tramo_end.posicion_y - self.tramo_cart.posicion_y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        return math.atan2(-dy, dx)

    def start(self):
        self._en_marcha = True

    def stop(self):
        self._en_marcha              = False
        self.tramo_cart.motor_activo = False
        self.tramo_end.motor_activo  = False

    def invertir_direccion(self):
        self.direccion *= -1

    def set_speed(self, velocidad_porcentaje: float):
        self.velocidad_porcentaje            = max(0.0, min(100.0, velocidad_porcentaje))
        self.tramo_cart.velocidad_porcentaje = self.velocidad_porcentaje
        self.tramo_end.velocidad_porcentaje  = self.velocidad_porcentaje

    def asignar_gps(self, indice_seccion: int,
                    lat_origen: float, lon_origen: float,
                    puerto_serial: str = None,
                    baudrate: int = 9600,
                    verbose_consola: bool = False):
        if not (1 <= indice_seccion <= self.numero_tramos - 1):
            raise ValueError(f"indice_seccion debe estar entre 1 y {self.numero_tramos - 1}")
        sec = self.secciones[indice_seccion]
        if not isinstance(sec, TramoIntermedio):
            raise ValueError(f"La sección {indice_seccion} no es un TramoIntermedio")
        self.gps = ReferenciaGPS(sec, lat_origen, lon_origen, puerto_serial, baudrate, verbose_consola)

    def asignar_caja(self, indice_seccion: int,
                     lat_origen: float, lon_origen: float,
                     puerto_serial: str,
                     carr: int = 2):
        if not (1 <= indice_seccion <= self.numero_tramos - 1):
            raise ValueError(f"indice_seccion debe estar entre 1 y {self.numero_tramos - 1}")
        self.caja_interfaz = CajaInterfaz(
            tramo=self.secciones[indice_seccion],
            lat_origen=lat_origen,
            lon_origen=lon_origen,
            puerto_serial=puerto_serial,
            carr=carr,
        )

    def avanza(self, segundos: int = 1):
        """Avanza la simulación tick a tick (1 s por iteración interna)."""
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

            rumbo  = self.rumbo
            slow_c = self.slow_down_cart
            slow_e = self.slow_down_end_tower

            # Actualizar motor de cada guía según su duty cycle
            self.tramo_cart.actualizar_motor(self._segundo_en_ciclo, self.DURACION_CICLO)
            self.tramo_end.actualizar_motor(self._segundo_en_ciclo, self.DURACION_CICLO)

            # En slow_down, la guía ralentizada copia el ritmo del motor rápido en vez del duty cycle
            if slow_c and not slow_e:
                self.tramo_cart.motor_activo = self.torre_rapida.motor_activo
                self.tramo_cart.avanzar(1, self.direccion, rumbo)
                self.tramo_end.avanzar(1, self.direccion, rumbo)

            elif slow_e and not slow_c:
                self.tramo_end.motor_activo = self.torre_rapida.motor_activo
                self.tramo_end.avanzar(1, self.direccion, rumbo)
                self.tramo_cart.avanzar(1, self.direccion, rumbo)

            else:
                self.tramo_cart.avanzar(1, self.direccion, rumbo)
                self.tramo_end.avanzar(1, self.direccion, rumbo)

            x_cart = self.tramo_cart.posicion_x
            y_cart = self.tramo_cart.posicion_y
            x_end  = self.tramo_end.posicion_x
            y_end  = self.tramo_end.posicion_y
            N = len(self.secciones) - 1  # número de intervalos

            # Cascada izquierda: cada sección sigue a la anterior (Cart → FSS izq)
            for i in range(1, self.indice_fss_izq + 1):
                pivot = self.secciones[i - 1]
                x_obj = x_cart + (x_end - x_cart) * i / N
                y_obj = y_cart + (y_end - y_cart) * i / N
                self.secciones[i].seguir(
                    x_obj, y_obj, 1, self.direccion,
                    pivot.posicion_x, pivot.posicion_y, rumbo,
                )

            # Cascada derecha: cada sección sigue a la siguiente (End-tower → FSS der)
            for i in range(N - 1, self.indice_fss_der - 1, -1):
                pivot = self.secciones[i + 1]
                x_obj = x_cart + (x_end - x_cart) * i / N
                y_obj = y_cart + (y_end - y_cart) * i / N
                self.secciones[i].seguir(
                    x_obj, y_obj, 1, self.direccion,
                    pivot.posicion_x, pivot.posicion_y, rumbo,
                )

            # FSS: corrige posición de sus tramos flanqueantes al eje Cart→End
            self._angulo_referencia = self.fss.actualizar(x_cart, y_cart, x_end, y_end)

            if self.torre_rapida.motor_activo:
                self._segundos_motor_rapido_on += 1

    def get_span_info(self, indice: int) -> dict:
        """Información geométrica y de alineación del tramo entre secciones[indice] y secciones[indice+1]."""
        izq = self.secciones[indice]
        der = self.secciones[indice + 1]
        dx  = der.posicion_x - izq.posicion_x
        dy  = der.posicion_y - izq.posicion_y
        lh  = abs(dx)
        L   = math.hypot(dx, dy)

        ang_abs = math.degrees(math.atan2(dy, lh)) if lh > 0 else 0.0
        ang_ref = self._angulo_referencia
        ang_rel = ang_abs - ang_ref
        while ang_rel >  180: ang_rel -= 360
        while ang_rel < -180: ang_rel += 360

        if lh > 0:
            dy_esperado   = math.tan(math.radians(ang_ref)) * lh
            desv_relativa = dy - dy_esperado
        else:
            desv_relativa = dy

        return {
            "x0": izq.posicion_x, "y0": izq.posicion_y,
            "x1": der.posicion_x, "y1": der.posicion_y,
            "longitud":                  L,
            "desviacion_norte":          dy,
            "desviacion_norte_relativa": desv_relativa,
            "angulo_grados":             ang_abs,
            "angulo_relativo_grados":    ang_rel,
            "esta_alineado":             abs(desv_relativa) < FreeStandingSpan.TOLERANCIA_ALINEACION,
            "es_rigido":                 (indice == self.indice_fss_izq),
        }

    def get_span_alineado(self, indice: int) -> bool:
        return self.get_span_info(indice)["esta_alineado"]

    def _tiempo_formateado(self) -> str:
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"
