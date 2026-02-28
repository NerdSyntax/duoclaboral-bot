"""
main.py — Script principal del bot de postulaciones DuocLaboral
Uso: python main.py
"""
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from config import validar_config, FILTROS, cargar_perfil
from database import inicializar_db, listar_postulaciones, total_postulaciones, ya_postule, registrar_postulacion
from scraper import crear_browser, login, obtener_ofertas, obtener_detalle_oferta, aplicar_filtros_avanzados, OFERTAS_URL, _pausa
from ai_responder import evaluar_oferta_relevancia
from aplicador import postular_oferta

console = Console()


# ─────────────────────────────────────────────
#  MENÚ PRINCIPAL
# ─────────────────────────────────────────────

def mostrar_menu():
    console.print(Panel.fit(
        "[bold yellow]🤖 DuocLaboral Bot[/bold yellow]\n"
        "[dim]Automatizador de postulaciones[/dim]",
        border_style="yellow"
    ))
    console.print("\n  [1] 🚀 Iniciar búsqueda y postulación [bold](modo revisión)[/bold]")
    console.print("  [2] ⚡ Modo automático [bold red](sin confirmación)[/bold red]")
    console.print("  [3] 📊 Ver mis postulaciones")
    console.print("  [4] 🔍 Solo escanear ofertas (sin postular)")
    console.print("  [5] ❌ Salir")
    console.print()
    return input("  Elige una opción [1-5]: ").strip()


# ─────────────────────────────────────────────
#  FLUJO PRINCIPAL DE POSTULACIÓN
# ─────────────────────────────────────────────

