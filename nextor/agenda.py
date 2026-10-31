"""Agenda do Nextor: le a Google Agenda por um endereco privado iCal (sem Google Cloud)."""
import urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from . import config

try:
    from icalendar import Calendar
    import recurring_ical_events
except ImportError:
    Calendar = None

TZ = ZoneInfo(config.FUSO)
DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


def _baixar_ics(url: str) -> bytes:
    url = url.replace("webcal://", "https://")
    req = urllib.request.Request(url, headers={"User-Agent": "Nextor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _normaliza(ev) -> dict:
    inicio = ev.get("DTSTART").dt
    dia_inteiro = not isinstance(inicio, datetime)
    if isinstance(inicio, datetime) and inicio.tzinfo is not None:
        inicio = inicio.astimezone(TZ)
    return {
        "titulo": str(ev.get("SUMMARY", "(sem titulo)")),
        "inicio": inicio,
        "dia_inteiro": dia_inteiro,
    }


def eventos_entre(inicio: date, fim: date, url: str = "") -> list:
    url = url or config.AGENDA_ICAL
    if not url or Calendar is None:
        return []
    cal = Calendar.from_ical(_baixar_ics(url))
    brutos = recurring_ical_events.of(cal).between(inicio, fim)
    eventos = [_normaliza(e) for e in brutos]
    eventos.sort(key=lambda e: (
        e["inicio"] if isinstance(e["inicio"], datetime)
        else datetime(e["inicio"].year, e["inicio"].month, e["inicio"].day, tzinfo=TZ)
    ))
    return eventos


def eventos_hoje(url: str = "") -> list:
    hoje = datetime.now(TZ).date()
    return eventos_entre(hoje, hoje + timedelta(days=1), url)


def eventos_proximos(dias: int = 7, url: str = "") -> list:
    hoje = datetime.now(TZ).date()
    return eventos_entre(hoje, hoje + timedelta(days=dias), url)


def _hora_falada(dt) -> str:
    return f"as {dt.hour} horas" if dt.minute == 0 else f"as {dt.hour} e {dt.minute:02d}"


def resumo_falado(eventos: list, prefixo_dia: bool = False) -> str:
    if not eventos:
        return "Voce nao tem compromissos marcados."
    partes = []
    hoje = datetime.now(TZ).date()
    for e in eventos:
        inicio = e["inicio"]
        if e["dia_inteiro"]:
            quando, dia = "", inicio
        else:
            quando, dia = _hora_falada(inicio), inicio.date()
        if prefixo_dia and dia != hoje:
            quando = f"{DIAS_SEMANA[dia.weekday()]} dia {dia.day} {quando}".strip()
        partes.append(f"{quando}, {e['titulo']}".strip(", ").strip())
    if len(partes) == 1:
        return f"Voce tem um compromisso: {partes[0]}."
    return f"Voce tem {len(partes)} compromissos. " + "; ".join(partes) + "."


if __name__ == "__main__":
    print(resumo_falado(eventos_proximos(7), prefixo_dia=True))
