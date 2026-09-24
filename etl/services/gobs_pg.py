"""
Origen de datos GOBS: base PostgreSQL en AWS RDS (usuario de solo lectura).

Reemplaza la carga manual de los Excel de declaraciones/actividades
(autorretención, retención ICA y Declare y Pague). El CSV de CXC sigue
subiéndose a mano porque viene de otro sistema.

Las vistas de GOBS son equivalentes a los Excel exportados, con dos diferencias
que este módulo compensa para que los procesadores (ProcesadorBase y derivados)
funcionen sin cambios:

1. Los nombres de columna vienen sin puntuación ni tildes
   ("11 Periodo declarado" en vez de "1.1 Periodo declarado").
   -> `a_estilo_excel` los devuelve al formato de los Excel.
2. Las vistas no traen los datos del contribuyente (nombres, tipo y número
   de documento). Se cruzan con `uvw_establishments_db` por "Id Establecimiento".

Configuración (.env): GOBS_PG_ENABLED, GOBS_PG_HOST, GOBS_PG_PORT, GOBS_PG_DB,
GOBS_PG_USER, GOBS_PG_PASSWORD, GOBS_PG_SSLMODE. Con GOBS_PG_ENABLED=False la
app sigue pidiendo los Excel como antes.
"""
import re
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd
from decouple import config

# Columnas del registro de establecimientos que no existen en un Excel exportado.
_EST_EXCLUIR = {"Nombre Productor", "Apellido Productor", "Id Historico", "Id Productor",
                "Fecha de creacion", "Load Timestamp"}

# Columnas que, en la vista, son identificadores enteros (llegan como double).
_COLS_CONSECUTIVO = {"Consecutivo", "Consecutivo 1", "Consecutivo 2"}

# Nombres que no se pueden deducir con la regla general "N texto" -> "N. texto".
_ESPECIALES = {
    "1 Ano": "1. Año",
    "11 Ano": "1.1 Año",
    "11 Periodo declarado": "1.1 Periodo declarado",
    "23 Tipo de declaracion": "2-3 Tipo de declaracion",  # no debe chocar con "23. Total a pagar"
    "Ano Gravable": "Año Gravable",
}


@dataclass(frozen=True)
class Fuente:
    """Qué vistas de qué esquema alimentan un proceso de un municipio."""
    schema: str
    declaraciones: str
    # Vista aparte de actividades (Declare y Pague). None => las actividades
    # vienen mezcladas en la vista de declaraciones (autorretención).
    actividades: str | None = None
    # Regex de las columnas que pertenecen a la actividad (CIIU), tanto para
    # separarlas de la declaración como para armar el DataFrame de actividades.
    cols_actividad: str | None = None
    establecimientos: str = "uvw_establishments_db"
    col_fecha: str = "Fecha de la visita"
    col_consecutivo: str = "Consecutivo"
    # Consecutivo con el que se une la vista de actividades aparte.
    col_union_actividades: str = "Consecutivo 2"
    # Nombres de columna de la vista de actividades -> nombre que espera el procesador.
    renombrar_actividades: tuple[tuple[str, str], ...] = ()
    # Variable de .env que debe ser True para usar esta fuente (None = siempre).
    activar_con: str | None = None


# (municipio, proceso) -> Fuente. Los procesos no listados siguen con Excel.
FUENTES: dict[tuple[str, str], Fuente] = {}


def _registrar_estilo_copa_estrella(municipio, schema, vista_auto, vista_rete,
                                    vista_dec, vista_act, col_consecutivo):
    cols_auto = r"^(Codigo CIIU|14 |15 |16 |17 Tarifa|18 |Load Timestamp CIIU)"
    cols_dec_act = (r"^(Consecutivo [12]|Codigo segun codificacion|Ingresos gravados|"
                    r"Tarifa|Impuestos de industria y comercio)")
    FUENTES[(municipio, "CXC_AUTO")] = Fuente(
        schema, vista_auto, cols_actividad=cols_auto, col_consecutivo=col_consecutivo)
    FUENTES[(municipio, "CXC_RETE")] = Fuente(
        schema, vista_rete, col_consecutivo=col_consecutivo)
    FUENTES[(municipio, "DECLAREYPAGUE")] = Fuente(
        schema, vista_dec, actividades=vista_act, cols_actividad=cols_dec_act,
        col_consecutivo="Consecutivo 1")


