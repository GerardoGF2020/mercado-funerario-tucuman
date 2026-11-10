"""Módulo de servicio de correo electrónico (SMTP multiproveedor y modo simulación/contingencia).

Soporta cualquier servidor SMTP: Gmail, Outlook, Microsoft 365, cPanel, Webmail, SendGrid, etc.
Si no hay credenciales SMTP configuradas, opera en modo de contingencia/simulación segura,
registrando el código para que el usuario pueda avanzar inmediatamente sin bloqueos.
"""
from __future__ import annotations

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config_smtp.json"
OUTBOX_FILE = BASE_DIR / "data" / "notificaciones_salientes.json"


def cargar_config_smtp() -> dict:
    """Carga la configuración SMTP guardada o desde st.secrets (Streamlit Cloud)."""
    defaults = {
        "servidor": "",
        "puerto": 587,
        "usuario": "",
        "password": "",
        "usar_tls": True,
        "remitente": "",
        "activo": False,
    }
    # 1. Intentar leer desde secrets de Streamlit Cloud
    try:
        import streamlit as st
        if "smtp" in st.secrets:
            s = st.secrets["smtp"]
            defaults.update({
                "servidor": str(s.get("server", s.get("servidor", ""))),
                "puerto": int(s.get("port", s.get("puerto", 587))),
                "usuario": str(s.get("user", s.get("usuario", ""))),
                "password": str(s.get("password", "")),
                "remitente": str(s.get("sender", s.get("remitente", ""))),
                "usar_tls": bool(s.get("tls", s.get("usar_tls", True))),
                "activo": bool(s.get("active", s.get("activo", True))),
            })
            return defaults
    except Exception:
        pass

    # 2. Archivo local de configuración
    if CONFIG_FILE.exists():
        try:
            d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            defaults.update(d)
        except Exception:
            pass
    return defaults


