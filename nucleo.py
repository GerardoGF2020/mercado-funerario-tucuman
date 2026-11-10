"""Lógica de datos pura (sin Streamlit): carga, normalización, calidad y semáforo.
Se usa tanto desde la app como desde alertas.py (línea de comandos)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
EXCEL_DIR = DATA_DIR / "excel"

LIMPIO = "Limpio - Verificado"
AUTOCONSOLIDADO = "Auto-Consolidado (Tipeo / Continuación Velatorio)"
DUDA = "Posible Duplicado - Consultar al Operador"
SIN_DATO = "No especificado / Sin dato"

EMPRESAS = [
    "Empresa Flores",
    "Empresa San Bernardo",
    "Empresa San Agustin",
    "Empresa Galvez",
    "Servicio Directo / Parque de la Paz",
]
EMPRESAS_ACTIVAS = ["Empresa Flores", "Empresa San Bernardo"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
VENTANA_DESDE = "2025-10"

UMBRAL_DIAS_ATRASO = 2
UMBRAL_SIN_CEMENTERIO = 0.45
UMBRAL_SIN_HORA = 0.50


def cargar_base() -> pd.DataFrame:
    ruta = DATA_DIR / "base_unificada.csv"
    if not ruta.exists():
        return pd.DataFrame()
    df = pd.read_csv(ruta, encoding="utf-8-sig")
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    for c in ["Cementerio de Destino", "Tipo de Destino", "Sala Velatoria", "Categoría de Sala", "Localidad"]:
        if c in df.columns:
            df[c] = df[c].fillna(SIN_DATO)
    # Regla de negocio confirmada: Parque del Recuerdo y crematorios = Cremación.
    cem = df["Cementerio de Destino"].astype(str).str.lower()
    df.loc[cem.str.contains("recuerdo|cremat|descanso", regex=True), "Tipo de Destino"] = "Cremación"
    return df


def cargar_semaforo(hoy: pd.Timestamp | None = None) -> pd.DataFrame:
    """Semáforo recalculado contra HOY (no contra el día en que corrió el ETL)."""
    ruta = DATA_DIR / "semaforo.csv"
    if not ruta.exists():
        return pd.DataFrame()
    s = pd.read_csv(ruta, encoding="utf-8-sig")
    hoy = (hoy or pd.Timestamp.now()).normalize()
    ultimo = pd.to_datetime(s["Último Aviso Capturado"], format="%d/%m/%Y", errors="coerce")
    dias = (hoy - ultimo).dt.days
    s["Días sin Datos Nuevos"] = dias
    s["Fecha del Reporte (Hoy)"] = f"{hoy:%d/%m/%Y}"

    def estado(d):
        if pd.isna(d):
            return "🔴 SIN DATOS"
        if d <= UMBRAL_DIAS_ATRASO:
            return "🟢 AL DÍA"
        if d <= 7:
            return "🟡 ATRASADO"
        return "🔴 DESACTUALIZADO"

    s["Estado"] = dias.map(estado)
    return s


def ultima_actualizacion() -> str:
    ruta = DATA_DIR / "ultima_actualizacion.json"
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8")).get("timestamp", "s/d")
        except Exception:
            pass
    return "s/d"


def ventana(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["Estado de Revisión"] == LIMPIO) & (df["Período (Año-Mes)"] >= VENTANA_DESDE)]


def calidad(df: pd.DataFrame) -> list[dict]:
    """Chequeos de calidad. Devuelve lista de {nivel, mensaje}. nivel: ok | aviso | error."""
    res: list[dict] = []
    if df.empty:
        return [{"nivel": "error", "mensaje": "No hay base de datos cargada."}]
    v = ventana(df)
    act = v[v["Empresa Fúnebre"].isin(EMPRESAS_ACTIVAS)]
    if len(act):
        sin_cem = (act["Cementerio de Destino"] == SIN_DATO).mean()
        sin_hora = (act["Franja Horaria"] == "Sin Hora Informada").mean()
        res.append({
            "nivel": "aviso" if sin_cem > UMBRAL_SIN_CEMENTERIO else "ok",
            "mensaje": f"Sin cementerio informado (Flores + San Bernardo): {sin_cem:.0%} (umbral {UMBRAL_SIN_CEMENTERIO:.0%}).",
        })
        res.append({
            "nivel": "aviso" if sin_hora > UMBRAL_SIN_HORA else "ok",
            "mensaje": f"Sin hora informada (Flores + San Bernardo): {sin_hora:.0%} (umbral {UMBRAL_SIN_HORA:.0%}).",
        })
    hist = DATA_DIR / "historial.csv"
    if hist.exists():
        h = pd.read_csv(hist)
        if len(h) >= 2 and h["filas"].iloc[-1] < h["filas"].iloc[-2]:
            res.append({"nivel": "error", "mensaje": f"La base BAJÓ de {h['filas'].iloc[-2]} a {h['filas'].iloc[-1]} filas desde la sync anterior."})
        elif len(h) >= 2:
            res.append({"nivel": "ok", "mensaje": f"Base creció {h['filas'].iloc[-1] - h['filas'].iloc[-2]:+d} filas desde la sync anterior."})
    fut = df[df["Fecha"] > pd.Timestamp.now().normalize() + pd.Timedelta(days=7)]
    if len(fut):
        res.append({"nivel": "aviso", "mensaje": f"{len(fut)} registros con fecha futura (>7 días): posible error de formato de fecha."})
    nulas = int(df["Fecha"].isna().sum())
    if nulas:
        res.append({"nivel": "error", "mensaje": f"{nulas} registros sin fecha válida."})
    if not res:
        res.append({"nivel": "ok", "mensaje": "Sin observaciones de calidad."})
    return res


def alertas_scrapers(sem: pd.DataFrame) -> list[dict]:
    """Fuentes con scraper activo atrasadas más de UMBRAL_DIAS_ATRASO días."""
    out = []
    if sem.empty:
        return [{"nivel": "error", "mensaje": "No hay semáforo cargado."}]
    for _, r in sem.iterrows():
        nombre = str(r["Fuente"])
        if "histórica" in nombre.lower():
            continue
        d = r["Días sin Datos Nuevos"]
        if pd.isna(d) or d > UMBRAL_DIAS_ATRASO:
            out.append({"nivel": "error" if (pd.isna(d) or d > 7) else "aviso",
                        "mensaje": f"{nombre}: {'sin datos' if pd.isna(d) else f'{int(d)} días sin avisos nuevos'} (último {r['Último Aviso Capturado']})."})
    return out


def pct(x: float) -> str:
    return "s/d" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1%}"