_registrar_estilo_copa_estrella(
    "ESTRELLA", "declaraciones_la_estrella",
    vista_auto="uvw_f_autorretencion__copacabana_actividades_ciiu",
    vista_rete="uvw_f_reteica",
    vista_dec="uvw_f_ica_anual_presente_aqui_su_declaracion",
    vista_act="uvw_cq_actividades_gravadas_presente_aqui_su_declaracion",
    col_consecutivo="Consecutivo",
)

_registrar_estilo_copa_estrella(
    "COPACABANA", "alcaldia_de_copacabana",
    vista_auto="uvw_f_autorretencion__copacabana_actividades_ciiu",
    vista_rete="uvw_f_reteica__copacabana",
    vista_dec="uvw_f_ica_anual_presente_aqui_su_declaracion__copacabana",
    vista_act="uvw_cq_actividades_gravadas_presente_aqui_su_declaracion",
    col_consecutivo="Consecutivo 1",
)

# Caldas: la vista de actividades no trae consecutivo (se une por Id Visita).
_COLS_ACT_AUTO = r"^(Codigo CIIU|14 |15 |16 |17 Tarifa|18 )"
FUENTES[("CALDAS", "CXC_AUTO")] = Fuente(
    "alcaldia_de_caldas", "uvw_f_autorretencioncaldas",
    actividades="uvw_cq_13_actividades_ciiu_autorretenciones",
    cols_actividad=_COLS_ACT_AUTO, col_union_actividades="Id Visita")
FUENTES[("CALDAS", "CXC_RETE")] = Fuente("alcaldia_de_caldas", "uvw_f_reteica__caldas")

# Caldas DECLAREYPAGUE: LISTO PERO DESACTIVADO. Al 2026-09-23 GOBS no tiene las actividades
# ICA de Caldas (cq_actividades_gravadas: 11 filas, todas de prueba, frente a 9.084 en
# Copacabana). Las 4 columnas "Q 1934xx" son las preguntas del formulario, en este orden:
# código CIIU, ingresos gravados, tarifa, impuesto. Activar con GOBS_PG_CALDAS_DECLARE=True
# cuando GOBS cargue las actividades (validar antes con verificar_gobs).
FUENTES[("CALDAS", "DECLAREYPAGUE")] = Fuente(
    "alcaldia_de_caldas", "uvw_f_ica_anual__caldas",
    actividades="uvw_cq_actividades_gravadas_ica",
    cols_actividad=r"^Q 19347[89]$|^Q 19348[01]$", col_union_actividades="Id Visita",
    renombrar_actividades=(
        ("Q 193478", "Codigo segun codificacion municipal o distrital"),
        ("Q 193479", "Ingresos gravados"),
        ("Q 193480", "Tarifa"),
        ("Q 193481", "Impuestos de industria y comercio"),
    ),
    activar_con="GOBS_PG_CALDAS_DECLARE")

# Envigado: sin CXC de otro sistema y con "Fecha de presentacion" en lugar de fecha de visita.
FUENTES[("ENVIGADO", "CXC_AUTO")] = Fuente(
    "alcaldia_de_envigado", "uvw_f_autorretencion_envigado_actividades_ciiu",
    cols_actividad=_COLS_ACT_AUTO, col_fecha="Fecha de presentacion")
FUENTES[("ENVIGADO", "CXC_RETE")] = Fuente(
    "alcaldia_de_envigado", "uvw_f_reteica_envigado",
    col_fecha="Fecha de presentacion", col_consecutivo="Consecutivo 1")

