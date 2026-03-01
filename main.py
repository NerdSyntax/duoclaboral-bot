"""
main.py — Bot multi-portal de postulaciones automáticas
Portales soportados: DuocLaboral, ChileTrabajos (+ LinkedIn en el futuro)
Uso: python main.py
"""
import sys
import json
import random
import time
from playwright.sync_api import sync_playwright, BrowserContext

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from config import validar_config, FILTROS
from database import inicializar_db, listar_postulaciones, total_postulaciones, ya_postule, registrar_postulacion
from ai_responder import evaluar_oferta_relevancia
import limit_tracker

console = Console()

# ─────────────────────────────────────────────────────────────────
#  BROWSER
# ─────────────────────────────────────────────────────────────────

def crear_browser(headless=False):
    """Crea y retorna (playwright, browser, context, page)."""
    from config import SESSION_PATH
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=headless,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(
        no_viewport=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # Cargar sesión si existe
    try:
        with open(SESSION_PATH, "r") as f:
            storage = json.load(f)
        context.add_cookies(storage.get("cookies", []))
    except FileNotFoundError:
        pass

    page = context.new_page()
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
    except Exception:
        pass
    return p, browser, context, page


# ─────────────────────────────────────────────────────────────────
#  MENÚ DE SELECCIÓN DE PORTAL
# ─────────────────────────────────────────────────────────────────

def seleccionar_portal() -> str:
    console.print(Panel.fit(
        "[bold cyan]🌐 Selecciona el Portal de Empleo[/bold cyan]",
        border_style="cyan"
    ))
    console.print("  [1] 🎓 DuocLaboral")
    console.print("  [2] 💼 ChileTrabajos")
    console.print("  [3] 🔗 LinkedIn  [dim](próximamente)[/dim]")
    console.print()
    opcion = input("  Portal [1-3]: ").strip()
    portales = {"1": "duoclaboral", "2": "chiletrabajos", "3": "linkedin"}
    return portales.get(opcion, "duoclaboral")


def obtener_instancia_portal(nombre: str, page, context):
    """Devuelve la instancia correcta según el portal elegido."""
    if nombre == "chiletrabajos":
        from portales.chiletrabajos.portal import ChileTrabajosPortal
        return ChileTrabajosPortal(page, context)
    elif nombre == "linkedin":
        from portales.linkedin.portal import LinkedinPortal
        return LinkedinPortal(page, context)
    else:  # Default: duoclaboral
        from portales.duoclaboral.portal import DuocLaboralPortal
        return DuocLaboralPortal(page, context)


# ─────────────────────────────────────────────────────────────────
#  MENÚ PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def mostrar_menu(nombre_portal: str):
    emoji_portal = "🔗" if nombre_portal == "linkedin" else ("🎓" if nombre_portal == "duoclaboral" else "💼")
    label_portal = "LinkedIn" if nombre_portal == "linkedin" else ("DuocLaboral" if nombre_portal == "duoclaboral" else "ChileTrabajos")
    console.print(Panel.fit(
        f"[bold yellow]🤖 Bot de Postulaciones[/bold yellow]  {emoji_portal} [cyan]{label_portal}[/cyan]\n"
        "[dim]Automatizador inteligente de postulaciones[/dim]",
        border_style="yellow"
    ))
    console.print("\n  [1] 🚀 Iniciar búsqueda y postulación [bold](modo revisión)[/bold]")
    console.print("  [2] ⚡ Modo automático [bold red](sin confirmación)[/bold red]")
    console.print("  [3] 📊 Ver mis postulaciones")
    console.print("  [4] 🤖 Probar Conexión Groq AI", style="bold yellow")
    console.print("  [5] 🔍 Solo escanear ofertas (sin postular)")
    console.print("  [6] 🔄 Cambiar portal")
    console.print("  [9] ❌ Salir", style="bold red")
    console.print()
    return input("  Elige una opción [1-6, 9]: ").strip()


# ─────────────────────────────────────────────────────────────────
#  FLUJO PRINCIPAL DE POSTULACIÓN
# ─────────────────────────────────────────────────────────────────

def _pausa(min_s=1.0, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))