def guardar_config_smtp(cfg: dict) -> bool:
    """Guarda la configuración SMTP."""
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def _registrar_en_outbox(tipo: str, destinatario: str, asunto: str, codigo: Optional[str] = None):
    """Guarda un registro de la notificación saliente para auditoría o simulación."""
    try:
        OUTBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        registros = []
        if OUTBOX_FILE.exists():
            try:
                registros = json.loads(OUTBOX_FILE.read_text(encoding="utf-8"))
            except Exception:
                registros = []
        import datetime
        registros.append({
            "fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tipo": tipo,
            "destinatario": destinatario,
            "asunto": asunto,
            "codigo": codigo,
        })
        # mantener los últimos 100
        OUTBOX_FILE.write_text(json.dumps(registros[-100:], indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def probar_conexion(cfg: dict, destinatario_prueba: str) -> tuple[bool, str]:
    """Prueba la conexión enviando un correo de verificación."""
    servidor = cfg.get("servidor", "").strip()
    puerto = int(cfg.get("puerto", 587))
    usuario = cfg.get("usuario", "").strip()
    password = cfg.get("password", "").strip()
    remitente = cfg.get("remitente", "").strip() or usuario
    usar_tls = cfg.get("usar_tls", True)

    if not servidor or not usuario or not password:
        return False, "Faltan completar campos obligatorios (servidor, usuario o contraseña)."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🧪 Prueba de Configuración - Mercado Funerario Tucumán"
        msg["From"] = remitente
        msg["To"] = destinatario_prueba

        texto = "Este es un correo de prueba para verificar que el servicio SMTP funciona correctamente."
        html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2 style="color: #2b5797;">⚰️ Mercado Funerario Tucumán</h2>
            <p>Este es un correo de prueba enviado desde el panel de administración.</p>
            <p><strong>Estado:</strong> ✅ Conexión SMTP exitosa.</p>
        </div>
        """
        msg.attach(MIMEText(texto, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        if puerto == 465:
            server = smtplib.SMTP_SSL(servidor, puerto, timeout=10)
        else:
            server = smtplib.SMTP(servidor, puerto, timeout=10)
            if usar_tls:
                server.starttls()

        server.login(usuario, password)
        server.sendmail(remitente, [destinatario_prueba], msg.as_string())
        server.quit()
        return True, f"Correo de prueba enviado con éxito a {destinatario_prueba}."
    except Exception as e:
        return False, f"Error al conectar con el servidor SMTP: {str(e)}"


def enviar_email(destinatario: str, asunto: str, cuerpo_html: str, cuerpo_texto: str, codigo: Optional[str] = None) -> tuple[bool, str]:
    """Envía un email vía SMTP. Si no está configurado, usa el modo simulación."""
    cfg = cargar_config_smtp()
    _registrar_en_outbox("general", destinatario, asunto, codigo)

    if not cfg.get("activo") or not cfg.get("servidor"):
        # Modo simulación activa
        return True, "MODO_SIMULACION"

    servidor = cfg.get("servidor", "").strip()
    puerto = int(cfg.get("puerto", 587))
    usuario = cfg.get("usuario", "").strip()
    password = cfg.get("password", "").strip()
    remitente = cfg.get("remitente", "").strip() or usuario
    usar_tls = cfg.get("usar_tls", True)

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = destinatario

        msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        if puerto == 465:
            server = smtplib.SMTP_SSL(servidor, puerto, timeout=10)
        else:
            server = smtplib.SMTP(servidor, puerto, timeout=10)
            if usar_tls:
                server.starttls()

        server.login(usuario, password)
        server.sendmail(remitente, [destinatario], msg.as_string())
        server.quit()
        return True, "ENVIADO_EXITOSO"
    except Exception as e:
        # Si falló el envío por red, registramos pero no rompemos el flujo
        return False, f"Error SMTP: {str(e)}"


def enviar_codigo_recuperacion(email: str, usuario: str, codigo: str) -> tuple[bool, str]:
    """Envía el código de 6 dígitos para recuperación de contraseña."""
    asunto = f"🔑 Código de Recuperación de Contraseña: {codigo}"
    cuerpo_texto = f"""Hola {usuario},
Has solicitado restablecer tu contraseña en Mercado Funerario Tucumán.
Tu código de seguridad temporal es: {codigo}
Este código tiene una vigencia de 15 minutos. Si no solicitaste este cambio, puedes ignorar este mensaje.
"""
    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: auto; padding: 25px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2b5797; margin-bottom: 5px;">⚰️ Mercado Funerario Tucumán</h2>
        <p style="color: #666; font-size: 14px;">Recuperación de Contraseña</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
        <p>Hola <strong>{usuario}</strong>,</p>
        <p>Recibimos una solicitud para restablecer tu contraseña. Utiliza el siguiente código de verificación:</p>
        <div style="background-color: #f0f4f8; padding: 15px; border-radius: 6px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #1e3c72;">{codigo}</span>
        </div>
        <p style="font-size: 13px; color: #888;">⏱️ Este código vence en <strong>15 minutos</strong>. Si tú no hiciste esta solicitud, puedes desestimar este correo con total tranquilidad.</p>
    </div>
    """
    _registrar_en_outbox("recuperacion", email, asunto, codigo)
    return enviar_email(email, asunto, cuerpo_html, cuerpo_texto, codigo=codigo)


def enviar_aviso_registro(email: str, nombre: str, usuario: str) -> tuple[bool, str]:
    """Envía confirmación al usuario de que su solicitud fue recibida."""
    asunto = "📝 Solicitud de Registro Recibida - Mercado Funerario Tucumán"
    cuerpo_texto = f"""Hola {nombre} ({usuario}),
Hemos recibido tu solicitud de registro en la plataforma de Mercado Funerario Tucumán.
Por motivos de seguridad, tu cuenta se encuentra pendiente de autorización por parte de un Administrador.
Te notificaremos en cuanto tu acceso sea activado.
"""
    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: auto; padding: 25px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2b5797;">⚰️ Mercado Funerario Tucumán</h2>
        <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
        <p>Hola <strong>{nombre}</strong> (usuario: <code>{usuario}</code>),</p>
        <p>Tu solicitud de registro ha sido registrada correctamente.</p>
        <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 12px; margin: 15px 0;">
            <strong>Estado:</strong> 🟡 Pendiente de Aprobación por el Administrador.
        </div>
        <p style="font-size: 14px; color: #555;">Un administrador revisará tu solicitud para habilitar tu cuenta con el rol correspondiente.</p>
    </div>
    """
    return enviar_email(email, asunto, cuerpo_html, cuerpo_texto)


def enviar_aviso_aprobacion(email: str, usuario: str, rol: str) -> tuple[bool, str]:
    """Notifica al usuario cuando su cuenta fue aprobada."""
    asunto = "✅ Tu cuenta ha sido APROBADA - Mercado Funerario Tucumán"
    cuerpo_texto = f"""Hola {usuario},
Tu cuenta ha sido aprobada por el Administrador con el rol: {rol.upper()}.
Ya puedes ingresar al sistema con tu usuario y contraseña.
"""
    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; margin: auto; padding: 25px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2b5797;">⚰️ Mercado Funerario Tucumán</h2>
        <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
        <p>Hola <strong>{usuario}</strong>,</p>
        <div style="background-color: #d4edda; border-left: 4px solid #28a745; padding: 12px; margin: 15px 0;">
            <strong>¡Acceso Habilitado!</strong> Tu cuenta ha sido activada con el rol: <strong>{rol.upper()}</strong>.
        </div>
        <p>Ya puedes iniciar sesión en la plataforma con tus credenciales.</p>
    </div>
    """
    return enviar_email(email, asunto, cuerpo_html, cuerpo_texto)
