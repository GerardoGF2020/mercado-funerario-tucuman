"""Autenticación basada exclusivamente en Correo Electrónico (cualquier dominio).
Soporta auto-registro con aprobación obligatoria por Administrador y recuperación autónoma.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import random
import re
import secrets as pysecrets
import shutil
from pathlib import Path
from typing import Optional

import streamlit as st

import email_service

FILE = Path(__file__).resolve().parent / "usuarios.json"
DRIVE_USER_BACKUP = Path(r"C:\Users\g-ger\My Drive\Scrarppping\App_Mercado_Funerario\usuarios.json")
CLAVE_INICIAL = "tucuman2026"
ROLES = ["admin", "operador", "lector"]


def _hash(clave: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(salt_hex), 150_000).hex()


def _registro(clave: str, rol: str, nombre: str = "", email: str = "") -> dict:
    salt = pysecrets.token_hex(16)
    em = email.strip().lower()
    return {
        "nombre": nombre.strip() or "Usuario",
        "email": em,
        "salt": salt,
        "hash": _hash(clave, salt),
        "rol": rol,
        "estado": "activo",
        "fecha_alta": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _secret(nombre: str, defecto=None):
    try:
        return st.secrets.get(nombre, defecto)
    except Exception:
        return defecto


def _sincronizar_drive():
    """Respalda el archivo de usuarios en Google Drive."""
    try:
        if DRIVE_USER_BACKUP.parent.exists() and FILE.exists():
            shutil.copy2(FILE, DRIVE_USER_BACKUP)
    except Exception:
        pass


def _sincronizar_cloud_github(contenido_json_str: str) -> bool:
    """Sincroniza usuarios.json con el repositorio en la nube si hay GITHUB_TOKEN en st.secrets."""
    token = _secret("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPO")
    if not token or not repo:
        return False
    try:
        import base64
        import requests
        url = f"https://api.github.com/repos/{repo}/contents/usuarios.json"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        r = requests.get(url, headers=headers, timeout=5)
        sha = r.json().get("sha") if r.status_code == 200 else None

        payload = {
            "message": "Persistencia de usuarios (Streamlit Cloud)",
            "content": base64.b64encode(contenido_json_str.encode("utf-8")).decode("utf-8"),
        }
        if sha:
            payload["sha"] = sha
        resp = requests.put(url, headers=headers, json=payload, timeout=5)
        return resp.status_code in (200, 201)
    except Exception:
        return False


def _leer_datos() -> dict:
    """Lee y normaliza el archivo usuarios.json (con respaldo cloud si está configurado)."""
    estructura = {"usuarios": {}, "pendientes": {}, "recuperaciones": {}}

    # Si estamos en la nube y FILE no existe, intentar recuperar desde GitHub
    if not FILE.exists():
        token = _secret("GITHUB_TOKEN")
        repo = _secret("GITHUB_REPO")
        if token and repo:
            try:
                import base64
                import requests
                url = f"https://api.github.com/repos/{repo}/contents/usuarios.json"
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    content_b64 = r.json().get("content", "")
                    decoded = base64.b64decode(content_b64).decode("utf-8")
                    FILE.write_text(decoded, encoding="utf-8")
                    return json.loads(decoded)
            except Exception:
                pass

        admin_pass = str(_secret("ADMIN_PASSWORD", CLAVE_INICIAL))
        estructura["usuarios"]["admin"] = _registro(
            admin_pass, "admin", nombre="Administrador", email="admin@mercado-funerario.com"
        )
        _guardar_datos(estructura)
        return estructura

    try:
        raw = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return estructura

    # Compatibilidad con formato antiguo
    if "usuarios" not in raw and isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict) and "hash" in v:
                v.setdefault("nombre", k.capitalize())
                v.setdefault("email", f"{k}@mercado-funerario.com")
                v.setdefault("estado", "activo")
                v.setdefault("fecha_alta", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
                estructura["usuarios"][k.lower()] = v
        _guardar_datos(estructura)
        return estructura

    return raw


def _guardar_datos(d: dict) -> bool:
    """Guarda los datos en disco, Drive y la nube."""
    try:
        txt = json.dumps(d, ensure_ascii=False, indent=2)
        FILE.write_text(txt, encoding="utf-8")
        _sincronizar_drive()
        _sincronizar_cloud_github(txt)
        return True
    except Exception:
        return False


def validar_email(email: str) -> bool:
    """Valida formato general de correo (cualquier proveedor o dominio propio)."""
    patron = r"^[\w\.-]+@[\w\.-]+\.\w{2,}$"
    return bool(re.match(patron, email.strip().lower()))


# ------------------------------------------------------------------ Consultas y Auth
def verificar(email_o_usuario: str, clave: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Verifica credenciales. Devuelve (identificador, rol, nombre, mensaje_error)."""
    term = email_o_usuario.strip().lower()
    if not term or not clave:
        return None, None, None, "Por favor complete su correo electrónico y contraseña."

    d = _leer_datos()

    # 1. Verificar si está en la lista de solicitudes pendientes
    for em, p in d.get("pendientes", {}).items():
        if em == term or p.get("email", "").lower() == term or p.get("usuario", "") == term:
            return None, None, None, f"⏳ La cuenta '{em}' fue registrada pero aún se encuentra PENDIENTE de autorización por el Administrador."

    # 2. Buscar en usuarios activos (por correo o por identificador 'admin')
    target_id = None
    target_data = None
    for u, v in d.get("usuarios", {}).items():
        if u == term or v.get("email", "").lower() == term:
            target_id = u
            target_data = v
            break

    if not target_data:
        return None, None, None, "Correo electrónico o contraseña incorrectos."

    if target_data.get("estado") == "suspendido":
        return None, None, None, "🚫 Esta cuenta se encuentra suspendida. Contacte al Administrador."

    # Validar hash de contraseña
    salt = target_data["salt"]
    if hmac.compare_digest(_hash(clave, salt), target_data["hash"]):
        nombre = target_data.get("nombre", target_id)
        return target_id, target_data["rol"], nombre, None

    return None, None, None, "Correo electrónico o contraseña incorrectos."