def run_bot(nombre_portal: str, modo_revision: bool = True):
    console.rule("[yellow]Iniciando bot[/yellow]")

    try:
        validar_config()
    except EnvironmentError as e:
        console.print(f"[red]❌ Error de configuración:\n{e}[/red]")
        console.print("\n[dim]Copia .env.example como .env y completa tus credenciales.[/dim]")
        return

    inicializar_db()

    max_postulaciones = FILTROS.get("max_postulaciones_por_sesion", 10)
    enviadas = 0
    errores = 0

    console.print("\n[cyan]🌐 Abriendo navegador...[/cyan]")
    p, browser, context, page = crear_browser(headless=False)

    try:
        # Instanciar el portal dinámicamente
        portal = obtener_instancia_portal(nombre_portal, page, context)
        console.print(f"[bold cyan]Portal activo: {portal.nombre}[/bold cyan]")

        # Login
        console.print("[cyan]🔑 Iniciando sesión...[/cyan]")
        if not portal.login():
            console.print("[red]❌ No se pudo iniciar sesión. Verifica tus credenciales.[/red]")
            return

        # Aplicar filtros de búsqueda
        carrera = FILTROS.get("carrera", "Ingeniería en informática")
        console.print(f"\n[bold magenta]⚙️ Aplicando filtros de búsqueda: {carrera} | Santiago[/bold magenta]")
        portal.aplicar_filtros_avanzados(carrera)

        # Recorrer páginas de resultados
        paginas_totales = 5
        for num_pagina in range(1, paginas_totales + 1):
            if enviadas >= max_postulaciones:
                break

            console.print(f"\n[bold cyan]📄 Explorando página {num_pagina}...[/bold cyan]")
            tarjetas_datos = portal.obtener_ofertas(paginas=paginas_totales, num_pagina_actual=num_pagina)

            if not tarjetas_datos:
                console.print("  [yellow]⚠️ No hay más ofertas. Fin de la búsqueda.[/yellow]")
                break

            console.print(f"  [dim]Encontradas {len(tarjetas_datos)} ofertas en esta página.[/dim]")

            for idx, oferta_basica in enumerate(tarjetas_datos, 1):
                if enviadas >= max_postulaciones:
                    break

                oferta_id = oferta_basica.get("id", "")
                titulo_basico = oferta_basica.get("titulo", "")[:60]
                url_oferta = oferta_basica.get("url", "")

                # 1. Filtro de duplicados
                if ya_postule(oferta_id):
                    console.print(f"  [dim]⏭  Omitiendo {oferta_id} (ya postulado en DB).[/dim]")
                    continue

                # 2. Abrir en pestaña nueva
                console.print(Panel(
                    f"[bold yellow]OFERTA #{enviadas+1}[/bold yellow] | [bold white]{titulo_basico}[/bold white]\n"
                    f"[dim]ID: {oferta_id}[/dim]",
                    title="[cyan]Procesando[/cyan]",
                    border_style="grey50"
                ))

                console.print(f"  [dim]Abriendo en nueva pestaña: {url_oferta}...[/dim]")
                tab_postulacion = context.new_page()
                try:
                    from playwright_stealth import stealth_sync
                    stealth_sync(tab_postulacion)
                except Exception:
                    pass

                # Instanciar portal en la nueva pestaña
                portal_tab = obtener_instancia_portal(nombre_portal, tab_postulacion, context)

                tab_postulacion.goto(url_oferta, timeout=60000)
                try:
                    tab_postulacion.wait_for_load_state("load", timeout=15000)
                except Exception:
                    pass
                _pausa(1, 2)

                try:
                    # 3. Obtener detalle de la oferta
                    detalle = portal_tab.obtener_detalle_oferta(url_oferta)

                    # Para LinkedIn: si la oferta no es Easy Apply, la saltamos SIN evaluar con IA
                    # (para no gastar tokens de Groq en ofertas que no podemos postular)
                    if nombre_portal == "linkedin" and not detalle.get("es_sencilla"):
                        console.print("  [yellow]↪ Oferta externa (sin Solicitud sencilla). Saltando...[/yellow]")
                        tab_postulacion.close()
                        _pausa(0.5, 1)
                        continue

                    # 4. Evaluación de Relevancia con IA
                    relevante, razon = evaluar_oferta_relevancia(
                        detalle.get("titulo", titulo_basico), detalle.get("descripcion", "")
                    )

                    if relevante:
                        console.print(f"  [bold green]🚀 Iniciando postulación...[/bold green]")
                        estado = portal_tab.postular_oferta(
                            {"id": oferta_id, "titulo": detalle.get("titulo", titulo_basico), "url": url_oferta, "empresa": detalle.get("empresa", "")},
                            detalle,
                            modo_revision=modo_revision
                        )
                        if estado == "enviada":
                            enviadas += 1
                        elif estado in ("error", "error_boton"):
                            errores += 1
                            console.print("  [red]Falló esta oferta, pasando a la siguiente...[/red]")
                        elif estado == "external":
                            console.print("  [yellow]ℹ️  Omitida: es una postulación externa (no Solicitud Sencilla).[/yellow]")
                        elif estado == "revision":
                            console.print("  [blue]👀 Detenido para revisión del usuario.[/blue]")
                    else:
                        console.print(f"  [bold red]⏭  No relevante:[/bold red] {razon}")

                except Exception as e:
                    console.print(f"  [red]⚠️ Error procesando oferta {idx}: {e}[/red]")

                finally:
                    try:
                        tab_postulacion.close()
                    except Exception:
                        pass
                    _pausa(0.5, 1)

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