# Sabaneta: publicidad exterior visual. "Consecutivo 1" (global) viene vacío en las
# declaraciones antiguas; el radicado del formulario es "Consecutivo 2".
FUENTES[("SABANETA", "PUBLICIDAD_EXTERIOR")] = Fuente(
    "alcaldia_de_sabaneta", "uvw_f_declaracion_publicidad_exterior_visual__sabaneta",
    col_consecutivo="Consecutivo 2")


def habilitado() -> bool:
    return config("GOBS_PG_ENABLED", default=False, cast=bool) and bool(
        config("GOBS_PG_HOST", default=""))


def fuente_para(municipio_codigo: str, proceso_codigo: str) -> Fuente | None:
    """Fuente GOBS del proceso, o None si no aplica (o no está habilitado)."""
    if not habilitado():
        return None
    fuente = FUENTES.get((municipio_codigo, proceso_codigo))
    if fuente and fuente.activar_con and not config(fuente.activar_con, default=False, cast=bool):
        return None
    return fuente


# ── nombres de columnas ─────────────────────────────────────────────────────

def a_estilo_excel(col: str) -> str:
    """'40 Total a pagar ...' -> '40. Total a pagar ...' (formato de los Excel).

    Algunos procesadores (Caldas) buscan columnas por el número de renglón exacto
    ("14.1", "20.1"), así que la numeración debe reproducir la de los Excel."""
    if col in _ESPECIALES:
        return _ESPECIALES[col]
    # Subrenglones: "141 Actividad..." -> "14.1 Actividad..." (14x a 20x, sufijo 1-3)
    m = re.match(r"^(1[4-9]|20)([1-3]) (?=\S)", col)
    if m:
        return f"{m.group(1)}.{m.group(2)} " + col[m.end():]
    m = re.match(r"^(\d+) (?=\S)", col)
    if m:
        return f"{m.group(1)}. " + col[m.end():]
    return col


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if df[c].dtype == object:
            # PostgreSQL entrega NULL como None; un Excel lo entrega como NaN y el
            # código de los procesadores depende de eso (p. ej. "vacío" == "nan").
            df[c] = df[c].where(df[c].notna(), np.nan)
        if c in _COLS_CONSECUTIVO:
            num = pd.to_numeric(df[c], errors="coerce")
            if num.notna().sum() == df[c].notna().sum():
                df[c] = num.astype("Int64")
    return df.rename(columns={c: a_estilo_excel(c) for c in df.columns})


# ── acceso a PostgreSQL ─────────────────────────────────────────────────────

def _conectar():
    import psycopg2
    conn = psycopg2.connect(
        host=config("GOBS_PG_HOST"),
        port=config("GOBS_PG_PORT", default=5432, cast=int),
        dbname=config("GOBS_PG_DB", default="gobs"),
        user=config("GOBS_PG_USER"),
        password=config("GOBS_PG_PASSWORD"),
        sslmode=config("GOBS_PG_SSLMODE", default="require"),
        connect_timeout=15,
        options="-c statement_timeout=180000",
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _leer_vista(conn, schema, vista, donde=None, params=()):
    from psycopg2 import sql
    q = sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(vista))
    if donde is not None:
        q = q + sql.SQL(" WHERE ") + donde
    with conn.cursor() as cur:
        cur.execute(q, params)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _cruzar_establecimientos(conn, fuente, dec):
    """Agrega nombres/documento del contribuyente a la declaración."""
    from psycopg2 import sql
    ids = [float(i) for i in dec["Id Establecimiento"].dropna().unique()]
    if not ids:
        return dec
    est = _leer_vista(conn, fuente.schema, fuente.establecimientos,
                      sql.SQL("{} = ANY(%s)").format(sql.Identifier("Id Establecimiento")),
                      (ids,))
    if "Fecha de edicion" in est.columns:
        est = est.sort_values("Fecha de edicion", na_position="first")
    est = est.drop_duplicates("Id Establecimiento", keep="last")
    orden_est = [c for c in est.columns if c not in _EST_EXCLUIR and c != "Id Establecimiento"]
    traer = [c for c in orden_est if c not in dec.columns]
    out = dec.merge(est[["Id Establecimiento", *traer]], on="Id Establecimiento", how="left")
    # Un Excel exportado trae primero los datos del establecimiento (en el orden del registro)
    # y después los de la declaración; algunos procesadores toman "la primera columna que
    # contiene X" (p. ej. "ESTABLECIMIENTO" debe dar "Nombre del establecimiento").
    resto = [c for c in dec.columns if c not in orden_est]
    return out[orden_est + resto]


