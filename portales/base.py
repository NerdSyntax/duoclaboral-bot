from abc import ABC, abstractmethod
from playwright.sync_api import Page, BrowserContext

class PortalBase(ABC):
    """Interfaz base para todos los portales de empleo."""
    
    def __init__(self, page: Page, context: BrowserContext):
        self.page = page
        self.context = context

    @abstractmethod
    def login(self) -> bool:
        """Inicia sesión en el portal."""
        pass

    @abstractmethod
    def obtener_ofertas(self, paginas: int = 3) -> list[dict]:
        """Extrae la lista básica de ofertas (título, url, id)."""
        pass

    @abstractmethod
    def obtener_detalle_oferta(self, url: str) -> dict:
        """Extrae el detalle de una oferta (descripción, preguntas, selectores)."""
        pass

    @abstractmethod
    def postular_oferta(self, oferta: dict, detalle: dict, modo_revision: bool = True) -> str:
        """Flujo de postulación para una oferta (rellena form, responde preguntas, envía)."""
        pass
