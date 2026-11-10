"""Páginas de la app. Cada función recibe el DataFrame filtrado `d` y el contexto `ctx`."""
from __future__ import annotations

import io
import json

import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import informes
import nucleo
from nucleo import DIAS, EMPRESAS, LIMPIO, SIN_DATO, pct

COLORES = {"Cremación": "#C0504D", "Inhumación": "#4F81BD", SIN_DATO: "#BFBFBF"}


def _mes_parcial(periodos) -> set:
    ps = sorted(periodos)
    out = set()
    if ps:
        out.add(ps[0])
        out.add(pd.Timestamp.now().strftime("%Y-%m"))
    return out


def _pct_col(df: pd.DataFrame, cols: list[str]):
    return df.style.format({c: "{:.1%}" for c in cols}, na_rep="s/d")


# ----------------------------------------------------------------------------- Resumen
def resumen(d, ctx):
    st.title("📊 Resumen ejecutivo")
    sem = ctx["semaforo"]
    if d.empty:
        st.warning("No hay datos con los filtros elegidos.")
        return
    cr = int((d["Tipo de Destino"] == "Cremación").sum())
    inh = int((d["Tipo de Destino"] == "Inhumación").sum())
    lider = d["Empresa Fúnebre"].value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Servicios verificados", f"{len(d):,}".replace(",", "."))
    c2.metric("Líder del mercado", lider.index[0].replace("Empresa ", ""), f"{lider.iloc[0] / len(d):.1%} del total")
    c3.metric("Cremación (s/ informados)", pct(cr / max(cr + inh, 1)), f"{cr} crem. / {inh} inhum.")
    c4.metric("Último aviso", f"{d['Fecha'].max():%d/%m/%Y}")
    st.caption("Cremación incluye Parque del Descanso, Crematorio y **Cementerio Parque del Recuerdo** (todos son cremaciones).")

    st.subheader("¿Están llegando datos nuevos?")
    if not sem.empty:
        st.dataframe(sem[["Fuente", "Estado", "Último Aviso Capturado", "Días sin Datos Nuevos", "Registros en Base"]],
                     use_container_width=True, hide_index=True)
    for a in nucleo.alertas_scrapers(sem):
        (st.error if a["nivel"] == "error" else st.warning)(a["mensaje"])

    a, b = st.columns(2)
    with a:
        st.subheader("Participación de mercado")
        share = d["Empresa Fúnebre"].value_counts().rename_axis("Empresa").reset_index(name="Servicios")
        st.plotly_chart(px.pie(share, names="Empresa", values="Servicios", hole=0.45), use_container_width=True)
    with b:
        st.subheader("Cremación vs. inhumación")
        t = d["Tipo de Destino"].value_counts().rename_axis("Tipo").reset_index(name="Servicios")
        st.plotly_chart(px.pie(t, names="Tipo", values="Servicios", hole=0.45, color="Tipo", color_discrete_map=COLORES),
                        use_container_width=True)
    st.subheader("Evolución mensual")
    m = d.groupby(["Período (Año-Mes)", "Empresa Fúnebre"]).size().rename("Servicios").reset_index()
    st.plotly_chart(px.bar(m, x="Período (Año-Mes)", y="Servicios", color="Empresa Fúnebre"), use_container_width=True)
    parciales = _mes_parcial(m["Período (Año-Mes)"].unique())
    st.caption(f"Meses parciales (no comparar con meses completos): {', '.join(sorted(parciales))}.")