def cargar(fuente: Fuente, desde=None, hasta=None) -> tuple[dict, dict]:
    """
    Devuelve ({"declaraciones": df, "actividades": df?}, meta).
    `desde`/`hasta` (date) filtran por la fecha de la declaración, ambos inclusive.
    """
    from psycopg2 import sql

    condiciones, params = [], []
    fecha = sql.Identifier(fuente.col_fecha)
    if desde:
        condiciones.append(sql.SQL("{} >= %s").format(fecha))
        params.append(desde)
    if hasta:
        condiciones.append(sql.SQL("{} < %s").format(fecha))
        params.append(hasta + timedelta(days=1))
    donde = sql.SQL(" AND ").join(condiciones) if condiciones else None

    conn = _conectar()
    try:
        vista = _leer_vista(conn, fuente.schema, fuente.declaraciones, donde, tuple(params))
        vista = vista.dropna(subset=[fuente.col_consecutivo])  # sin consecutivo no hay CXC
        act = None

        if fuente.actividades is None and fuente.cols_actividad:
            # Vista mezclada: una fila por (declaración, actividad).
            es_act = [bool(re.match(fuente.cols_actividad, c)) for c in vista.columns]
            claves = [c for c in vista.columns if c in _COLS_CONSECUTIVO]
            act = vista[[c for c, a in zip(vista.columns, es_act) if a or c in claves]].copy()
            dec = vista[[c for c, a in zip(vista.columns, es_act) if not a]].copy()
            dec = dec.drop_duplicates(fuente.col_consecutivo)
        else:
            dec = vista.drop_duplicates(fuente.col_consecutivo)
            if fuente.actividades:
                union = fuente.col_union_actividades
                claves = [float(v) for v in dec[union].dropna().unique()]
                act_full = _leer_vista(
                    conn, fuente.schema, fuente.actividades,
                    sql.SQL("{} = ANY(%s)").format(sql.Identifier(union)),
                    (claves,)) if claves else pd.DataFrame(columns=[union])
                cols = [c for c in act_full.columns if re.match(fuente.cols_actividad, c)]
                if union == "Id Visita":
                    # La vista de actividades no trae consecutivo: se toma de la declaración.
                    act = act_full[[union, *cols]].merge(
                        dec[[union, fuente.col_consecutivo]].drop_duplicates(union),
                        on=union, how="inner")
                    # Filas sin datos (la vista cruza establecimientos con formularios vacíos)
                    act = act.dropna(subset=cols, how="all")
                else:
                    act = act_full[cols].copy()

        dec = _cruzar_establecimientos(conn, fuente, dec)
    finally:
        conn.close()

    ts_cols = [c for c in dec.columns if str(c).startswith("Load Timestamp")]
    ts = None
    for c in ts_cols:
        v = pd.to_datetime(dec[c], errors="coerce").max()
        if pd.notna(v) and (ts is None or v > ts):
            ts = v
    meta = {"declaraciones": len(dec), "datos_al": ts}

    datos = {"declaraciones": _normalizar(dec.reset_index(drop=True))}
    if act is not None:
        act = act.rename(columns=dict(fuente.renombrar_actividades))
        datos["actividades"] = _normalizar(act.reset_index(drop=True))
    return datos, meta
