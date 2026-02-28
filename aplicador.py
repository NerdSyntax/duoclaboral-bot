"""
aplicador.py — Rellena y envía formularios de postulación en DuocLaboral
"""
import json
import time
import random
from playwright.sync_api import Page
from rich.console import Console
from config import cargar_perfil
from ai_responder import responder_pregunta
from database import ya_postule, registrar_postulacion

console = Console()


def _pausa(min_s=1.0, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))


def _escribir_lento(page: Page, selector: str, texto: str):
    """Escribe texto de forma humana (carácter por carácter con delay)."""
    page.click(selector)
    page.fill(selector, "")
    for char in texto:
        page.type(selector, char, delay=random.randint(30, 80))


def postular_oferta(page: Page, oferta: dict, detalle: dict,
                    modo_revision: bool = True) -> str:
    """
    Rellena y envía el formulario de postulación de una oferta.

    Args:
        page: Instancia de Playwright Page ya logueada
        oferta: Dict con id, titulo, empresa, url
        detalle: Dict con descripcion, preguntas, renta_selector, submit_selector
        modo_revision: Si True, muestra las respuestas antes de enviar y pide confirmación

    Returns:
        Estado final: 'enviada' | 'saltada' | 'error'
    """
    oferta_id = oferta["id"]
    titulo = oferta.get("titulo", "")
    empresa = oferta.get("empresa", "")
    url = oferta.get("url", "")

    # ── 1. Verificar si ya postulé ────────────────────────────────────
    if ya_postule(oferta_id):
        # Ya no debería llegar aquí si main.py lo filtra antes, pero mantenemos por seguridad
        return "duplicado"

    print(f"\n{'='*60}")
    print(f"  💼 [bold yellow]CARGO   :[/bold yellow] {titulo}")
    print(f"  🏢 [bold cyan]EMPRESA :[/bold cyan] {empresa}")
    print(f"  🔗 [dim]LINK OFERTA:[/dim] {url}")
    # Nota: El link de la empresa a veces no está disponible directamente como URL externa
    # pero mostramos la de la postulación que es lo que importa.
    print(f"{'='*60}")

    # Navegar a la oferta
    page.goto(url, timeout=60000)
    _pausa(2, 4)
    
    # ── 1.5 Detección Visual de Duplicación (Doble Seguro) ────────────────
    # A veces redirige o muestra un texto que avisa que ya se postuló
    if page.locator("text='Ya postulaste'").count() > 0 or page.locator("text='Postulado'").count() > 0:
        return "duplicado"
        
    perfil = cargar_perfil()
    respuestas_generadas = []

    # ── 2. Generar respuestas con IA (SI HAY FORMULARIO) ───────────────
    # Validar primero que haya un botón de enviar (o no es un formulario real)
    btn_enviar = page.locator("button#sendApplication.btn.btn-primary.job-apply-btn")
    if btn_enviar.count() == 0:
        # A veces el botón principal de postular inicia un pop-up, probamos ese antes de abortar
        btn_postular_alt = page.locator("button.button-apply, .btn-postular")
        if btn_postular_alt.count() == 0:
            return "error"  # No hay donde postular, salir antes de gastar API

    descripcion = detalle.get("descripcion", "")
    preguntas = detalle.get("preguntas", [])

    if preguntas:
        console.print(f"\n[bold magenta]🤖 IA GENERANDO RESPUESTAS ({len(preguntas)})[/bold magenta]")
        for i, p in enumerate(preguntas):
            label = p.get("label", "Pregunta")
            console.print(f"\n[cyan]───────────────── Pregunta {i+1} ─────────────────[/cyan]")
            console.print(f"[bold white]Texto:[/bold white] {label}")
            console.print("[dim italic]Consultando a la IA...[/dim italic]")
            
            respuesta = responder_pregunta(label, descripcion)
            
            console.print(f"[bold green]Respuesta IA:[/bold green]\n{respuesta}")
            
            respuestas_generadas.append({
                "pregunta": label,
                "respuesta": respuesta,
                "selector": p.get("selector"),
                "indice": p.get("indice", 0),
            })
            _pausa(0.8, 1.8)

    # ── 3. Modo revisión ──────────────────────────────────────────────
    if modo_revision:
        console.print("\n" + "═"*60)
        console.print("  [bold yellow]📋 PANEL DE REVISIÓN FINAL[/bold yellow]")
        console.print("═"*60)
        
        # Renta logic: SIEMPRE 100.000
        console.print(f"  💰 [bold cyan]RENTA SOLICITADA:[/bold cyan] $100.000 (Valor fijo)")

        # Tabla de resumen de respuestas
        for i, r in enumerate(respuestas_generadas):
            console.print(f"\n[bold white]P{i+1}:[/bold white] {r['pregunta'][:100]}...")
            console.print(f"[dim]R:[/dim] {r['respuesta']}")
            
            opcion = input(f"\n  ¿Editar P{i+1}? [e]ditar / [ENTER] ok: ").strip().lower()
            if opcion == 'e':
                console.print("  [yellow]Escribe la nueva respuesta:[/yellow]")
                nueva = input("  > ").strip()
                if nueva:
                    r['respuesta'] = nueva
                    console.print("  [green]✅ OK.[/green]")

        print("\n" + "─"*60)
        confirmacion = input("  ¿Enviar postulación ahora? [s/N]: ").strip().lower()
        if confirmacion != "s":
            print("  ⏭  Postulación descartada.")
            registrar_postulacion(oferta_id, titulo, empresa, url, "saltada",
                                  json.dumps(respuestas_generadas, ensure_ascii=False))
            return "saltada"

        # 4. Rellenar el formulario ──────────────────────────────────────
        try:
            # Ocultar posibles elementos que bloquean el click (IA SOFIA, Cookies, etc.)
            page.evaluate("""
                () => {
                    const selectors = ['flowise-chatbot', '.cookie-consent', '#open_feedback', '.modal-backdrop'];
                    selectors.forEach(sel => {
                        const el = document.querySelector(sel);
                        if (el) el.style.display = 'none';
                    });
                }
            """)

            # ── NUEVO: Si no vemos el formulario, intentar click en botón "Postular" inicial ──
            renta_selector = detalle.get("renta_selector") or \
                "input[placeholder*='número'], input[placeholder*='Solo números'], input[placeholder*='numeros'], input[name*='salary'], input[name*='pretension']"
            
            renta_el = page.query_selector(renta_selector)
            textareas = page.query_selector_all("textarea")
            
            if not renta_el and not textareas:
                console.print("  [dim]No se detecta formulario directo. Buscando botón de postulación...[/dim]")
                btn_postular = page.query_selector("button:has-text('Postular'), .btn-postular, .postular-btn, .button-apply")
                if btn_postular:
                    btn_postular.scroll_into_view_if_needed()
                    btn_postular.click()
                    _pausa(2, 4)
                    # Re-escanear
                    renta_el = page.query_selector(renta_selector)
                    textareas = page.query_selector_all("textarea")

            # Campo de renta esperada
            if renta_el:
                renta_valor = "100000"
                renta_el.scroll_into_view_if_needed()
                renta_el.click()
                renta_el.fill("")
                renta_el.type(renta_valor, delay=50)
                _pausa(0.3, 0.8)

            # Campos de texto / preguntas personalizadas
            textareas = page.query_selector_all("textarea")
            for r in respuestas_generadas:
                indice = r.get("indice", 0)
                if indice < len(textareas):
                    ta = textareas[indice]
                    ta.scroll_into_view_if_needed()
                    ta.click()
                    ta.fill("")
                    # Fallback si la IA falló (ej: error 403)
                    txt_resp = r["respuesta"]
                    if "Error code: 403" in txt_resp:
                        txt_resp = "Disponible para ampliar información en una entrevista."
                    
                    for char in txt_resp:
                        ta.type(char, delay=random.randint(20, 60))
                    _pausa(0.3, 0.8)

            _pausa(1, 2)

            # ── 5. Enviar ──────────────────────────────────────────────────
            # Selector exacto basado en el HTML del usuario:
            # <button type="submit" id="sendApplication" class="btn btn-primary job-apply-btn">...
            submit_selector = detalle.get("submit_selector") or \
                'button#sendApplication.btn.btn-primary.job-apply-btn'
            
            # Intentar varios selectores si el principal falla
            btn_loc = page.locator(submit_selector).first
            
            if btn_loc.count() == 0:
                # Selector de emergencia
                alternativos = [
                    'button#sendApplication',
                    '#sendApplication',
                    '.job-apply-btn',
                    'button:has-text("Enviar postulación")'
                ]
                for sel in alternativos:
                    if page.locator(sel).count() > 0:
                        submit_selector = sel
                        btn_loc = page.locator(sel).first
                        break

            if btn_loc.count() > 0:
                btn_loc.scroll_into_view_if_needed()
                # Pausa muy reducida antes del clic final
                _pausa(0.2, 0.5)
                # Click forzado por si hay algo invisible encima
                btn_loc.click(timeout=5000, force=True)
                _pausa(1, 2)
                print("  ✅ Postulación enviada correctamente")
                estado = "enviada"
            else:
                print("  ⚠️  No se encontró el botón de envío")
                with open("error_boton.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                estado = "error_boton"

        except Exception as e:
            print(f"  ❌ Error al rellenar/enviar: {e}")
            # DEBUG: Guardar HTML en caso de error general
            try:
                with open("error_general.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            except: pass
            estado = "error"

    # ── 6. Registrar en BD ─────────────────────────────────────────────
    registrar_postulacion(
        oferta_id, titulo, empresa, url, estado,
        json.dumps(respuestas_generadas, ensure_ascii=False)
    )
    return estado
