"""Generación de informes: PDF mensual y Excel de presentación."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from fpdf import FPDF

import nucleo


def _t(s) -> str:
    """Texto seguro para fuentes core de PDF (latin-1)."""
    s = str(s).replace("–", "-").replace("—", "-").replace("→", "->").replace("’", "'")
    return s.encode("latin-1", "ignore").decode("latin-1")


def tablas(d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    total = max(len(d), 1)
    emp = d.groupby("Empresa Fúnebre").size().reindex(nucleo.EMPRESAS, fill_value=0).rename("Servicios").to_frame()
    emp["Participación"] = (emp["Servicios"] / total).map("{:.1%}".format)
    emp = emp.reset_index().rename(columns={"Empresa Fúnebre": "Empresa"})

    dest = d.groupby(["Empresa Fúnebre", "Tipo de Destino"]).size().unstack(fill_value=0)
    for c in ["Inhumación", "Cremación", nucleo.SIN_DATO]:
        if c not in dest.columns:
            dest[c] = 0
    dest = dest[["Inhumación", "Cremación", nucleo.SIN_DATO]].reindex(nucleo.EMPRESAS, fill_value=0)
    inf = (dest["Inhumación"] + dest["Cremación"]).replace(0, float("nan"))
    dest["% Cremación (s/ informados)"] = (dest["Cremación"] / inf).map(lambda x: "s/d" if pd.isna(x) else f"{x:.1%}")
    dest = dest.reset_index().rename(columns={"Empresa Fúnebre": "Empresa"})

    cem = (d[d["Cementerio de Destino"] != nucleo.SIN_DATO].groupby(["Cementerio de Destino", "Tipo de Destino"])
           .size().rename("Servicios").reset_index().sort_values("Servicios", ascending=False).head(15))

    mes = d.groupby(["Período (Año-Mes)", "Empresa Fúnebre"]).size().unstack(fill_value=0)
    mes["Total"] = mes.sum(axis=1)
    mes = mes.reset_index().rename(columns={"Período (Año-Mes)": "Mes"})

    dia = d.groupby("Día de la Semana").size().reindex(nucleo.DIAS, fill_value=0).rename("Servicios").reset_index()
    return {"Empresas": emp, "Cremación vs Inhumación": dest, "Top destinos": cem, "Evolución mensual": mes, "Días de la semana": dia}


def generar_excel(d: pd.DataFrame, ocultar_nombres: bool) -> bytes:
    buf = io.BytesIO()
    base = d.drop(columns=["Nombre del Fallecido"], errors="ignore") if ocultar_nombres else d
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        for nombre, t in tablas(d).items():
            t.to_excel(xw, sheet_name=nombre[:31], index=False)
        base.assign(Fecha=base["Fecha"].dt.strftime("%Y-%m-%d")).to_excel(xw, sheet_name="Base filtrada", index=False)
        for ws in xw.sheets.values():
            ws.set_column(0, 12, 22)
    return buf.getvalue()


def _tabla_pdf(pdf: FPDF, t: pd.DataFrame, anchos: list[float] | None = None):
    pdf.set_font("Helvetica", "B", 8)
    n = len(t.columns)
    anchos = anchos or [190 / n] * n
    pdf.set_fill_color(47, 85, 151)
    pdf.set_text_color(255, 255, 255)
    for c, w in zip(t.columns, anchos):
        pdf.cell(w, 6, _t(c)[:28], border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(0, 0, 0)
    for _, r in t.iterrows():
        for v, w in zip(r, anchos):
            pdf.cell(w, 5.5, _t(v)[:34], border=1)
        pdf.ln()
    pdf.ln(3)


def generar_pdf(d: pd.DataFrame, titulo: str, periodo_txt: str, sem: pd.DataFrame) -> bytes:
    tb = tablas(d)
    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _t(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _t(f"Período: {periodo_txt} | Servicios verificados: {len(d):,}".replace(",", ".")), new_x="LMARGIN", new_y="NEXT")
    cr = int((d["Tipo de Destino"] == "Cremación").sum())
    inh = int((d["Tipo de Destino"] == "Inhumación").sum())
    pdf.cell(0, 5, _t(f"Cremación: {cr / max(cr + inh, 1):.1%} ({cr}) | Inhumación: {inh / max(cr + inh, 1):.1%} ({inh}) - sobre servicios con destino informado. "
                      "Parque del Recuerdo y crematorios cuentan como cremación."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    m = tb["Evolución mensual"].set_index("Mes").drop(columns=["Total"])
    fig, ax = plt.subplots(figsize=(8, 3))
    m.plot(kind="bar", stacked=True, ax=ax, width=0.8, legend=True)
    ax.set_xlabel("")
    ax.set_ylabel("Servicios")
    ax.legend(fontsize=6)
    ax.tick_params(axis="x", labelsize=7, rotation=45)
    fig.tight_layout()
    img = io.BytesIO()
    fig.savefig(img, format="png", dpi=150)
    plt.close(fig)
    img.seek(0)
    pdf.image(img, w=190)
    pdf.ln(2)

    for nombre in ["Empresas", "Cremación vs Inhumación", "Top destinos", "Días de la semana"]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _t(nombre), new_x="LMARGIN", new_y="NEXT")
        _tabla_pdf(pdf, tb[nombre])

    if not sem.empty:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Origen y actualización de los datos", new_x="LMARGIN", new_y="NEXT")
        s = sem[["Fuente", "Último Aviso Capturado", "Días sin Datos Nuevos", "Registros en Base"]].copy()
        s["Fuente"] = s["Fuente"].astype(str).str[:48]
        _tabla_pdf(pdf, s, [95, 35, 30, 30])
    return bytes(pdf.output())