def run_bot(modo_revision: bool = True):
    console.rule("[yellow]Iniciando bot[/yellow]")

    # Validar config
    try:
        validar_config()
    except EnvironmentError as e:
        console.print(f"[red]❌ Error de configuración:\n{e}[/red]")
        console.print("\n[dim]Copia .env.example como .env y completa tus credenciales.[/dim]")
        return

    # Inicializar BD
    inicializar_db()

    max_postulaciones = FILTROS.get("max_postulaciones_por_sesion", 10)
    enviadas = 0
    errores = 0

    # Crear browser
    console.print("\n[cyan]🌐 Abriendo navegador...[/cyan]")
    p, browser, context, page = crear_browser(headless=False)

    try:
        # Login
        console.print("[cyan]🔑 Iniciando sesión...[/cyan]")
        if not login(page, context):
            console.print("[red]❌ No se pudo iniciar sesión. Verifica tus credenciales.[/red]")
            return

        # ── NUEVO: Aplicar Filtros de Carrera si están configurados ──
        carrera = FILTROS.get("carrera")
        if carrera:
            console.print(f"\n[bold magenta]⚙️ Aplicando filtros avanzados para: {carrera}[/bold magenta]")
            aplicar_filtros_avanzados(page, carrera)

        # ── NUEVO: Procesamiento uno a uno por página ──
        paginas_totales = 5
        for num_pagina in range(1, paginas_totales + 1):
            if enviadas >= max_postulaciones:
                break
                
            console.print(f"\n[bold cyan]📄 Explorando página {num_pagina}...[/bold cyan]")
            
            # Si no es la primera página, usar el botón visual de "Siguiente" para no perder los filtros de sesión
            if num_pagina > 1:
                console.print("  [dim]Buscando botón Siguiente en el paginador...[/dim]")
                btn_siguiente = page.query_selector('.pagination a[rel="next"], .pagination li:last-child a, a:has-text("Siguiente"), a:has-text("Next")')
                if btn_siguiente:
                    btn_siguiente.scroll_into_view_if_needed()
                    btn_siguiente.click()
                    console.print(f"  [dim]Navegando a página {num_pagina} (Clic Siguiente)[/dim]")
                    _pausa(3, 5) # Esperar a que recargue la página la tabla
                else:
                    console.print("  [yellow]⚠️ No se encontró botón para avanzar a la página siguiente. Fin de resultados.[/yellow]")
                    break
            else:
                console.print("  [dim]Manteniendo filtros UI de la primera página...[/dim]")
            
            # Esperar a que carguen las tarjetas
            try:
                page.wait_for_selector("a[href*='/jobs/'], .job-offer, .card-job", timeout=10000)
            except:
                console.print(f"  [yellow]⚠️ No se detectaron más ofertas en esta página.[/yellow]")
                break

            # Encontrar todas las tarjetas de esta página
            # Usamos selectores que apunten a los contenedores o links principales
            tarjetas = page.query_selector_all("a[href*='/jobs/'], .job-offer, .card-job, article")
            console.print(f"  [dim]Encontradas {len(tarjetas)} tarjetas.[/dim]")

            for idx, card in enumerate(tarjetas, 1):
                if enviadas >= max_postulaciones:
                    break

                try:
                    # Extraer ID y Título básico de la tarjeta
                    href = card.get_attribute("href") or ""
                    
                    # ── NUEVO: IGNORAR REDES SOCIALES ──
                    if not href or href.startswith("http"):
                        # Prioridad 1: Buscar directamente el botón Postular que tiene el link al trabajo
                        link = card.query_selector("a.btn.btn-primary.job-card-apply-btn, a[href^='/jobs/']")
                        href = link.get_attribute("href") if link else ""
                    
                    # Verificación extra por las dudas
                    if not href or href.startswith("http"):
                        continue
                        
                    if not href.startswith("/jobs/"):
                        continue
                    
                    # Es vital tener la URL lista, extraída de scraper.py logic
                    url_oferta = f"https://duoclaboral.cl{href}" if href.startswith("/") else href
                    
                    oferta_id = href.rstrip("/").split("/")[-1]
                    titulo_basico = card.inner_text().split("\n")[0][:60]

                    texto_tarjeta = card.inner_text().lower()
                    
                    # 1. Verificar si ya postulé (IMPORTANTE: NO BUSCAR INFINITAMENTE)
                    if ya_postule(oferta_id):
                        # console.print(f"  [dim]⏭  ({idx}) Ya postulada en DB: {titulo_basico}[/dim]")
                        continue
                        
                    # 1.5 Detección Visual de Duplicado (por si se postuló a mano o en otra PC)
                    if "postulad" in texto_tarjeta or "ya postulas" in texto_tarjeta:
                        console.print(f"  [dim]⏭  ({idx}) Detectado como YA POSTULADO visualmente: {titulo_basico}[/dim]")
                        # Registrar para que no vuelva a entrar en futuros ciclos
                        registrar_postulacion(oferta_id, titulo_basico, "N/A", url_oferta, "duplicado", "Postulado previamente manual")
                        continue

                    # 2. Entrar a la oferta (Haciendo click en 'Postular' de la tarjeta)
                    console.print(Panel(
                        f"[bold yellow]OFERTA #{enviadas+1}[/bold yellow] | [bold white]{titulo_basico}[/bold white]\n"
                        f"[dim]ID: {oferta_id}[/dim]",
                        title="[cyan]Procesando Individualmente[/cyan]",
                        border_style="grey50"
                    ))

                    # Selector exacto basado en el HTML del usuario para el enlace de postulación inicial
                    btn_postular_sel = "a.btn.btn-primary.job-card-apply-btn"
                    btn_postular = card.query_selector(btn_postular_sel)
                    if btn_postular:
                        console.print(f"  [cyan]🖱️  Detectado botón 'Postular' de la tarjeta (ID: {oferta_id})...[/cyan]")
                    
                    # ── NUEVO FLUJO: Abrir en pestaña nueva para no perder filtros ──
                    nueva_url = url_oferta
                    console.print(f"  [dim]Abriendo en nueva pestaña: {nueva_url}...[/dim]")
                    
                    # Crear nueva pestaña
                    tab_postulacion = context.new_page()
                    # Si usas stealth, aplícalo aquí también
                    try:
                        from playwright_stealth import stealth_sync
                        stealth_sync(tab_postulacion)
                    except: pass
                    
                    tab_postulacion.goto(nueva_url, timeout=60000)
                    tab_postulacion.wait_for_load_state("networkidle")
                    _pausa(2, 4)

                    # 3. Obtener detalle completo desde la pestaña nueva
                    detalle = obtener_detalle_oferta(tab_postulacion, tab_postulacion.url) 
                    
                    # 4. Evaluación de Relevancia
                    relevante, razon = evaluar_oferta_relevancia(
                        detalle.get("titulo", titulo_basico), detalle.get("descripcion", "")
                    )
                    
                    if relevante:
                        console.print(f"  [bold green]🚀 Iniciando postulación interactiva...[/bold green]")
                        estado = postular_oferta(tab_postulacion, {"id": oferta_id, "titulo": detalle["titulo"], "url": tab_postulacion.url}, detalle, modo_revision=modo_revision)
                        
                        if estado == "enviada":
                            enviadas += 1
                        elif estado in ("error", "error_boton"):
                            errores += 1
                    else:
                        console.print(f"  [dim]⏭  No relevante: {razon}[/dim]")

                    # 5. Volver al listado: Cerramos la pestaña, la página original sigue intacta
                    console.print("  [dim]Cerrando pestaña y volviendo al listado intacto...[/dim]")
                    tab_postulacion.close()
                    _pausa(1, 2)

                except Exception as e:
                    console.print(f"  [red]⚠️ Error procesando tarjeta {idx}: {e}[/red]")
                    try:
                        tab_postulacion.close()
                    except: pass

    except KeyboardInterrupt:
        console.print("\n[bold red]🛑 Bot detenido manualmente por el usuario.[/bold red]")
    finally:
        browser.close()
        p.stop()

    # Resumen
    console.rule("[yellow]Resumen[/yellow]")
    console.print(f"  ✅ Postulaciones enviadas : [green]{enviadas}[/green]")
    console.print(f"  ❌ Errores               : [red]{errores}[/red]")
    console.print(f"  📊 Total histórico        : {total_postulaciones()}")