# ----------------------------------------------------------------------------- Empresas
def empresas(d, ctx):
    st.title("🏢 Empresas fúnebres")
    total = max(len(d), 1)
    t = d.groupby("Empresa Fúnebre").size().reindex(EMPRESAS, fill_value=0).rename("Servicios").to_frame()
    t["Participación"] = t["Servicios"] / total
    t["% en La Gaceta"] = [nucleo_pct_gaceta(d[d["Empresa Fúnebre"] == e]) for e in t.index]
    origen = {
        "Empresa Flores": "Scraper web empresaflores.com",
        "Empresa San Bernardo": "Scraper web sanbernardosepelios.com.ar",
        "Empresa San Agustin": "Base histórica (sin scraper activo)",
        "Empresa Galvez": "Base histórica (sin scraper activo)",
        "Servicio Directo / Parque de la Paz": "Scraper parquedelapaz.com.ar",
    }
    t["Origen del dato"] = [origen[e] for e in t.index]
    st.dataframe(_pct_col(t.reset_index(), ["Participación", "% en La Gaceta"]), use_container_width=True, hide_index=True)
    st.caption("La Gaceta es un diario (canal de prensa), no una funeraria: se cruza por nombre y fecha para medir qué % de cada empresa publica aviso.")

    m = d.groupby(["Período (Año-Mes)", "Empresa Fúnebre"]).size().rename("Servicios").reset_index()
    st.plotly_chart(px.line(m, x="Período (Año-Mes)", y="Servicios", color="Empresa Fúnebre", markers=True), use_container_width=True)

    st.subheader("Modalidad de velatorio")
    s = d.groupby(["Categoría de Sala", "Empresa Fúnebre"]).size().rename("Servicios").reset_index()
    st.plotly_chart(px.bar(s, x="Categoría de Sala", y="Servicios", color="Empresa Fúnebre", barmode="group"), use_container_width=True)


def nucleo_pct_gaceta(sub: pd.DataFrame) -> float:
    ver = sub[sub["Publicado en La Gaceta"].isin(["Sí", "No"])]
    return float((ver["Publicado en La Gaceta"] == "Sí").mean()) if len(ver) else float("nan")


# ----------------------------------------------------------------------------- Cementerios
def cementerios(d, ctx):
    st.title("⚰️ Cementerios y cremaciones")
    st.info("Regla confirmada: todo servicio con destino **Cementerio Parque del Recuerdo** es una **cremación**, "
            "igual que Parque del Descanso (Flores) y Crematorio (San Bernardo).")
    cem = d[d["Cementerio de Destino"] != SIN_DATO]
    top = (cem.groupby(["Cementerio de Destino", "Tipo de Destino"]).size().rename("Servicios").reset_index()
           .sort_values("Servicios", ascending=False).head(20))
    st.subheader(f"Top 20 destinos ({len(cem)} servicios con destino informado de {len(d)})")
    st.plotly_chart(px.bar(top, x="Servicios", y="Cementerio de Destino", color="Tipo de Destino", orientation="h",
                           color_discrete_map=COLORES).update_yaxes(autorange="reversed"), use_container_width=True)

    st.subheader("Inhumación vs. cremación por empresa")
    p = d.groupby(["Empresa Fúnebre", "Tipo de Destino"]).size().unstack(fill_value=0).reindex(EMPRESAS, fill_value=0)
    for c in ["Inhumación", "Cremación", SIN_DATO]:
        if c not in p.columns:
            p[c] = 0
    p = p[["Inhumación", "Cremación", SIN_DATO]]
    inf = (p["Inhumación"] + p["Cremación"]).replace(0, float("nan"))
    p["% Cremación"] = p["Cremación"] / inf
    p["% Inhumación"] = p["Inhumación"] / inf
    st.dataframe(_pct_col(p.reset_index(), ["% Cremación", "% Inhumación"]), use_container_width=True, hide_index=True)

    st.subheader("¿A qué crematorio / parque va cada empresa?")
    cr = d[d["Tipo de Destino"] == "Cremación"]
    g = cr.groupby(["Cementerio de Destino", "Empresa Fúnebre"]).size().unstack(fill_value=0)
    g["Total"] = g.sum(axis=1)
    g["% s/ cremaciones"] = g["Total"] / max(g["Total"].sum(), 1)
    st.dataframe(_pct_col(g.sort_values("Total", ascending=False).reset_index(), ["% s/ cremaciones"]),
                 use_container_width=True, hide_index=True)

    st.subheader("Matriz destino × empresa")
    mx = cem.groupby(["Cementerio de Destino", "Empresa Fúnebre"]).size().unstack(fill_value=0)
    mx["Total"] = mx.sum(axis=1)
    st.dataframe(mx.sort_values("Total", ascending=False).head(25), use_container_width=True)


