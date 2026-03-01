import json
import random
import time
from playwright.sync_api import Page, BrowserContext
from rich.console import Console
from rich.panel import Panel

from config import DUOC_EMAIL, DUOC_PASSWORD, LOGIN_URL, OFERTAS_URL, SESSION_PATH, cargar_perfil
from database import ya_postule, registrar_postulacion
from ai_responder import responder_pregunta, resumir_oferta
from portales.base import PortalBase

console = Console()

def _pausa(min_s=1.0, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))

def scroll_aleatorio(page: Page):
    try:
        movimiento = random.randint(100, 500)
        page.mouse.wheel(0, movimiento)
        _pausa(0.5, 1.5)
    except Exception:
        pass


class DuocLaboralPortal(PortalBase):
    
    def __init__(self, page: Page, context: BrowserContext):
        super().__init__(page, context)
        self.nombre = "DuocLaboral"

    def login(self) -> bool:
        """Inicia sesión en DuocLaboral."""
        self.page.goto(LOGIN_URL, timeout=60000)
        _pausa()

        if "login" not in self.page.url:
            print("✅ Sesión activa detectada")
            return True

        try:
            email_sel = '#username, input[name="LoginForm[username]"], input[type="email"]'
            pass_sel  = '#password, input[name="LoginForm[password]"], input[type="password"]'

            self.page.wait_for_selector(email_sel, timeout=10000)
            
            self.page.fill(email_sel, "")
            self.page.type(email_sel, DUOC_EMAIL.strip(), delay=random.randint(50, 150))
            _pausa(1.0, 2.0)
            
            self.page.fill(pass_sel, "")
            self.page.type(pass_sel, DUOC_PASSWORD.strip(), delay=random.randint(50, 150))
            _pausa(1.0, 2.0)
            
            try:
                box = self.page.locator('#userLoginSubmit, button[type="submit"], input[type="submit"]').bounding_box()
                if box:
                    self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    _pausa(0.3, 0.8)
            except Exception:
                pass

            self.page.click('#userLoginSubmit, button[type="submit"], input[type="submit"]')

            try:
                self.page.wait_for_function('window.location.pathname !== "/login"', timeout=15000)
            except Exception:
                pass 
            
            _pausa(1, 2)

            if "login" not in self.page.url:
                print("✅ Login exitoso")
                self._guardar_sesion()
                return True
            else:
                print(f"❌ Login fallido — la URL no cambió: {self.page.url}")
                return False
        except Exception as e:
            print(f"❌ Error en login: {e}")
            return False

    def _guardar_sesion(self):
        cookies = self.context.cookies()
        with open(SESSION_PATH, "w") as f:
            json.dump({"cookies": cookies}, f)

    def aplicar_filtros_avanzados(self, carrera: str):
        """Navega directamente a la URL de búsqueda con carrera=Ingeniería en informática (id=341)."""
        # Usamos URL directa con parámetro de carrera — mucho más rápido y confiable que la UI
        # genericCareer=341 = Ingeniería en informática (según el HTML del select)
        search_url = (
            "https://duoclaboral.cl/trabajo/trabajos-en-chile"
            "?Search[jobOfferType]=0"
            "&Search[genericCareer]=341"
        )
        console.print(f"  [cyan]🔗 Navegando a búsqueda por URL directa...[/cyan]")
        self.page.goto(search_url, timeout=60000)
        try:
            self.page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        _pausa(1, 2)


    def obtener_ofertas(self, paginas: int = 3, num_pagina_actual: int = 1) -> list[dict]:
        """Obtiene ofertas de la página actual de DuocLaboral usando selectores correctos del HTML real."""
        ofertas = []

        if num_pagina_actual > 1:
            # Paginación: buscar enlace "Siguiente" o úrrow en el paginador
            btn_siguiente = self.page.query_selector(
                '.pagination a[rel="next"], '
                'li.next a, '
                'a:has-text(">"): '
            )
            if not btn_siguiente:
                # Intentar hacer clic en el número de página siguiente
                try:
                    num_links = self.page.query_selector_all('.pagination a')
                    for lnk in num_links:
                        txt = lnk.inner_text().strip()
                        if txt == str(num_pagina_actual):
                            btn_siguiente = lnk
                            break
                except Exception:
                    pass

            if btn_siguiente:
                btn_siguiente.scroll_into_view_if_needed()
                btn_siguiente.click()
                console.print(f"  [dim]Navegando a página {num_pagina_actual}...[/dim]")
                _pausa(2, 3)
            else:
                console.print("  [yellow]⚠️ Fin de resultados (no hay página siguiente).[/yellow]")
                return []
        else:
            console.print(f"[dim]📄 Escaneando página 1...[/dim]")

        try:
            self.page.wait_for_selector("article.job-card, .job-card", timeout=10000)
        except Exception:
            console.print(f"  [yellow]⚠️  No se encontraron ofertas en esta página[/yellow]")
            return []

        # Las tarjetas en DuocLaboral son <article class="job-card"> con un enlace <a href="/jobs/ID">
        articulos = self.page.query_selector_all("article.job-card")
        console.print(f"  [dim]Encontré {len(articulos)} tarjetas en esta página.[/dim]")

        for art in articulos:
            try:
                if random.random() < 0.2: scroll_aleatorio(self.page)

                # Saltar las que ya marcaron "Ya postulaste" en la tarjeta
                ya_aplicado = art.query_selector(".job-card-applied")
                if ya_aplicado:
                    continue

                # Enlace principal del trabajo: <a href="/jobs/856396">
                enlace = art.query_selector("a[href*='/jobs/']") or art.query_selector("h2 a, .job-card-title a")
                if not enlace:
                    continue

                href = enlace.get_attribute("href") or ""
                if not href:
                    continue

                # ID es el último segmento de /jobs/856396
                oferta_id = href.rstrip("/").split("/")[-1]
                if not oferta_id.isdigit():
                    continue

                # Título desde el elemento span dentro del enlace
                titulo_el = enlace.query_selector("span[itemprop='title']")
                titulo = titulo_el.inner_text().strip() if titulo_el else enlace.inner_text().strip()
                if len(titulo) < 3:
                    titulo = "Oferta sin título"

                # Empresa
                emp_el = art.query_selector(".job-card-company span[itemprop='name']")
                empresa = emp_el.inner_text().strip() if emp_el else ""

                url_oferta = f"https://duoclaboral.cl{href}" if href.startswith("/") else href

                if any(o.get("id") == oferta_id for o in ofertas):
                    continue

                ofertas.append({
                    "id": oferta_id,
                    "titulo": titulo,
                    "empresa": empresa,
                    "url": url_oferta,
                })
            except Exception:
                continue

        _pausa(1, 2)
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
                page_text = self.page.evaluate("""
                    () => {
                        const garbage = document.querySelectorAll('script,style,nav,footer,header');
                        garbage.forEach(el => el.remove());
                        return document.body ? document.body.innerText : '';
                    }
                """).strip()
                if page_text and len(page_text) > 100: detalle["descripcion"] = page_text
            except:
                body_el = self.page.query_selector("body")
                if body_el: detalle["descripcion"] = body_el.inner_text()[:10000]

            emp_el = self.page.query_selector(".company-name, .empresa, h2.company, .job-company, h2, .companyTitle")
            if emp_el: detalle["empresa"] = emp_el.inner_text().strip()

            loc_el = self.page.query_selector(".location, .ubicacion, [title*='Ubicación'], .job-location, .icono-ubicacion + span")
            if not loc_el:
                for txt in ["text=/Región/i", "text=/Ciudad/i"]:
                    loc_el = self.page.query_selector(txt)
                    if loc_el: break
            if loc_el: detalle["ubicacion"] = loc_el.inner_text().strip()
            else: detalle["ubicacion"] = "No especificada"

            form_container_selectors = ["form:has(button#sendApplication)", "form.job-apply-form", ".application-form", "#postulacion", ".postulacion-container"]
            form_container = None
            for sel in form_container_selectors:
                form_container = self.page.query_selector(sel)
                if form_container: break
            
            textareas = []
            if form_container: textareas = form_container.query_selector_all("textarea")
            
            if textareas:
                for i, ta in enumerate(textareas):
                    label = ""
                    try:
                        js_eval = """
                        el => {
                            if (el.id) { let lbl = document.querySelector(`label[for="${el.id}"]`); if (lbl && lbl.innerText.trim()) return lbl.innerText.trim(); }
                            let prev = el.previousElementSibling; if (prev && prev.innerText.trim()) return prev.innerText.trim();
                            let wrap = el.closest('div.form-group, div.field, div.mb-3, .form-item, .form-textarea, .field-wrapper, .wpcf7-form-control-wrap, .textarea-container, td, li');
                            if (wrap) {
                                let labels = wrap.querySelectorAll('label, p, span, strong, b, h1, h2, h3, h4, h5, .label, .title');
                                for (let l of labels) { if (l.innerText.trim()) return l.innerText.trim(); }
                            }
                            let parent = el.parentElement;
                            if (parent && parent.innerText.trim().length < 500) { return parent.innerText.split('\\n')[0].trim(); }
                            return '';
                        }
                        """
                        extraido = ta.evaluate(js_eval)
                        label = extraido.strip() if extraido else f"Pregunta {i+1}"
                    except:
                        label = f"Pregunta {i+1}"

                    if detalle.get("preguntas") is None: detalle["preguntas"] = []
                    detalle["preguntas"].append({ "label": label, "indice": i, "selector": f"textarea:nth-of-type({i+1})" })

                renta_sel = 'input[placeholder*="número"], input[placeholder*="Sólo números"], input[placeholder*="numeros"], input[name*="salary"], input[name*="pretension"], input[id*="salary"]'
                renta_el = (form_container.query_selector(renta_sel) if form_container else None) or self.page.query_selector(renta_sel)
                if renta_el: detalle["renta_selector"] = renta_sel
            else:
                detalle["preguntas"] = []

            btn_selector = 'button#sendApplication.job-apply-btn, button:has-text("Enviar postulación"), button:has-text("Enviar postulacion")'
            btn = (form_container.query_selector(btn_selector)) if form_container else self.page.query_selector(btn_selector)
            if btn: detalle["submit_selector"] = btn_selector

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
            title="[bold white]OFERTA DE TRABAJO[/bold white]", border_style="bright_blue"
        ))

        self.page.goto(url, timeout=60000)
        _pausa(2, 4)
        
        if self.page.locator("text='Ya postulaste'").count() > 0 or self.page.locator("text='Postulado'").count() > 0:
            return "duplicado"
            
        respuestas_generadas = []
        btn_enviar = self.page.locator("button#sendApplication.btn.btn-primary.job-apply-btn")
        if btn_enviar.count() == 0:
            btn_postular_alt = self.page.locator("button.button-apply, .btn-postular")
            if btn_postular_alt.count() == 0: return "error"

        descripcion = detalle.get("descripcion", "")
        preguntas = detalle.get("preguntas", [])

        if preguntas:
            console.print(f"[dim]  → Generando {len(preguntas)} respuesta(s)...[/dim]")
            for p in preguntas:
                label = p.get("label", "Pregunta")
                respuesta = responder_pregunta(label, descripcion)
                respuestas_generadas.append({
                    "pregunta": label, "respuesta": respuesta, "selector": p.get("selector"), "indice": p.get("indice", 0)
                })
                _pausa(0.8, 1.5)

        if modo_revision:
            console.print("")
            console.print(Panel(
                f"[italic white]{resumir_oferta(descripcion)}[/italic white]",
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

            renta_ingresada = input("  Renta líquida [ENTER = $100.000 / escribe otro valor]: ").strip()
            renta_valor_final = renta_ingresada.replace(".", "").replace("$", "").strip() or "100000"
            console.print(f"[dim]  Renta a enviar: ${int(renta_valor_final):,}[/dim]".replace(",", "."))

            confirmacion = input("  ¿Postular? [s] Sí / [n] No: ").strip().lower()
            if confirmacion != "s":
                registrar_postulacion(oferta_id, titulo, empresa, url, "saltada", json.dumps(respuestas_generadas, ensure_ascii=False))
                return "saltada"

        try:
            self.page.evaluate("""
                () => {
                    const selectors = ['flowise-chatbot', '.cookie-consent', '#open_feedback', '.modal-backdrop'];
                    selectors.forEach(sel => { const el = document.querySelector(sel); if (el) el.style.display = 'none'; });
                }
            """)

            renta_selector = detalle.get("renta_selector") or "input[placeholder*='número'], input[placeholder*='Solo números'], input[placeholder*='numeros'], input[name*='salary'], input[name*='pretension']"
            renta_el = self.page.query_selector(renta_selector)
            textareas = self.page.query_selector_all("textarea")
            
            if not renta_el and not textareas:
                console.print("  [dim]No se detecta formulario directo. Buscando botón de postulación...[/dim]")
                btn_postular = self.page.query_selector("button:has-text('Postular'), .btn-postular, .postular-btn, .button-apply")
                if btn_postular:
                    btn_postular.scroll_into_view_if_needed()
                    btn_postular.click()
                    _pausa(2, 4)
                    renta_el = self.page.query_selector(renta_selector)
                    textareas = self.page.query_selector_all("textarea")

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
                    if "Error code: 403" in txt_resp: txt_resp = "Disponible para ampliar información en una entrevista."
                    for char in txt_resp: ta.type(char, delay=random.randint(20, 60))
                    _pausa(0.3, 0.8)

            _pausa(1, 2)
            submit_selector = detalle.get("submit_selector") or 'button#sendApplication.btn.btn-primary.job-apply-btn'
            btn_loc = self.page.locator(submit_selector).first
            
            if btn_loc.count() == 0:
                alternativos = ['button#sendApplication', '#sendApplication', '.job-apply-btn', 'button:has-text("Enviar postulación")']
                for sel in alternativos:
                    if self.page.locator(sel).count() > 0:
                        submit_selector = sel
                        btn_loc = self.page.locator(sel).first
                        break

            if btn_loc.count() > 0:
                btn_loc.scroll_into_view_if_needed()
                _pausa(0.2, 0.5)
                btn_loc.click(timeout=5000, force=True)
                _pausa(1, 2)
                print("  ✅ Postulación enviada correctamente")
                estado = "enviada"
            else:
                print("  ⚠️  No se encontró el botón de envío")
                estado = "error_boton"

        except Exception as e:
            print(f"  ❌ Error al rellenar/enviar: {e}")
            estado = "error"

        registrar_postulacion(oferta_id, titulo, empresa, url, estado, json.dumps(respuestas_generadas, ensure_ascii=False))
        return estado