# ─────────────────────────────────────────────────────────────────
#  SOLO ESCANEAR (sin postular)
# ─────────────────────────────────────────────────────────────────

def solo_escanear(nombre_portal: str):
    console.rule("[cyan]Modo escaneo[/cyan]")
    try:
        validar_config()
    except EnvironmentError as e:
        console.print(f"[red]{e}[/red]")
        return

    inicializar_db()
    p, browser, context, page = crear_browser(headless=False)

    try:
        portal = obtener_instancia_portal(nombre_portal, page, context)
        if not portal.login():
            return

        carrera = FILTROS.get("carrera", "Ingeniería en informática")
        portal.aplicar_filtros_avanzados(carrera)
        ofertas = portal.obtener_ofertas(paginas=3, num_pagina_actual=1)

        tabla = Table(title=f"Ofertas encontradas — {portal.nombre}", box=box.ROUNDED)
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


# ─────────────────────────────────────────────────────────────────
#  VER POSTULACIONES
# ─────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    nombre_portal = seleccionar_portal()

    while True:
        opcion = mostrar_menu(nombre_portal)

        if opcion == "1":
            run_bot(nombre_portal, modo_revision=True)
        elif opcion == "2":
            console.print("\n[red bold]⚠️  MODO AUTOMÁTICO: postulará SIN pedir confirmación[/red bold]")
            confirmar = input("  ¿Estás seguro? [s/N]: ").strip().lower()
            if confirmar == "s":
                run_bot(nombre_portal, modo_revision=False)
        elif opcion == "3":
            ver_postulaciones()
        elif opcion == "4":
            import ai_responder
            console.print("[yellow]Probando conexión a Groq...[/yellow]")
            res = ai_responder.probar_conexion()
            console.print(f"[bold green]Resultado: {res}[/bold green]")
        elif opcion == "5":
            solo_escanear(nombre_portal)
        elif opcion == "6":
            nombre_portal = seleccionar_portal()
        elif opcion == "9":
            console.print("[dim]Chao 👋[/dim]")
            sys.exit(0)
        else:
            console.print("[red]Opción inválida[/red]")

        input("\n  Presiona Enter para continuar...")