# ─────────────────────────────────────────────
#  SOLO ESCANEAR (sin postular)
# ─────────────────────────────────────────────

def solo_escanear():
    console.rule("[cyan]Modo escaneo[/cyan]")
    try:
        validar_config()
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        return

    inicializar_db()
    p, browser, context, page = crear_browser(headless=False)

    try:
        if not login(page, context):
            return

        ofertas = obtener_ofertas(page, paginas=3)

        tabla = Table(title="Ofertas encontradas", box=box.ROUNDED)
        tabla.add_column("#", style="dim", width=4)
        tabla.add_column("Título", style="yellow")
        tabla.add_column("URL", style="dim")

        for i, o in enumerate(ofertas, 1):
            tabla.add_row(str(i), o["titulo"][:50], o["url"])

        console.print(tabla)
        console.print(f"\n[green]Total: {len(ofertas)} ofertas[/green]")

    finally:
        browser.close()
        p.stop()


# ─────────────────────────────────────────────
#  VER POSTULACIONES
# ─────────────────────────────────────────────

def ver_postulaciones():
    inicializar_db()
    rows = listar_postulaciones()

    if not rows:
        console.print("[yellow]No hay postulaciones registradas aún.[/yellow]")
        return

    tabla = Table(title=f"Mis Postulaciones ({len(rows)} total)", box=box.ROUNDED)
    tabla.add_column("Fecha", style="dim", width=16)
    tabla.add_column("Título", style="yellow", width=35)
    tabla.add_column("Empresa", width=20)
    tabla.add_column("Estado", style="bold")

    colores = {
        "enviada": "green",
        "saltada": "yellow",
        "error": "red",
        "duplicado": "dim",
    }

    for r in rows:
        estado = r.get("estado", "")
        color = colores.get(estado, "white")
        tabla.add_row(
            r.get("fecha", ""),
            (r.get("titulo") or "")[:33],
            (r.get("empresa") or "")[:18],
            f"[{color}]{estado}[/{color}]"
        )

    console.print(tabla)


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    while True:
        opcion = mostrar_menu()

        if opcion == "1":
            run_bot(modo_revision=True)
        elif opcion == "2":
            console.print("\n[red bold]⚠️  MODO AUTOMÁTICO: postulará SIN pedir confirmación[/red bold]")
            confirmar = input("  ¿Estás seguro? [s/N]: ").strip().lower()
            if confirmar == "s":
                run_bot(modo_revision=False)
        elif opcion == "3":
            ver_postulaciones()
        elif opcion == "4":
            solo_escanear()
        elif opcion == "5":
            console.print("[dim]Chao 👋[/dim]")
            sys.exit(0)
        else:
            console.print("[red]Opción inválida[/red]")

        input("\n  Presiona Enter para continuar...")