# ----------------------------------------------------------------------------- Picos
def picos(d, ctx):
    st.title("⏱️ Picos de demanda")
    dia = d.groupby(["Día de la Semana", "Empresa Fúnebre"]).size().rename("Servicios").reset_index()
    st.plotly_chart(px.bar(dia, x="Día de la Semana", y="Servicios", color="Empresa Fúnebre",
                           category_orders={"Día de la Semana": DIAS}), use_container_width=True)
    h = d[d["Franja Horaria"] != "Sin Hora Informada"]
    st.subheader(f"Franja horaria (sobre {len(h)} servicios con hora real, {len(h) / max(len(d), 1):.0%} del total)")
    f = h.groupby(["Franja Horaria", "Empresa Fúnebre"]).size().rename("Servicios").reset_index()
    st.plotly_chart(px.bar(f, x="Franja Horaria", y="Servicios", color="Empresa Fúnebre"), use_container_width=True)
    hh = h.assign(H=h["Hora de Inicio"]).groupby("H").size().rename("Servicios").reset_index()
    st.plotly_chart(px.bar(hh, x="H", y="Servicios", title="Servicios por hora de inicio"), use_container_width=True)
    if len(hh) and hh["Servicios"].max() / hh["Servicios"].sum() > 0.30:
        st.warning("Una sola hora concentra más del 30% de los servicios: probable hora por defecto del sitio, interpretar con cautela.")


# ----------------------------------------------------------------------------- San Agustín
def san_agustin(d, ctx):
    st.title("🏛️ Tablero gerencial — San Agustín")
    SA = "Empresa San Agustin"
    sa = d[d["Empresa Fúnebre"] == SA]
    st.warning("Los datos de San Agustín vienen de una base histórica sin scraper activo: los meses recientes están incompletos "
               "y no sirven para medir tendencia. Tampoco informan cementerio de destino.")
    if sa.empty:
        st.info("Sin servicios de San Agustín en el período filtrado.")
        return
    rank = d["Empresa Fúnebre"].value_counts()
    pos = list(rank.index).index(SA) + 1
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Servicios", len(sa))
    c2.metric("Ranking", f"{pos}° de {len(rank)}")
    c3.metric("Participación", f"{len(sa) / len(d):.1%}")
    c4.metric("Último dato", f"{sa['Fecha'].max():%d/%m/%Y}")
    mes = pd.DataFrame({"San Agustín": sa.groupby("Período (Año-Mes)").size(), "Total mercado": d.groupby("Período (Año-Mes)").size()}).fillna(0).astype(int)
    mes["Participación"] = mes["San Agustín"] / mes["Total mercado"].replace(0, float("nan"))
    st.subheader("Evolución mensual y participación")
    st.dataframe(_pct_col(mes.reset_index().rename(columns={"index": "Mes"}), ["Participación"]), use_container_width=True, hide_index=True)
    st.plotly_chart(px.bar(mes.reset_index(), x="Período (Año-Mes)", y="San Agustín"), use_container_width=True)
    a, b = st.columns(2)
    with a:
        dd = sa.groupby("Día de la Semana").size().reindex(DIAS, fill_value=0).rename("Servicios").reset_index()
        st.plotly_chart(px.bar(dd, x="Día de la Semana", y="Servicios", title="Días de mayor trabajo"), use_container_width=True)
    with b:
        sl = sa.groupby("Sala Velatoria").size().sort_values(ascending=False).head(8).rename("Servicios").reset_index()
        st.plotly_chart(px.bar(sl, x="Servicios", y="Sala Velatoria", orientation="h", title="Salas más usadas").update_yaxes(autorange="reversed"),
                        use_container_width=True)
    st.metric("Calidad: cementerio informado", f"{(sa['Cementerio de Destino'] != SIN_DATO).mean():.0%}")
    st.metric("Calidad: hora informada", f"{(sa['Franja Horaria'] != 'Sin Hora Informada').mean():.0%}")


# ----------------------------------------------------------------------------- Comparativas
def comparativas(d, ctx):
    st.title("📈 Comparativas mes a mes")
    piv = d.groupby(["Período (Año-Mes)", "Empresa Fúnebre"]).size().unstack(fill_value=0)
    piv["TOTAL"] = piv.sum(axis=1)
    parciales = _mes_parcial(piv.index)
    completos = piv.drop(index=[p for p in parciales if p in piv.index])
    st.subheader("Servicios por mes")
    st.dataframe(piv, use_container_width=True)
    if len(completos) >= 2:
        var = completos.pct_change().iloc[1:]
        st.subheader("Variación vs. mes anterior (solo meses completos)")
        st.dataframe(var.style.format("{:+.1%}", na_rep="s/d"), use_container_width=True)
        ult, ant = completos.index[-1], completos.index[-2]
        st.metric(f"Total {ult} vs {ant}", int(completos.loc[ult, "TOTAL"]), f"{completos.loc[ult, 'TOTAL'] - completos.loc[ant, 'TOTAL']:+d}")
    st.caption(f"Excluidos por parciales: {', '.join(sorted(parciales)) or 'ninguno'}. Hay un solo año de historia, la comparación interanual estará disponible desde oct-2026.")
    if len(completos):
        prom = completos.mean().round(1).rename("Promedio mensual").to_frame()
        st.dataframe(prom, use_container_width=True)


