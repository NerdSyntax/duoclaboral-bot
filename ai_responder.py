"""
ai_responder.py — Motor de IA basado en Groq (Llama 3)
Responde preguntas de postulación ultra rápido.
"""
import json
import time
from groq import Groq
from config import GROQ_API_KEY, cargar_perfil

import httpx
from limit_tracker import guardar_limites

_client = None
_perfil = None


def _on_response(response: httpx.Response):
    """Callback invocado por httpx para extraer del rate limit."""
    guardar_limites(response.headers)

def _get_client():
    global _client
    if _client is None:
        http_client = httpx.Client(event_hooks={'response': [_on_response]})
        _client = Groq(api_key=GROQ_API_KEY, http_client=http_client)
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
- RUT: {perfil.get('rut', '21687322-K')}
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
1. REGLA ESTRICTA 1 (Práctica/Horas): Si preguntan por "horas", "práctica", "¿Cuántas horas...?" responde EXACTAMENTE: "Actualmente busco una práctica para aprender y ganar experiencia en el rubro, las horas pueden ser negociables según los requerimientos de la empresa."
2. REGLA ESTRICTA 2 (Seguro): Si preguntan por "seguro escolar" o "seguro de salud" responde EXACTAMENTE: "Sí, Duoc UC cuenta con un seguro estudiantil que me cubre completamente durante el transcurso de la carrera ante cualquier eventualidad médica."
3. REGLA ESTRICTA 3 (Personalidad): JAMÁS digas "el perfil del candidato", "no se proporciona", "no tengo esta información". Si no sabes algo, responde de forma adaptable y natural.
4. REGLA ESTRICTA 4 (Inglés): Si preguntan por "inglés", "idioma", "english" responde EXACTAMENTE: "Poseo un nivel intermedio de inglés, me desenvuelvo con lectura técnica y comunicación básica en el idioma."
5. REGLA ESTRICTA 5 (Excel): Si preguntan por "Excel", "planilla", nivel Excel responde EXACTAMENTE: "Cuento con conocimientos intermedios-básicos en Excel: manejo filtros, gráficos, tablas dinámicas y fórmulas básicas. Además tengo nociones de Power BI."
6. REGLA ESTRICTA 6 (Horario/Disponibilidad): Si preguntan por un horario específico, disponibilidad de días/horas, o jornada de trabajo, responde EXACTAMENTE: "Actualmente me encuentro cursando mi carrera en Duoc UC y mi disponibilidad horaria puede variar. Para coordinar horarios específicos, te invito a contactarme directamente por correo a jose.oporto.va@gmail.com o por WhatsApp al +56944399872."
7. REGLA ESTRICTA 7 (Variedad al no saber): Cuando no tengas experiencia con una herramienta o tecnología específica, NUNCA uses la misma frase dos veces en el mismo formulario. Varía la forma de expresar adaptabilidad usando diferentes expresiones como:
   - "Aunque no he trabajado directamente con [tecnología], tengo una base sólida en tecnologías similares y aprendo rápido."
   - "No tengo experiencia práctica en [tecnología], pero cuento con la capacidad para adaptarme y aprenderla en poco tiempo."
   - "Si bien no he utilizado [tecnología] en contextos laborales, manejo conceptos relacionados y estoy abierto a capacitarme."
   - "Mi experiencia con [tecnología] es básica, pero me comprometo a desarrollar ese conocimiento según las necesidades del equipo."
   Elige la variación que suene más natural para esa pregunta específica.
8. REGLA ESTRICTA 8 (RUT): Si preguntan por "RUT", "Rut", "rut", "número de identificación", "Cédula" responde EXACTAMENTE: "21687322-K"
9. Máximo 2 oraciones. Sin introducciones, saludos, despedidas ni comillas. Solo la respuesta directa.
10. Cero emojis.

PREGUNTA DE LA EMPRESA:
{pregunta}

TU RESPUESTA COMO JOSÉ OPORTO:"""

    modelos_fallback = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it"
    ]

    for modelo in modelos_fallback:
        for intento in range(2):
            try:
                # Pausa mínima (Groq es mucho más noble con los límites básicos)
                time.sleep(1.5)
                
                client = _get_client()
                chat_completion = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=modelo,
                    temperature=0.85,
                    max_tokens=256
                )
                return chat_completion.choices[0].message.content.strip()
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg:
                    print(f"    ⏳ Límite de solicitudes (429) con modelo {modelo}. Intentando con otro si es posible...")
                    time.sleep(2)
                    break # Salta al siguiente modelo
                if "403" in err_msg:
                    print("    ❌ Error 403 - Acceso prohibido (revisa tu API KEY de Groq). Usando respuesta de respaldo.")
                    return "Cuento con las habilidades y disposición para integrarme rápidamente al equipo y aportar valor desde el primer día."
                
                print(f"    ⚠️ Error en IA: {e}")
                time.sleep(2)
                
    return "Disponible para ampliar cualquier detalle sobre mi perfil en una entrevista personal."


def elegir_opcion_select(pregunta: str, opciones: list, descripcion_oferta: str = "") -> str:
    """
    Dada una pregunta de formulario y una lista de opciones disponibles en un <select>,
    usa la IA para elegir la opción más adecuada según el perfil del candidato.

    Args:
        pregunta: Texto de la pregunta/label del campo
        opciones: Lista de strings con las opciones disponibles (valor visible)
        descripcion_oferta: Descripción de la oferta para contexto

    Returns:
        El texto exacto de la opción elegida (para usar con select_option(label=...))
    """
    if not opciones:
        return ""

    # Si solo hay 1 opción real (además del placeholder), retornamos esa directamente
    opciones_reales = [o for o in opciones if o.lower() not in (
        "", "selecciona una opción", "select an option", "seleccione", "-- selecciona --"
    )]
    if len(opciones_reales) == 1:
        return opciones_reales[0]

    perfil = _get_perfil()
    contexto = _construir_contexto_perfil(perfil)

    opciones_str = "\n".join(f"  - \"{o}\"" for o in opciones_reales)

    prompt = f"""Eres José Oporto, estudiante de Ingeniería Informática postulando a un trabajo.
