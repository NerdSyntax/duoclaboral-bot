import json
import random
import time
from playwright.sync_api import Page, BrowserContext
from rich.console import Console
from rich.panel import Panel

from config import CHILETRABAJOS_EMAIL, CHILETRABAJOS_PASSWORD, SESSION_PATH, cargar_perfil
from database import ya_postule, registrar_postulacion
from ai_responder import responder_pregunta, resumir_oferta
from portales.base import PortalBase

console = Console()

def _pausa(min_s=2.5, max_s=5.5):
    time.sleep(random.uniform(min_s, max_s))

def scroll_aleatorio(page: Page):
    try:
        movimiento = random.randint(100, 500)
        page.mouse.wheel(0, movimiento)
        _pausa(0.5, 1.5)
    except Exception:
        pass


class ChileTrabajosPortal(PortalBase):
    
    def __init__(self, page: Page, context: BrowserContext):
        super().__init__(page, context)
        self.nombre = "ChileTrabajos"
        self.base_url = "https://www.chiletrabajos.cl"
        self.login_url = f"{self.base_url}/chtlogin"
        self.ofertas_url = f"{self.base_url}/buscar-empleos"

    def login(self) -> bool:
        """Inicia sesión en ChileTrabajos."""
        console.print(f"[cyan]Navegando a {self.login_url}[/cyan]")
        self.page.goto(self.login_url, timeout=60000)
        _pausa()

        if "/panel" in self.page.url or "Mi cuenta" in self.page.content():
            print("✅ Sesión activa detectada (ChileTrabajos)")
            return True

        try:
            # Según la captura, el form tiene Usuario/email y Clave
            email_sel = 'input[name="email"], input[type="email"], #email'
            pass_sel  = 'input[name="password"], input[type="password"], #password'

            self.page.wait_for_selector(email_sel, timeout=10000)
            
            self.page.fill(email_sel, "")
            self.page.type(email_sel, CHILETRABAJOS_EMAIL.strip(), delay=random.randint(50, 150))
            _pausa(1.0, 2.0)
            
            self.page.fill(pass_sel, "")
            self.page.type(pass_sel, CHILETRABAJOS_PASSWORD.strip(), delay=random.randint(50, 150))
            _pausa(1.0, 2.0)
            
            # Botón Iniciar Sesión
            btn_login = self.page.locator('button:has-text("Iniciar Sesión"), input[type="submit"], button[type="submit"]').first
            
            try:
                box = btn_login.bounding_box()
                if box:
                    self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    _pausa(0.3, 0.8)
            except Exception:
                pass

            btn_login.click()

            # Esperar a ver si cambia de página o aparece algún elemento de login exitoso
            try:
                self.page.wait_for_selector('.alert-danger, .error', timeout=5000)
                # Si encuentra un error de credenciales
                print("❌ Login fallido — Credenciales inválidas.")
                return False
            except:
                pass # No hubo error visible rápido

            _pausa(2, 4)

            # Comprobar estado final
            if "chtlogin" not in self.page.url or "Cerrar sesión" in self.page.content() or "/panel" in self.page.url:
                print("✅ Login exitoso en ChileTrabajos")
                self._guardar_sesion()
                return True
            else:
                print(f"❌ Login fallido — la URL no cambió: {self.page.url}")
                return False
        except Exception as e:
            print(f"❌ Error en login ChileTrabajos: {e}")
            return False

    def _guardar_sesion(self):
        cookies = self.context.cookies()
        with open(SESSION_PATH, "w") as f:
            json.dump({"cookies": cookies}, f)
            
    def aplicar_filtros_avanzados(self, carrera: str):
        # En ChileTrabajos usaremos búsqueda directa por URL para ser más rápidos y evitar errores de UI
        # ej: https://www.chiletrabajos.cl/encuentra-un-empleo?2=ingenieria+informatica&13=1022
        # Pero podemos intentar usar la UI de búsqueda primero.
        console.print(f"[cyan]Buscando ofertas para: {carrera} en Santiago[/cyan]")
        
        # URL armada según la captura: ?2=ingenieria+informatica&13=1022
        # 2 = Keyword, 13 = Ubicación (1022 parece ser Santiago)
        keyword = carrera.replace(" ", "+").lower()
        search_url = f"{self.base_url}/encuentra-un-empleo?2={keyword}&13=1022"
        self.page.goto(search_url, timeout=60000)
        _pausa(3, 5)

    def obtener_ofertas(self, paginas: int = 3, num_pagina_actual: int = 1) -> list[dict]:
        """Obtiene las ofertas de la página actual de ChileTrabajos."""
        ofertas = []

        if num_pagina_actual > 1:
            console.print("  [dim]Buscando botón Siguiente en el paginador...[/dim]")
            btn_siguiente = self.page.query_selector('.pagination a[rel="next"], a:has-text("Siguiente"), a:has-text(">")')
            if btn_siguiente:
                btn_siguiente.scroll_into_view_if_needed()
                btn_siguiente.click()
                console.print(f"  [dim]Navegando a página {num_pagina_actual} (Clic Siguiente)[/dim]")
                _pausa(3, 5) 
            else:
                console.print("  [yellow]⚠️ No se encontró botón para avanzar a la página siguiente. Fin de resultados.[/yellow]")
                return []
        else:
            console.print(f"[dim]📄 Escaneando página 1 de resultados...[/dim]")

        # Esperar a que carguen las tarjetas. Según la imagen, las ofertas tienen un contenedor con un enlace
        try:
            self.page.wait_for_selector(".job-item, .oferta, div.row.mb-3, article", timeout=10000)
        except Exception:
            console.print(f"  [yellow]⚠️  No se encontraron más ofertas en esta página[/yellow]")
            return []

        # Extraer tarjetas (buscamos enlaces que parezcan de trabajos)
        tarjetas = self.page.query_selector_all("a[href*='/trabajo/']")

        for tarjeta in tarjetas:
            try:
                if random.random() < 0.3: scroll_aleatorio(self.page)
                    
                href = tarjeta.get_attribute("href") or ""
                if not href or "/trabajo/" not in href:
                    continue

                # Extraer ID: en ChileTrabajos la url es ej: /trabajo/analista-de-facturacion-3793214
                oferta_id = href.split("-")[-1]
                if not oferta_id.isdigit(): continue # Asegurar que es un id
                
                titulo = tarjeta.inner_text().strip()
                if not titulo: titulo = tarjeta.get_attribute("title") or "Sin Título"
                
                # Ignorar si es un link interno raro
                if len(titulo) < 3: continue
                    
                url_oferta = f"{self.base_url}{href}" if href.startswith("/") else href

                if any(o.get("id") == oferta_id for o in ofertas):
                    continue

                ofertas.append({
                    "id": oferta_id,
                    "titulo": titulo,
                    "url": url_oferta,
                })
            except Exception:
                continue

        _pausa(2, 5)
        return ofertas

    def obtener_detalle_oferta(self, url: str) -> dict:
        self.page.goto(url, timeout=60000)
        _pausa(3, 6) 

        for _ in range(random.randint(2, 4)): scroll_aleatorio(self.page)

        detalle = {
            "titulo": "Sin título", "descripcion": "", "empresa": "Empresa no especificada",
            "preguntas": [], "renta_selector": None, "submit_selector": None,
        }

        try:
            titulo_h1 = self.page.query_selector("h1")
            if titulo_h1: detalle["titulo"] = titulo_h1.inner_text().strip()

            try:
                # El texto de la descripción suele estar en el body o un id específico.
                page_text = self.page.evaluate("""
                    () => {
                        const garbage = document.querySelectorAll('script,style,nav,footer,header, .publi');
                        garbage.forEach(el => el.remove());
                        const content = document.querySelector('.desc-oferta, .job-desc, article');
                        if (content) return content.innerText;
                        return document.body ? document.body.innerText : '';
                    }
                """).strip()
                if page_text and len(page_text) > 100: detalle["descripcion"] = page_text
            except:
                body_el = self.page.query_selector("body")
                if body_el: detalle["descripcion"] = body_el.inner_text()[:10000]

            # Buscar la empresa (en la imagen sale debajo del H1)
            emp_el = self.page.query_selector(".company, b, strong, h2")
            if emp_el: detalle["empresa"] = emp_el.inner_text().strip()

            # En ChileTrabajos, al pusar "Postular" suele abrirse un modal o enviarse directo si el CV ya está.
            # Según tu imagen, hay un botón grande azul "Postular".
            btn_postular_sel = "button:has-text('Postular'), a.btn-primary:has-text('Postular'), #btn-postular"
            btn_postular = self.page.query_selector(btn_postular_sel)
            
            if btn_postular:
                detalle["submit_selector"] = btn_postular_sel
                
            # Hay portales (como CT) que a veces te piden esperar el click y entonces sale el form.
            # En CT, si le das a Postular, te sale un recuadro de "¿Por qué deberíamos contratarte?" o "Pretensiones".
            
            # Nota: para extraer las preguntas, si CT abre un modal, habría que hacer clic en "Postular" aquí,
            # pero no queremos arriesgarnos a enviar accidentalmente en esta fase.

        except Exception as e: print(f"  ⚠️  Error extrayendo detalle: {e}")
        return detalle

    def postular_oferta(self, oferta: dict, detalle: dict, modo_revision: bool = True) -> str:
        oferta_id = oferta["id"]
        titulo = oferta.get("titulo", "")
        empresa = oferta.get("empresa", "")
        url = oferta.get("url", "")

        if ya_postule(oferta_id): return "duplicado"

        console.print(Panel.fit(
            f"[bold yellow]💼 {titulo}[/bold yellow]\\n[cyan]🏢 {empresa}[/cyan]\\n[dim]🔗 {url}[/dim]",
            title="[bold white]OFERTA DE TRABAJO (ChileTrabajos)[/bold white]", border_style="bright_blue"
        ))

        self.page.goto(url, timeout=60000)
        _pausa(2, 4)
        
        # Validar si ya postulamos
        if self.page.locator("text='Ya has postulado'").count() > 0 or self.page.locator("text='Postulado'").count() > 0:
            return "duplicado"

        # Hacer Clic en "Postular" inicial para que aparezcan las preguntas si las hay.
        submit_selector = detalle.get("submit_selector") or "button:has-text('Postular'), a.btn-primary:has-text('Postular')"
        btn_postular = self.page.query_selector(submit_selector)
        
        if not btn_postular:
            return "error"
            
        btn_postular.click()
        _pausa(2, 4)
        
        # Ahora que el form (modal o nueva pagina) está abierto, leemos textareas
        respuestas_generadas = []
        textareas = self.page.query_selector_all("textarea")
        
        if textareas:
            console.print(f"[dim]  → Generando respuesta para el mensaje de presentación...[/dim]")
            for i, ta in enumerate(textareas):
                # Usualmente en CT es una carta de presentación
                label = "Carta de presentación o motivo"
                respuesta = responder_pregunta(label, detalle.get("descripcion", ""))
                respuestas_generadas.append({
                    "pregunta": label, "respuesta": respuesta, "indice": i
                })
                _pausa(0.8, 1.5)

        if modo_revision:
            console.print("")
            console.print(Panel(
                f"[italic white]{resumir_oferta(detalle.get('descripcion', ''))}[/italic white]",
                title="[cyan]ℹ  Sobre esta oferta[/cyan]", border_style="cyan", padding=(0, 2)
            ))
            console.print("")

            for i, r in enumerate(respuestas_generadas, 1):
                console.print(f"[dim]P{i}[/dim] {r['pregunta'][:90]}")
                console.print(f"    [green]→[/green] {r['respuesta']}\\n")

            for i, r in enumerate(respuestas_generadas):
                opcion = input(f"  Editar P{i+1}? [e] / [ENTER] ok: ").strip().lower()
                if opcion == 'e':
                    nueva = input("  Nueva respuesta: ").strip()
                    if nueva: r['respuesta'] = nueva

            # En CT a veces piden renta.
            renta_ingresada = input("  Renta líquida [ENTER = $100.000 / escribe otro valor]: ").strip()
            renta_valor_final = renta_ingresada.replace(".", "").replace("$", "").strip() or "100000"
            console.print(f"[dim]  Renta a enviar: ${int(renta_valor_final):,}[/dim]".replace(",", "."))

            confirmacion = input("  ¿Confirmar y enviar Postulación? [s] Sí / [n] No: ").strip().lower()
            if confirmacion != "s":
                registrar_postulacion(oferta_id, titulo, empresa, url, "saltada", json.dumps(respuestas_generadas, ensure_ascii=False))
                return "saltada"

        try:
            renta_sel = 'input[name="pretensiones"], input[name="salary"], input[placeholder*="pretensiones"]'
            renta_el = self.page.query_selector(renta_sel)
            if renta_el:
                renta_valor = renta_valor_final if 'renta_valor_final' in dir() else "100000"
                renta_el.scroll_into_view_if_needed()
                renta_el.click()
                renta_el.fill("")
                renta_el.type(renta_valor, delay=50)
                _pausa(0.3, 0.8)

            textareas = self.page.query_selector_all("textarea")
            for r in respuestas_generadas:
                indice = r.get("indice", 0)
                if indice < len(textareas):
                    ta = textareas[indice]
                    ta.scroll_into_view_if_needed()
                    ta.click()
                    ta.fill("")
                    txt_resp = r["respuesta"]
                    if "Error code: 403" in txt_resp: txt_resp = "Disponible para entrevista."
                    for char in txt_resp: ta.type(char, delay=random.randint(20, 60))
                    _pausa(0.3, 0.8)

            _pausa(1, 2)
            # Buscar el botón final de envío dentro del modal
            submit_final_sel = 'button:has-text("Enviar postulación"), button:has-text("Confirmar postulación"), input[type="submit"][value*="Postular"]'
            btn_final_loc = self.page.locator(submit_final_sel).first
            
            if btn_final_loc.count() > 0:
                btn_final_loc.click(timeout=5000, force=True)
                _pausa(2, 4)
                print("  ✅ Postulación enviada correctamente en ChileTrabajos")
                estado = "enviada"
            else:
                # Si no hay formulario extra, el postular inicial probablemente ya lo envió.
                print("  ✅ Postulación rápida enviada")
                estado = "enviada"

        except Exception as e:
            print(f"  ❌ Error al rellenar/enviar: {e}")
            estado = "error"

        registrar_postulacion(oferta_id, titulo, empresa, url, estado, json.dumps(respuestas_generadas, ensure_ascii=False))
        return estado