# ----------------------------------------------------------------------------- Fuentes y calidad
def fuentes(d, ctx):
    st.title("🔎 Fuentes, actualización y calidad")
    st.caption(f"Última sincronización de datos: **{nucleo.ultima_actualizacion()}**")
    sem = ctx["semaforo"]
    if not sem.empty:
        st.dataframe(sem.drop(columns=["Fecha del Reporte (Hoy)"], errors="ignore"), use_container_width=True, hide_index=True)
    st.subheader("Chequeos de calidad")
    for c in nucleo.calidad(ctx["base"]):
        {"ok": st.success, "aviso": st.warning, "error": st.error}[c["nivel"]](c["mensaje"])
    st.subheader("Cómo se interpretan los datos")
    st.markdown(
        "- **Empresas fúnebres** (Flores, San Bernardo, San Agustín, Gálvez, Servicio Directo Parque): prestan el servicio.\n"
        "- **Cementerios / crematorios**: destino del servicio. *Parque del Recuerdo, Parque del Descanso y Crematorio = cremación.*\n"
        "- **La Gaceta**: diario (canal de prensa). No suma servicios; se cruza por nombre y fecha (−3 a +7 días) para medir cobertura.\n"
        "- **Parque de la Paz**: scraper propio; 271 filas jul–sep 2026 no traen nombre y no entran a la lista nominal.\n"
        "- **Regla de no borrado**: ninguna fila se elimina; los duplicados se consolidan marcándolos (ver *Sala de Revisión*)."
    )
    hist = nucleo.DATA_DIR / "historial.csv"
    if hist.exists():
        st.subheader("Historial de sincronizaciones")
        st.dataframe(pd.read_csv(hist).tail(30).iloc[::-1], use_container_width=True, hide_index=True)
    log = nucleo.APP_DIR / "alertas.log"
    if log.exists() and ctx["rol"] == "admin":
        with st.expander("Log de alertas"):
            st.code("".join(log.read_text(encoding="utf-8").splitlines(keepends=True)[-30:]))


# ----------------------------------------------------------------------------- Sala de revisión
DECISIONES = nucleo.DATA_DIR / "decisiones_operador.json"