Dado tu perfil y la siguiente pregunta de un formulario de postulación,
elige la opción MÁS ADECUADA de la lista proporcionada.

{contexto}

OFERTA DE TRABAJO:
{descripcion_oferta[:500] if descripcion_oferta else "(General)"}

PREGUNTA DEL FORMULARIO: {pregunta}

OPCIONES DISPONIBLES:
{opciones_str}

INSTRUCCIONES:
- Si la pregunta es Sí/No (o Yes/No): elige Sí/Yes si tienes la habilidad, No si claramente no la tienes.
- Para experiencia con tecnologías desconocidas (SAP, ERP específico, herramientas muy especializadas): elige No.
- Para tecnologías que sí manejas (Python, Git, HTML, soporte, Windows, Office): elige Sí/Yes.
- Responde ÚNICAMENTE con el JSON: {{"opcion": "TEXTO EXACTO DE LA OPCIÓN ELEGIDA"}}
- El texto debe ser EXACTAMENTE uno de los valores de la lista de opciones.

JSON:"""

    modelos = ["llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]
    for modelo in modelos:
        try:
            time.sleep(1.0)
            client = _get_client()
            chat = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=modelo,
                temperature=0.0,
                max_tokens=60,
                response_format={"type": "json_object"}
            )
            text = chat.choices[0].message.content.strip()
            data = json.loads(text)
            elegida = data.get("opcion", "").strip()
            # Validar que la opción elegida existe en la lista
            for op in opciones_reales:
                if op.lower() == elegida.lower():
                    return op
            # Fallback: primer opción real si la IA devuelve algo inválido
            return opciones_reales[0]
        except Exception as e:
            err = str(e)
            if "429" in err:
                time.sleep(1.5)
                continue
            continue

    # Fallback final: primera opción real
    return opciones_reales[0]



def resumir_oferta(descripcion: str) -> str:
    """
    Genera un resumen claro y bien estructurado de la oferta de trabajo.
    Devuelve vietas de: Rol, Funciones principales y Requerimientos clave.
    """
    if not descripcion or len(descripcion.strip()) < 50:
        return "No se encontró descripción detallada para esta oferta."

    desc_completa = descripcion.strip()
    # Limitar a 6000 chars para no exceder el contexto del modelo
    if len(desc_completa) > 6000:
        desc_completa = desc_completa[:6000] + "\n[...texto recortado por longitud...]"

    prompt = f"""Resume esta oferta laboral de forma ESTRUCTURADA, BREVE y SIN REDUNDANCIAS. Usa las siguientes secciones si la información aparece en el texto (si no aparece, omite la sección):

💼 CARGO: (una sola línea exacta del texto)
📝 FUNCIONES: (máximo 3 - 4 funciones reales del texto, separadas por " | ")
🔧 REQUISITOS: (máximo 3 - 4 requisitos o herramientas del texto, separados por " | ")
📅 CONDICIONES: (jornada, lugar, horario si aparece en el texto)

REGLAS ESTRICTAS:
- Solo incluye lo que está literalmente en el texto. Jamas inventes.
- Cada sección en UNA SOLA LÍNEA. Evita oraciones largas.
- Si una sección no tiene información explícita en el texto, NO la incluyas.

--- TEXTO DE LA OFERTA ---
{desc_completa}
--- FIN ---

Resumen:"""

    modelos_fallback = [
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "llama-3.3-70b-versatile"
    ]

    for modelo in modelos_fallback:
        for intento in range(2):
            try:
                time.sleep(1.0)
                client = _get_client()
                chat = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=modelo,
                    temperature=0.3,
                    max_tokens=600
                )
                return chat.choices[0].message.content.strip()
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg:
                    time.sleep(1.5)
                    break
                if intento < 1:
                    time.sleep(3)
                    continue
                return f"(No se pudo generar el resumen: {e})"
    return "(Resumen no disponible)"


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
    modelos_fallback = [
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it" 
    ]

    for modelo in modelos_fallback:
        for intento in range(2):
            try:
                time.sleep(1.0)
                client = _get_client()
                chat_completion = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=modelo,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                text = chat_completion.choices[0].message.content.strip()
                data = json.loads(text)
                return data.get("relevante", True), data.get("razon", "Evaluado correctamente")
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg:
                    time.sleep(1)
                    break
                if intento < 1:
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
