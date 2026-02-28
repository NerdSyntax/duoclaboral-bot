"""
config.py — Configuración central del bot
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

# ── Credenciales ──────────────────────────────────────────
DUOC_EMAIL    = os.getenv("DUOC_EMAIL", "")
DUOC_PASSWORD = os.getenv("DUOC_PASSWORD", "")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")

# ── URLs ──────────────────────────────────────────────────
BASE_URL   = "https://duoclaboral.cl"
LOGIN_URL  = "https://duoclaboral.cl/login"
# URL base para buscar ofertas (sin filtros, los agregamos en scraper.py)
OFERTAS_URL = "https://duoclaboral.cl/trabajo/trabajos-en-chile"

# ── Filtros de búsqueda ───────────────────────────────────
FILTROS = {
    "palabras_clave": "informatica soporte analista sistemas computacion programador redes tecnico",
    "tipo_oferta": "",  # Vacío para todas
    "carrera": "Ingeniería en informática",
    "max_postulaciones_por_sesion": 15
}

# ── Directorios ───────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PERFIL_PATH = os.path.join(BASE_DIR, "perfil.json")
DB_PATH     = os.path.join(BASE_DIR, "postulaciones.db")
SESSION_PATH = os.path.join(BASE_DIR, "session_state.json")


def cargar_perfil() -> dict:
    """Carga el perfil del usuario desde perfil.json"""
    with open(PERFIL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def validar_config():
    """Verifica que las variables esenciales estén configuradas."""
    errores = []
    if not DUOC_EMAIL:
        errores.append("DUOC_EMAIL no está configurado en .env")
    if not DUOC_PASSWORD:
        errores.append("DUOC_PASSWORD no está configurado en .env")
    if not GROQ_API_KEY:
        errores.append("GROQ_API_KEY no está configurada en .env")
    if errores:
        raise EnvironmentError("\n".join(errores))