def usa_clave_inicial(usuario: str = "admin") -> bool:
    d = _leer_datos()
    c = d.get("usuarios", {}).get(usuario)
    return bool(c) and hmac.compare_digest(_hash(CLAVE_INICIAL, c["salt"]), c["hash"])


# ------------------------------------------------------------------ Auto-Registro con Correo
def solicitar_registro(nombre: str, email: str, clave: str) -> tuple[bool, str]:
    """Crea una solicitud de registro usando exclusivamente el Correo Electrónico."""
    nom = nombre.strip()
    em = email.strip().lower()

    if not nom or not em or not clave:
        return False, "Todos los campos son obligatorios (Nombre, Correo y Contraseña)."

    if not validar_email(em):
        return False, f"El correo '{em}' no tiene un formato válido (ejemplo: usuario@dominio.com)."

    if len(clave) < 8:
        return False, "La contraseña debe tener un mínimo de 8 caracteres."

    d = _leer_datos()

    # Verificar si el correo ya existe en usuarios activos
    for u, val in d.get("usuarios", {}).items():
        if u == em or val.get("email", "").lower() == em:
            return False, f"El correo '{em}' ya está registrado en el sistema. Puedes iniciar sesión o recuperar tu contraseña."

    # Verificar si ya existe en solicitudes pendientes
    for u, val in d.get("pendientes", {}).items():
        if u == em or val.get("email", "").lower() == em:
            return False, f"Ya existe una solicitud pendiente de autorización para el correo '{em}'."

    salt = pysecrets.token_hex(16)
    d.setdefault("pendientes", {})[em] = {
        "nombre": nom,
        "email": em,
        "usuario": em,
        "salt": salt,
        "hash": _hash(clave, salt),
        "fecha_solicitud": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "estado": "pendiente",
    }

    if _guardar_datos(d):
        email_service.enviar_aviso_registro(em, nom, em)
        return True, f"Solicitud registrada exitosamente para {em}. El Administrador debe autorizar tu acceso."

    return False, "Error al registrar la solicitud en el sistema."


# ------------------------------------------------------------------ Gestión de Autorizaciones (Admin)
def listar_pendientes() -> list[dict]:
    d = _leer_datos()
    res = []
    for em, v in d.get("pendientes", {}).items():
        res.append({
            "email": em,
            "nombre": v.get("nombre", em),
            "fecha_solicitud": v.get("fecha_solicitud", "-"),
        })
    return sorted(res, key=lambda x: x["fecha_solicitud"], reverse=True)


