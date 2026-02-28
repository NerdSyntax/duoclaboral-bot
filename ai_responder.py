"""
ai_responder.py — Motor de IA basado en Groq (Llama 3)
Responde preguntas de postulación ultra rápido.
"""
import json
import time
from groq import Groq
from config import GROQ_API_KEY, cargar_perfil

_client = None
_perfil = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _get_perfil() -> dict:
    global _perfil
    if _perfil is None:
        _perfil = cargar_perfil()
    return _perfil


def _construir_contexto_perfil(perfil: dict) -> str:
    """Convierte el perfil JSON en texto para el prompt."""
    exp_texto = "\n".join(
        f"  - {e['cargo']} en {e['empresa']} ({e['periodo']}): {e['descripcion']}"
        for e in perfil.get("experiencia_laboral", [])
    )
    edu_texto = "\n".join(
        f"  - {ed['titulo']} en {ed['institucion']} ({ed['estado']})"
        for ed in perfil.get("educacion", [])
    )
    
    habilidades = perfil.get("habilidades", [])
    if isinstance(habilidades, list):
        habilidades_str = ", ".join(habilidades)
    else:
        habilidades_str = str(habilidades)

    return f"""
PERFIL DEL CANDIDATO:
- Nombre: {perfil.get('nombre_completo', 'José Oporto')}
- Email personal: jose.oporto.va@gmail.com
- Teléfono: +56944399872
- Ubicación/Comuna: {perfil.get('ubicacion', 'Santiago')}
- Carrera: {perfil.get('educacion', [{}])[0].get('titulo', 'Informática')}
- Sobre mí/Resumen: {perfil.get('resumen_profesional', '')}
- Habilidades: {habilidades_str}
- Experiencias laborales:
{exp_texto if exp_texto else "  (Sin experiencias previas registradas)"}
- Educación:
{edu_texto if edu_texto else "  (Sin educación registrada)"}
- Disponibilidad: {perfil.get('preferencias', {}).get('disponibilidad', 'Inmediata')}
"""


def responder_pregunta(pregunta: str, descripcion_oferta: str = "") -> str:
    """
    Usa Groq para responder una pregunta personalizada de postulación.

    Args:
        pregunta: La pregunta que hace la empresa
        descripcion_oferta: Texto de la oferta / cargo para contexto

    Returns:
        Respuesta generada por IA (string)
    """
    perfil = _get_perfil()
    contexto = _construir_contexto_perfil(perfil)

    prompt = f"""
Eres José Oporto, un estudiante de Ingeniería Informática. Estás respondiendo preguntas críticas en un formulario de postulación a una oferta de trabajo.
NUNCA actúes como un asistente de IA. Tú ERES el candidato. Responde SIEMPRE en primera persona del singular ("yo", "mi", "soy", "busco").

{contexto}

OFERTA DE TRABAJO A LA QUE POSTULAS:
{descripcion_oferta if descripcion_oferta else "(Oferta general)"}

INSTRUCCIONES CLAVES Y ESTRICTAS:
1. REGLA ESTRICTA 1 (Práctica): Si te preguntan por "horas", "práctica", "¿Cuántas horas exige...?" responde EXACTAMENTE: "Actualmente busco una práctica para aprender y ganar experiencia en el rubro, las horas pueden ser negociables según los requerimientos de la empresa."
2. REGLA ESTRICTA 2 (Seguro): Si te preguntan por "seguro escolar", "seguro de salud", responde EXACTAMENTE: "Sí, Duoc UC cuenta con un seguro estudiantil que me cubre completamente durante el transcurso de la carrera ante cualquier eventualidad médica."
3. REGLA ESTRICTA 3 (Personalidad): JAMÁS digas "el perfil del candidato", "no se proporciona", "no tengo esta información". Si no sabes algo específico, asume una actitud de rápida adaptabilidad. Ejemplo: "No poseo esa herramienta específica actualmente, pero aprenderé rápido según los requerimientos." o "Tengo total disponibilidad para trasladarme o adaptarme a la comuna requerida."
4. Sé directo, seguro y profesional. Máximo 1 o 2 oraciones, ve al grano.
5. NO uses introducciones, saludos, despedidas, ni comillas. Solo entrega la respuesta cruda para pegarla en el formulario de la empresa.
6. Cero emojis.

PREGUNTA DE LA EMPRESA:
{pregunta}

TU RESPUESTA COMO JOSÉ OPORTO:"""

    for intento in range(3):
        try:
            # Pausa mínima (Groq es mucho más noble con los límites básicos)
            time.sleep(1.5)
            
            client = _get_client()
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                max_tokens=256
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg and intento < 2:
                print("    ⏳ Límite de solicitudes rate-limit (429). Reintentando en 6s...")
                time.sleep(6)
                continue
            if "403" in err_msg:
                print("    ❌ Error 403 - Acceso prohibido (revisa tu API KEY de Groq). Usando respuesta de respaldo.")
                return "Cuento con las habilidades y disposición para integrarme rápidamente al equipo y aportar valor desde el primer día."
            
            print(f"    ⚠️ Error en IA: {e}")
            return f"[Error al generar respuesta: {e}]"
    
    return "Disponible para ampliar cualquier detalle sobre mi perfil en una entrevista personal."


def evaluar_oferta_relevancia(titulo: str, descripcion: str) -> tuple[bool, str]:
    """
    Evalúa usando Groq si la oferta es relevante para el perfil.
    Ahora más flexible para no descartar todo por falta de info.
    """
    perfil = _get_perfil()
    resumen = perfil.get("resumen_profesional", "")
    habilidades = ", ".join(perfil.get("habilidades", []))

    descripcion_corta = (descripcion or "")[:1000]
    prompt = f"""
Candidato Resumen: {resumen}
Habilidades: {habilidades}

Oferta Título: {titulo}
Oferta Descripción: {descripcion_corta}

    ¿Esta oferta está relacionada con Informática, Computación, Soporte, Análisis, Redes, Telecomunicaciones o Tecnología en general? 
    Incluso si la descripción es mínima, si el título parece técnico o de oficina/gestión tecnológica, responde true.

Responde UNICAMENTE con este formato JSON:
{{"relevante": true, "razon": "breve explicacion"}} o {{"relevante": false, "razon": "breve explicacion"}}
"""
    for intento in range(3):
        try:
            time.sleep(1.0)
            client = _get_client()
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            text = chat_completion.choices[0].message.content.strip()
            data = json.loads(text)
            return data.get("relevante", True), data.get("razon", "Evaluado correctamente")
        except Exception:
            if intento < 2:
                time.sleep(2)
                continue
            return True, "Asumida como relevante por error técnico"
    
    return True, "Asumida como relevante por defecto"

def probar_conexion() -> str:
    """Prueba rápida para ver autenticación en Groq"""
    try:
        client = _get_client()
        r = client.chat.completions.create(
            messages=[{"role": "user", "content": "Hola"}],
            model="llama-3.1-8b-instant",
            max_tokens=10
        )
        return f"OK: {r.choices[0].message.content}"
    except Exception as e:
        return f"ERROR: {e}"
