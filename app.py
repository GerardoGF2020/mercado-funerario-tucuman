"""App Mercado Funerario Tucumán — punto de entrada.  Ejecutar:  streamlit run app.py"""
import pandas as pd
import streamlit as st

import auth
import nucleo
import paginas

st.set_page_config(
    page_title="Mercado Funerario Tucumán",
    page_icon="⚰️",
    layout="wide",
    initial_sidebar_state="auto",
)

# Estilos CSS responsivos para móviles y pantallas táctiles
st.markdown("""
<style>
    /* Optimización táctil y móvil */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1.5rem !important;
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
        }
        .stButton>button {
            width: 100% !important;
            min-height: 44px !important;
            font-size: 16px !important;
        }
        .stMetric {
            background: #ffffff;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            margin-bottom: 8px;
        }
    }
</style>
""", unsafe_allow_html=True)

usuario, rol = auth.login()


@st.cache_data(ttl=600, show_spinner="Cargando datos...")
def _base():
    return nucleo.cargar_base()


@st.cache_data(ttl=600)
def _semaforo():
    return nucleo.cargar_semaforo()


base = _base()
if base.empty:
    st.error("No hay datos. Ejecutá sincronizar_datos.py (o actualizar_todo.bat).")
    st.stop()

# ----------------------------------------------------------------- Sidebar y filtros
st.sidebar.markdown(f"👤 **{usuario}** · `{rol.upper()}`")
st.sidebar.caption(f"Datos actualizados: {nucleo.ultima_actualizacion()}")

PAGINAS = {
    "📊 Resumen": paginas.resumen,
    "🏢 Empresas": paginas.empresas,
    "⚰️ Cementerios y cremaciones": paginas.cementerios,
    "⏱️ Picos de demanda": paginas.picos,
    "🏛️ San Agustín (gerencia)": paginas.san_agustin,
    "📈 Comparativas": paginas.comparativas,
    "🔎 Fuentes y calidad": paginas.fuentes,
}

if rol in ("admin", "operador"):
    PAGINAS["🧐 Sala de Revisión"] = paginas.revision

PAGINAS["📁 Archivos Excel"] = paginas.archivos
PAGINAS["🖨️ Informes"] = paginas.informe

if rol == "admin":
    PAGINAS["⚙️ Administración"] = paginas.administracion

pagina = st.sidebar.radio("Sección", list(PAGINAS), label_visibility="collapsed")

st.sidebar.markdown("---")
st.sidebar.markdown("**Filtros**")
solo_limpios = st.sidebar.checkbox("Solo servicios verificados (sin duplicados)", value=True)
fmin, fmax = base["Fecha"].min().date(), base["Fecha"].max().date()
ini_def = max(fmin, pd.Timestamp(f"{nucleo.VENTANA_DESDE}-01").date())
rango = st.sidebar.date_input("Período", (ini_def, fmax), min_value=fmin, max_value=fmax)
emp_sel = st.sidebar.multiselect("Empresas", nucleo.EMPRESAS, default=nucleo.EMPRESAS)
tipos = st.sidebar.multiselect("Tipo de destino", ["Cremación", "Inhumación", nucleo.SIN_DATO],
                               default=["Cremación", "Inhumación", nucleo.SIN_DATO])

d = base.copy()
if solo_limpios:
    d = d[d["Estado de Revisión"] == nucleo.LIMPIO]
if isinstance(rango, tuple) and len(rango) == 2:
    d = d[(d["Fecha"] >= pd.Timestamp(rango[0])) & (d["Fecha"] <= pd.Timestamp(rango[1]))]
d = d[d["Empresa Fúnebre"].isin(emp_sel) & d["Tipo de Destino"].isin(tipos)]
if rol == "lector":
    d = d.drop(columns=["Nombre del Fallecido"], errors="ignore")

if st.sidebar.button("🚪 Cerrar sesión"):
    for k in ["auth_ok", "usuario", "rol", "recup_paso", "recup_target", "recup_codigo_sim"]:
        st.session_state.pop(k, None)
    st.rerun()

ctx = {
    "rol": rol,
    "usuario": usuario,
    "semaforo": _semaforo(),
    "base": base if rol in ("admin", "operador") else base.drop(columns=["Nombre del Fallecido"], errors="ignore"),
}
PAGINAS[pagina](d, ctx)