def aprobar_usuario(email: str, rol: str = "lector") -> tuple[bool, str]:
    """Autoriza y activa la cuenta del correo pendiente, asignándole su rol."""
    em = email.strip().lower()
    if rol not in ROLES:
        rol = "lector"

    d = _leer_datos()
    if em not in d.get("pendientes", {}):
        return False, f"No se encontró la solicitud de '{em}'."

    p = d["pendientes"].pop(em)
    p["rol"] = rol
    p["estado"] = "activo"
    p["fecha_alta"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    d.setdefault("usuarios", {})[em] = p
    if _guardar_datos(d):
        email_service.enviar_aviso_aprobacion(em, p.get("nombre", em), rol)
        return True, f"Cuenta '{em}' autorizada con éxito con el rol '{rol}'."

    return False, "Error al guardar la autorización."


def rechazar_usuario(email: str) -> tuple[bool, str]:
    """Rechaza y elimina la solicitud pendiente."""
    em = email.strip().lower()
    d = _leer_datos()
    if em in d.get("pendientes", {}):
        del d["pendientes"][em]
        _guardar_datos(d)
        return True, f"Solicitud de '{em}' rechazada y eliminada."
    return False, "Solicitud no encontrada."


def listar_activos() -> list[dict]:
    d = _leer_datos()
    res = []
    for u, v in d.get("usuarios", {}).items():
        res.append({
            "email_o_usuario": u,
            "nombre": v.get("nombre", u),
            "email": v.get("email", u),
            "rol": v.get("rol", "lector"),
            "estado": v.get("estado", "activo"),
            "fecha_alta": v.get("fecha_alta", "-"),
        })
    return sorted(res, key=lambda x: x["email_o_usuario"])


def modificar_rol(identificador: str, nuevo_rol: str) -> bool:
    u = identificador.strip().lower()
    if nuevo_rol not in ROLES:
        return False
    d = _leer_datos()
    if u in d.get("usuarios", {}):
        d["usuarios"][u]["rol"] = nuevo_rol
        return _guardar_datos(d)
    return False


def cambiar_clave_admin(identificador: str, nueva_clave: str) -> bool:
    u = identificador.strip().lower()
    if len(nueva_clave) < 8:
        return False
    d = _leer_datos()
    if u in d.get("usuarios", {}):
        salt = pysecrets.token_hex(16)
        d["usuarios"][u]["salt"] = salt
        d["usuarios"][u]["hash"] = _hash(nueva_clave, salt)
        return _guardar_datos(d)
    return False


def cambiar_mi_clave(usuario_o_email: str, clave_actual: str, nueva_clave: str) -> tuple[bool, str]:
    """Permite a cualquier usuario conectado (admin, operador o lector) cambiar su propia contraseña."""
    term = usuario_o_email.strip().lower()
    if not clave_actual or not nueva_clave:
        return False, "Debe ingresar la contraseña actual y la nueva contraseña."
    if len(nueva_clave) < 8:
        return False, "La nueva contraseña debe tener al menos 8 caracteres."
    if clave_actual == nueva_clave:
        return False, "La nueva contraseña debe ser diferente a la actual."

    d = _leer_datos()
    target_id = None
    target_data = None
    for u, v in d.get("usuarios", {}).items():
        if u == term or v.get("email", "").lower() == term:
            target_id = u
            target_data = v
            break

    if not target_data:
        return False, "Usuario no encontrado en la base."

    # Validar contraseña actual con hash seguro
    salt = target_data["salt"]
    if not hmac.compare_digest(_hash(clave_actual, salt), target_data["hash"]):
        return False, "La contraseña actual ingresada es incorrecta."

    # Actualizar con nuevo salt criptográfico y hash
    nuevo_salt = pysecrets.token_hex(16)
    d["usuarios"][target_id]["salt"] = nuevo_salt
    d["usuarios"][target_id]["hash"] = _hash(nueva_clave, nuevo_salt)
    if _guardar_datos(d):
        return True, "¡Tu contraseña ha sido cambiada con éxito!"

    return False, "Error al guardar la nueva contraseña."


def eliminar_usuario(identificador: str) -> tuple[bool, str]:
    d = _leer_datos()
    u = identificador.strip().lower()
    if u not in d.get("usuarios", {}):
        return False, "Usuario no encontrado."
    admins = [k for k, v in d["usuarios"].items() if v.get("rol") == "admin"]
    if d["usuarios"][u].get("rol") == "admin" and len(admins) <= 1:
        return False, "No se puede eliminar el único Administrador del sistema."
    del d["usuarios"][u]
    _guardar_datos(d)
    return True, f"Usuario '{u}' eliminado correctamente."


# ------------------------------------------------------------------ Recuperación de Clave
def solicitar_recuperacion(email_o_usuario: str) -> tuple[bool, str, Optional[str]]:
    term = email_o_usuario.strip().lower()
    d = _leer_datos()

    target_id = None
    target_email = None
    for u, v in d.get("usuarios", {}).items():
        if u == term or v.get("email", "").lower() == term:
            target_id = u
            target_email = v.get("email", u)
            break

    if not target_id:
        return False, "No se encontró ninguna cuenta activa con ese correo electrónico.", None

    codigo = f"{random.randint(100000, 999999)}"
    ahora = datetime.datetime.now()
    expira = (ahora + datetime.timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    d.setdefault("recuperaciones", {})[target_email] = {
        "usuario": target_id,
        "codigo": codigo,
        "expira": expira,
        "creado": ahora.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _guardar_datos(d)

    ok, estado = email_service.enviar_codigo_recuperacion(target_email, target_id, codigo)
    return True, f"Se despachó un código de verificación a {target_email}.", codigo


def confirmar_recuperacion(email_o_usuario: str, codigo: str, nueva_clave: str) -> tuple[bool, str]:
    term = email_o_usuario.strip().lower()
    cod = codigo.strip()

    if len(nueva_clave) < 8:
        return False, "La nueva contraseña debe tener al menos 8 caracteres."

    d = _leer_datos()
    recuperacion = None
    target_email = None

    for em, rec in d.get("recuperaciones", {}).items():
        if em == term or rec.get("usuario") == term:
            recuperacion = rec
            target_email = em
            break

    if not recuperacion:
        return False, "No hay solicitudes de recuperación activas para ese correo."

    if recuperacion.get("codigo") != cod:
        return False, "El código de verificación de 6 dígitos es incorrecto."

    try:
        expira_dt = datetime.datetime.strptime(recuperacion["expira"], "%Y-%m-%d %H:%M:%S")
        if datetime.datetime.now() > expira_dt:
            return False, "El código de verificación ha expirado (validez 15 minutos). Solicite uno nuevo."
    except Exception:
        pass

    target_id = recuperacion["usuario"]
    if target_id in d.get("usuarios", {}):
        salt = pysecrets.token_hex(16)
        d["usuarios"][target_id]["salt"] = salt
        d["usuarios"][target_id]["hash"] = _hash(nueva_clave, salt)
        del d["recuperaciones"][target_email]
        _guardar_datos(d)
        return True, "¡Contraseña actualizada con éxito! Ya puedes iniciar sesión con tu nueva contraseña."

    return False, "Error al actualizar la contraseña."


# ------------------------------------------------------------------ Pantalla de Login / Portal
def login():
    """Pantalla de acceso con selector visual directo de acción."""
    if st.session_state.get("auth_ok"):
        return st.session_state["usuario"], st.session_state["rol"]

    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("## ⚰️ Mercado Funerario Tucumán")
        st.caption("Plataforma de Inteligencia y Monitoreo del Sector")

        # Selector visual de acción directo y prominente
        opcion = st.radio(
            "Seleccione qué desea hacer:",
            ["🔑 Iniciar Sesión", "📝 Solicitar Cuenta Nueva", "🔄 Olvidé mi Contraseña"],
            horizontal=True,
            label_visibility="collapsed",
        )

        st.markdown("---")

        # --------------------------------------------------------- 1: INICIAR SESIÓN
        if opcion == "🔑 Iniciar Sesión":
            st.subheader("Ingreso al Sistema")
            bloqueado = st.session_state.get("intentos", 0) >= 5
            with st.form("form_login"):
                u = st.text_input("Correo Electrónico (o usuario admin)", placeholder="ejemplo@correo.com", key="login_email")
                p = st.text_input("Contraseña", type="password", key="login_pass")
                submit = st.form_submit_button("Ingresar", use_container_width=True, disabled=bloqueado)

            if bloqueado:
                st.error("🔒 Demasiados intentos fallidos. Espere unos momentos y recargue la página.")
            elif submit:
                usuario_ok, rol_ok, nombre_ok, error = verificar(u, p)
                if usuario_ok:
                    st.session_state.update(auth_ok=True, usuario=usuario_ok, rol=rol_ok, nombre=nombre_ok, intentos=0)
                    st.rerun()
                else:
                    st.session_state["intentos"] = st.session_state.get("intentos", 0) + 1
                    st.error(error)

        # --------------------------------------------------------- 2: SOLICITAR CUENTA NUEVA
        elif opcion == "📝 Solicitar Cuenta Nueva":
            st.subheader("Registro de Nuevo Usuario")
            st.info("💡 **Tu Correo Electrónico será tu usuario de acceso**. Admite cualquier proveedor (@gmail, @outlook, correos corporativos de la empresa, etc.). Por seguridad, el Administrador debe autorizar tu acceso.")

            with st.form("form_registro_correo"):
                reg_nombre = st.text_input("Nombre y Apellido", placeholder="Ej. Juan Pérez")
                reg_email = st.text_input("Correo Electrónico (será tu usuario)", placeholder="juan.perez@miempresa.com.ar").strip().lower()
                reg_pass1 = st.text_input("Contraseña deseada (mínimo 8 caracteres)", type="password")
                reg_pass2 = st.text_input("Confirmar Contraseña", type="password")
                reg_submit = st.form_submit_button("Solicitar Acceso al Administrador", use_container_width=True)

            if reg_submit:
                if reg_pass1 != reg_pass2:
                    st.warning("Las contraseñas no coinciden.")
                else:
                    ok, msg = solicitar_registro(reg_nombre, reg_email, reg_pass1)
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(msg)

        # --------------------------------------------------------- 3: RECUPERAR CONTRASEÑA
        elif opcion == "🔄 Olvidé mi Contraseña":
            st.subheader("Recuperación de Contraseña")
            paso = st.session_state.get("recup_paso", 1)

            if paso == 1:
                st.caption("Ingresa tu correo registrado para recibir un código de seguridad de 6 dígitos.")
                with st.form("form_recup_paso1"):
                    rec_term = st.text_input("Correo Electrónico registrado", placeholder="tu.correo@dominio.com").strip().lower()
                    rec_submit1 = st.form_submit_button("Enviar Código de Verificación", use_container_width=True)

                if rec_submit1:
                    ok, msg, codigo = solicitar_recuperacion(rec_term)
                    if ok:
                        st.session_state["recup_target"] = rec_term
                        st.session_state["recup_paso"] = 2
                        st.session_state["recup_codigo_sim"] = codigo
                        st.success(f"📧 {msg}")
                        st.rerun()
                    else:
                        st.error(msg)

            elif paso == 2:
                rec_target = st.session_state.get("recup_target", "")
                st.info(f"Ingresa el código enviado a: **{rec_target}**")

                cfg = email_service.cargar_config_smtp()
                if not cfg.get("activo"):
                    cod_sim = st.session_state.get("recup_codigo_sim", "")
                    st.caption(f"ℹ️ *(Modo local activo: Tu código es `{cod_sim}`)*")

                with st.form("form_recup_paso2"):
                    cod_ingresado = st.text_input("Código de 6 dígitos", max_chars=6)
                    nueva_p1 = st.text_input("Nueva Contraseña (mínimo 8 caracteres)", type="password")
                    nueva_p2 = st.text_input("Confirmar Nueva Contraseña", type="password")
                    col_b1, col_b2 = st.columns([1, 1])
                    with col_b1:
                        confirm_sub = st.form_submit_button("Restablecer Contraseña", use_container_width=True)
                    with col_b2:
                        cancel_sub = st.form_submit_button("Cancelar", use_container_width=True)

                if cancel_sub:
                    st.session_state["recup_paso"] = 1
                    st.rerun()

                if confirm_sub:
                    if nueva_p1 != nueva_p2:
                        st.warning("Las contraseñas no coinciden.")
                    else:
                        ok, msg = confirmar_recuperacion(rec_target, cod_ingresado, nueva_p1)
                        if ok:
                            st.success(f"🎉 {msg}")
                            st.session_state["recup_paso"] = 1
                            st.session_state.pop("recup_target", None)
                        else:
                            st.error(msg)

    st.stop()
