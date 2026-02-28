"""
database.py — SQLite para registro de postulaciones
"""
import sqlite3
from datetime import datetime
from config import DB_PATH


def inicializar_db():
    """Crea las tablas si no existen."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS postulaciones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            oferta_id   TEXT    UNIQUE,
            titulo      TEXT,
            empresa     TEXT,
            url         TEXT,
            estado      TEXT DEFAULT 'pendiente',
            fecha       TEXT,
            respuestas  TEXT
        )
    """)
    conn.commit()
    conn.close()


def ya_postule(oferta_id: str) -> bool:
    """Devuelve True si ya postulé a esta oferta."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM postulaciones WHERE oferta_id = ?", (oferta_id,))
    existe = c.fetchone() is not None
    conn.close()
    return existe


def registrar_postulacion(oferta_id: str, titulo: str, empresa: str,
                           url: str, estado: str, respuestas: str = ""):
    """Registra una postulación en la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO postulaciones
        (oferta_id, titulo, empresa, url, estado, fecha, respuestas)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (oferta_id, titulo, empresa, url, estado,
          datetime.now().strftime("%Y-%m-%d %H:%M"), respuestas))
    conn.commit()
    conn.close()


def listar_postulaciones() -> list[dict]:
    """Devuelve todas las postulaciones registradas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM postulaciones ORDER BY fecha DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def total_postulaciones() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM postulaciones WHERE estado='enviada'")
    total = c.fetchone()[0]
    conn.close()
    return total