def revision(d, ctx):
    st.title("🧐 Sala de Revisión")
    base = ctx["base"]
    g = base[base["ID Grupo Duplicado"].notna()].copy()
    pend = g[g["Estado de Revisión"] == nucleo.DUDA]
    c1, c2, c3 = st.columns(3)
    c1.metric("Dudas pendientes", pend["ID Grupo Duplicado"].nunique())
    c2.metric("Auto-consolidados", int((g["Estado de Revisión"] == nucleo.AUTOCONSOLIDADO).sum()))
    c3.metric("Filas borradas", 0)
    cols = [c for c in ["ID Grupo Duplicado", "Estado de Revisión", "Score Similitud (%)", "Empresa Fúnebre", "Fecha", "Nombre del Fallecido",
                        "Cementerio de Destino", "Sala Velatoria", "Detalle de Alerta"] if c in g.columns]
    if ctx["rol"] != "admin":
        cols = [c for c in cols if c != "Nombre del Fallecido"]
    if pend.empty:
        st.success("No hay dudas pendientes para el operador.")
    else:
        st.subheader("Pendientes de decisión")
        st.dataframe(pend[cols].sort_values(["ID Grupo Duplicado", "Fecha"]), use_container_width=True, hide_index=True)
        if ctx["rol"] == "admin":
            dec = json.loads(DECISIONES.read_text(encoding="utf-8")) if DECISIONES.exists() else {}
            with st.form("decidir"):
                gid = st.selectbox("Grupo", sorted(pend["ID Grupo Duplicado"].unique()))
                op = st.radio("Decisión", ["Mantener ambos (personas distintas)", "Unificar (misma persona)"], horizontal=True)
                if st.form_submit_button("Registrar decisión"):
                    dec[gid] = {"decision": op, "usuario": ctx["usuario"], "fecha": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}
                    DECISIONES.write_text(json.dumps(dec, ensure_ascii=False, indent=2), encoding="utf-8")
                    st.success(f"Decisión registrada para {gid}.")
            st.caption("Las decisiones se guardan en data/decisiones_operador.json. Incorporarlas a las reglas del ETL (etl_unificado_maestro.py) es un paso manual.")
    with st.expander(f"Auto-consolidados y auditados ({len(g) - len(pend)} filas)"):
        st.dataframe(g[g["Estado de Revisión"] != nucleo.DUDA][cols].sort_values(["ID Grupo Duplicado", "Fecha"]),
                     use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------- Archivos Excel
def archivos(d, ctx):
    st.title("📁 Archivos Excel del Drive")
    st.caption("Resúmenes publicados desde Google Drive. Podés navegarlos, editarlos temporalmente y descargar tu versión (el original no se modifica).")
    archivos = sorted(nucleo.EXCEL_DIR.glob("*.xlsx"))
    if not archivos:
        st.info("Aún no hay Excel sincronizados. Ejecutá sincronizar_datos.py.")
        return
    nombre = st.selectbox("Archivo", [a.name for a in archivos])
    ruta = nucleo.EXCEL_DIR / nombre
    hojas = pd.ExcelFile(ruta).sheet_names
    hoja = st.selectbox("Hoja", hojas)
    df = pd.read_excel(ruta, sheet_name=hoja, header=None)
    if ctx["rol"] != "admin":
        st.info("Los nombres de fallecidos solo son visibles para administradores.")
        df = df.apply(lambda c: c.map(lambda x: "•••" if isinstance(x, str) and any(k in x for k in ["Q.E.P.D", "QEPD"]) else x))
    editable = ctx["rol"] == "admin" and st.toggle("Modo edición (temporal)")
    if editable:
        df = st.data_editor(df, num_rows="dynamic", use_container_width=True, height=520)
    else:
        st.dataframe(df, use_container_width=True, height=520)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False, sheet_name=hoja[:31])
    st.download_button("⬇️ Descargar esta hoja (Excel)", buf.getvalue(), f"{ruta.stem}_{hoja[:20]}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if ctx["rol"] == "admin":
        st.download_button("⬇️ Descargar archivo original completo", ruta.read_bytes(), nombre)


# ----------------------------------------------------------------------------- Informes
def informe(d, ctx):
    st.title("🖨️ Informes para presentar")
    if d.empty:
        st.warning("No hay datos con los filtros elegidos.")
        return
    desde, hasta = d["Fecha"].min(), d["Fecha"].max()
    periodo = f"{desde:%d/%m/%Y} a {hasta:%d/%m/%Y}"
    titulo = st.text_input("Título", "Informe de Mercado Funerario - Tucumán")
    st.write(f"Se usarán los filtros actuales del panel lateral — período {periodo}, {len(d):,} servicios.".replace(",", "."))
    c1, c2 = st.columns(2)
    if c1.button("Generar PDF", use_container_width=True):
        st.session_state["pdf"] = informes.generar_pdf(d, titulo, periodo, ctx["semaforo"])
    if c2.button("Generar Excel", use_container_width=True):
        st.session_state["xls"] = informes.generar_excel(d, ocultar_nombres=ctx["rol"] != "admin")
    if "pdf" in st.session_state:
        c1.download_button("⬇️ Descargar PDF", st.session_state["pdf"], "informe_mercado_funerario.pdf", "application/pdf", use_container_width=True)
    if "xls" in st.session_state:
        c2.download_button("⬇️ Descargar Excel", st.session_state["xls"], "informe_mercado_funerario.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)


# ----------------------------------------------------------------------------- Administración
def administracion(d, ctx):
    st.title("⚙️ Administración del Sistema")
    if ctx["rol"] != "admin":
        st.error("Acceso restringido: esta sección está reservada exclusivamente para Administradores.")
        return

    if auth.usa_clave_inicial():
        st.warning("⚠️ El usuario `admin` todavía utiliza la clave inicial por defecto (`tucuman2026`). Se recomienda cambiarla desde la sección inferior.")

    tab_pendientes, tab_usuarios, tab_smtp, tab_datos = st.tabs([
        "📬 Solicitudes Pendientes",
        "👥 Usuarios Activos",
        "📧 Servidor de Correo (SMTP)",
        "🔄 Datos y Scrapers",
    ])

    # --------------------------------------------------------- TAB 1: PENDIENTES
    with tab_pendientes:
        st.subheader("Bandeja de Aprobación de Nuevos Registros")
        pendientes = auth.listar_pendientes()
        if not pendientes:
            st.info("No hay solicitudes pendientes de aprobación en este momento. Cuando un usuario solicite acceso con su correo, aparecerá aquí.")
        else:
            st.dataframe(pd.DataFrame(pendientes), hide_index=True, use_container_width=True)
            st.markdown("---")
            col1, col2 = st.columns([1.5, 1])
            with col1:
                em_sel = st.selectbox("Seleccionar correo a autorizar:", [p["email"] for p in pendientes])
                rol_sel = st.selectbox("Asignar Rol al autorizar:", auth.ROLES, index=2, help="Lector: solo lectura de gráficos. Operador: acceso a Sala de Revisión. Admin: control total.")
            with col2:
                st.write("")
                st.write("")
                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    if st.button("🟢 Autorizar Cuenta", use_container_width=True):
                        ok, msg = auth.aprobar_usuario(em_sel, rol_sel)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                with col_btn2:
                    if st.button("🔴 Rechazar", use_container_width=True):
                        ok, msg = auth.rechazar_usuario(em_sel)
                        if ok:
                            st.warning(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    # --------------------------------------------------------- TAB 2: USUARIOS ACTIVOS
    with tab_usuarios:
        st.subheader("Gestión de Usuarios Habilitados")
        activos = auth.listar_activos()
        df_activos = pd.DataFrame(activos)
        st.dataframe(df_activos, hide_index=True, use_container_width=True)

        st.markdown("---")
        col_u1, col_u2 = st.columns([1, 1])

        with col_u1:
            st.markdown("#### Modificar Rol o Resetear Clave")
            u_mod = st.selectbox("Seleccionar cuenta / correo:", [u["email_o_usuario"] for u in activos], key="u_mod")
            nuevo_rol = st.selectbox("Nuevo Rol:", auth.ROLES, key="nuevo_rol")
            if st.button("Guardar Cambio de Rol"):
                if auth.modificar_rol(u_mod, nuevo_rol):
                    st.success(f"Rol de {u_mod} actualizado a '{nuevo_rol}'.")
                    st.rerun()
                else:
                    st.error("No se pudo actualizar el rol.")

            with st.expander("🔑 Restablecer contraseña de este usuario"):
                nueva_clave_admin = st.text_input("Nueva contraseña temporal:", type="password", key="pass_reset")
                if st.button("Aplicar Nueva Contraseña"):
                    if len(nueva_clave_admin) < 8:
                        st.warning("La contraseña debe tener al menos 8 caracteres.")
                    elif auth.cambiar_clave_admin(u_mod, nueva_clave_admin):
                        st.success(f"Contraseña actualizada para {u_mod}.")
                    else:
                        st.error("No se pudo cambiar la contraseña.")

        with col_u2:
            st.markdown("#### Dar de Alta Usuario Directamente")
            with st.form("alta_directa"):
                alta_nom = st.text_input("Nombre y Apellido", placeholder="Ej: Roberto Gómez")
                alta_email = st.text_input("Correo Electrónico (será su usuario)", placeholder="roberto@miempresa.com.ar").strip().lower()
                alta_pass = st.text_input("Contraseña", type="password")
                alta_rol = st.selectbox("Rol", auth.ROLES, index=2)
                if st.form_submit_button("Crear y Activar Inmediatamente"):
                    if not alta_email or not alta_pass:
                        st.error("Complete el correo y la contraseña.")
                    elif not auth.validar_email(alta_email):
                        st.error("Formato de correo no válido.")
                    elif len(alta_pass) < 8:
                        st.warning("La contraseña debe tener al menos 8 caracteres.")
                    else:
                        d = auth._leer_datos()
                        d.setdefault("usuarios", {})[alta_email] = auth._registro(
                            alta_pass, alta_rol, nombre=alta_nom, email=alta_email
                        )
                        if auth._guardar_datos(d):
                            st.success(f"Usuario {alta_email} creado y activado.")
                            st.rerun()
                        else:
                            st.error("Error al guardar.")

            st.markdown("#### Eliminar Cuenta")
            borrables = [x["email_o_usuario"] for x in activos if x["email_o_usuario"] != ctx["usuario"]]
            if borrables:
                u_del = st.selectbox("Seleccionar cuenta a borrar:", borrables, key="u_del")
                if st.button("🗑️ Eliminar Usuario Definitivamente"):
                    ok, msg = auth.eliminar_usuario(u_del)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.caption("No hay otros usuarios para eliminar.")

    # --------------------------------------------------------- TAB 3: SERVIDOR SMTP
    with tab_smtp:
        import email_service
        st.subheader("Configuración de Correo Saliente (SMTP)")
        st.caption("Permite que la app envíe códigos de recuperación y avisos de aprobación a cualquier correo (Gmail, Outlook, servidores corporativos propios, etc.).")

        cfg = email_service.cargar_config_smtp()

        with st.form("form_smtp"):
            col_s1, col_s2 = st.columns([2, 1])
            with col_s1:
                servidor = st.text_input("Servidor SMTP (Host)", value=cfg.get("servidor", ""), placeholder="Ej: smtp.gmail.com, mail.miempresa.com, smtp.office365.com")
            with col_s2:
                puerto = st.number_input("Puerto SMTP", value=int(cfg.get("puerto", 587)), min_value=1, max_value=65535)

            col_s3, col_s4 = st.columns([1, 1])
            with col_s3:
                usuario_smtp = st.text_input("Usuario SMTP / Correo", value=cfg.get("usuario", ""), placeholder="notificaciones@miempresa.com")
            with col_s4:
                password_smtp = st.text_input("Contraseña SMTP / App Password", value=cfg.get("password", ""), type="password")

            col_s5, col_s6 = st.columns([1, 1])
            with col_s5:
                remitente = st.text_input("Nombre / Casilla Remitente (opcional)", value=cfg.get("remitente", ""), placeholder="Mercado Funerario <avisos@miempresa.com>")
            with col_s6:
                usar_tls = st.checkbox("Usar STARTTLS (Recomendado para puerto 587)", value=cfg.get("usar_tls", True))
                activo = st.checkbox("✅ Activar envío de correos reales", value=cfg.get("activo", False), help="Si está desactivado, el sistema funciona en modo simulación/contingencia segura.")

            if st.form_submit_button("💾 Guardar Configuración SMTP", use_container_width=True):
                nueva_cfg = {
                    "servidor": servidor.strip(),
                    "puerto": int(puerto),
                    "usuario": usuario_smtp.strip(),
                    "password": password_smtp.strip(),
                    "remitente": remitente.strip(),
                    "usar_tls": usar_tls,
                    "activo": activo,
                }
                if email_service.guardar_config_smtp(nueva_cfg):
                    st.success("Configuración SMTP guardada correctamente.")
                    st.rerun()
                else:
                    st.error("Error al guardar la configuración.")

        st.markdown("#### 🧪 Probar Conexión SMTP")
        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            dest_test = st.text_input("Enviar correo de prueba a:", placeholder="tu.correo@cualquierdominio.com")
        with col_t2:
            st.write("")
            st.write("")
            if st.button("Enviar Correo de Prueba", use_container_width=True):
                if not dest_test:
                    st.warning("Ingresa un correo destinatario para la prueba.")
                else:
                    with st.spinner("Conectando y enviando correo..."):
                        ok, msg = email_service.probar_conexion(cfg, dest_test)
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")

    # --------------------------------------------------------- TAB 4: DATOS Y SCRAPERS
    with tab_datos:
        st.subheader("Actualización de Datos")
        import subprocess
        bat = nucleo.APP_DIR / "actualizar_todo.bat"
        if bat.exists():
            if st.button("🔄 Ejecutar Scrapers + ETL + Sincronización"):
                with st.spinner("Ejecutando scrapers y pipeline... puede tardar unos minutos"):
                    r = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True, encoding="utf-8", errors="ignore")
                st.code((r.stdout or "")[-3000:] or "sin salida")
                st.cache_data.clear()
        if st.button("♻️ Recargar datos en pantalla (limpiar caché)"):
            st.cache_data.clear()
            st.rerun()

