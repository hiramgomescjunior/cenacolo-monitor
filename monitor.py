#!/usr/bin/env python3
"""
Cenacolo Vinciano — Monitor de Ingressos
Alvo: 18 de Setembro de 2026, a partir das 16:30
Prioridade: Visita Individual > Tour em Inglês > Tour em Italiano
"""

import asyncio
import logging
import os
import re
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from playwright.async_api import async_playwright

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────
TARGET_DAY   = 18
TARGET_MONTH = 9
TARGET_YEAR  = 2026
MIN_HOUR     = 16
MIN_MINUTE   = 30

# Gmail — use uma App Password (não sua senha normal)
GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

EVENTS = [
    {
        "name": "Visita Individual (sem tour guiado)",
        "url": "https://cenacolovinciano.vivaticket.it/it/event/cenacolo-vinciano/151991",
        "priority": 1,
    },
    {
        "name": "Tour Guiado em Inglês",
        "url": "https://cenacolovinciano.vivaticket.it/it/event/cenacolo-visite-guidate-a-orario-fisso-in-inglese/238363",
        "priority": 2,
    },
    {
        "name": "Tour Guiado em Italiano",
        "url": "https://cenacolovinciano.vivaticket.it/it/event/cenacolo-visite-guidate-a-orario-fisso-in-italiano/238362",
        "priority": 3,
    },
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────
def send_email(subject: str, body_text: str, body_html: str):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        log.warning("Gmail não configurado — pulando notificação.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = GMAIL_ADDRESS   # envia para si mesmo

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        log.info("✅ Email enviado com sucesso.")
    except Exception as e:
        log.error(f"Falha ao enviar email: {e}")


# ─────────────────────────────────────────────
# UTILITÁRIOS DE HORÁRIO
# ─────────────────────────────────────────────
def parse_time(text: str) -> tuple[int, int] | None:
    m = re.search(r'\b(\d{1,2})[h:.](\d{2})\b', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def is_valid_slot(text: str) -> bool:
    parsed = parse_time(text)
    if not parsed:
        return False
    h, mi = parsed
    return (h, mi) >= (MIN_HOUR, MIN_MINUTE)


# ─────────────────────────────────────────────
# SCRAPER
# ─────────────────────────────────────────────
async def check_event(event: dict) -> list[str]:
    available = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="it-IT",
        )
        page = await ctx.new_page()

        try:
            log.info(f"Verificando: {event['name']}")
            await page.goto(event["url"], wait_until="domcontentloaded", timeout=40_000)
            await page.wait_for_timeout(4_000)

            # ── 1. Navegar até Setembro 2026 ──
            month_keywords = ["settembre", "september", "setembro"]
            found_month = False
            last_month_text = ""

            for attempt in range(30):
                content = (await page.content()).lower()

                if any(kw in content for kw in month_keywords) and "2026" in content:
                    found_month = True
                    log.info("Calendário em Setembro 2026 encontrado.")
                    break

                # Detecta o mês atual para checar se o calendário parou de avançar
                current_month_text = content[:2000]  # primeiros chars têm o mês
                if attempt > 0 and current_month_text == last_month_text:
                    log.info("Calendário chegou ao limite — Setembro 2026 ainda não disponível.")
                    return []
                last_month_text = current_month_text

                # Verifica se o botão "próximo" está desabilitado
                next_btn = page.locator(
                    "button[aria-label*='prossimo'], button[aria-label*='next'], "
                    "[class*='next']:not([disabled]), [class*='arrow-right'], "
                    "[class*='calendar-next'], button:has-text('›'), button:has-text('>')"
                ).first

                if await next_btn.count() == 0:
                    log.info("Botão 'próximo mês' não encontrado — calendário no limite.")
                    return []

                is_disabled = await next_btn.get_attribute("disabled")
                btn_classes = (await next_btn.get_attribute("class") or "").lower()
                if is_disabled is not None or "disabled" in btn_classes:
                    log.info("Botão 'próximo mês' desabilitado — Setembro ainda não abriu.")
                    return []

                await next_btn.click()
                await page.wait_for_timeout(1_200)

            if not found_month:
                log.info(f"Setembro 2026 ainda não disponível: {event['name']}")
                await page.screenshot(path=f"debug_p{event['priority']}_notfound.png")
                return []

            await page.screenshot(path=f"debug_p{event['priority']}_calendar.png")

            # ── 2. Clicar no dia 18 ──
            day_selectors = [
                "[data-date='2026-09-18']",
                "[data-date='18/09/2026']",
                "[data-date='18-09-2026']",
                "td[data-day='18'][data-month='9']",
                "button[data-day='18']",
                "[class*='day']:not([class*='disabled']):not([class*='other-month']):has-text('18')",
                "td:not([class*='disabled']):not([class*='inactive']):has-text('18')",
            ]

            day_clicked = False
            for sel in day_selectors:
                try:
                    els = page.locator(sel)
                    if await els.count() > 0:
                        el = els.first
                        classes = (await el.get_attribute("class") or "").lower()
                        if any(bad in classes for bad in ["disabled", "unavailable", "inactive", "past"]):
                            continue
                        await el.click()
                        await page.wait_for_timeout(2_000)
                        day_clicked = True
                        log.info(f"Dia 18 clicado via: {sel}")
                        break
                except Exception:
                    continue

            if not day_clicked:
                log.info(f"Dia 18/09/2026 não clicável para: {event['name']}")
                await page.screenshot(path=f"debug_p{event['priority']}_noclickday.png")
                return []

            await page.screenshot(path=f"debug_p{event['priority']}_afterday.png")

            # ── 3. Ler horários disponíveis ──
            await page.wait_for_timeout(2_000)
            page_html = await page.content()

            slot_selectors = [
                "[class*='time-slot']:not([class*='disabled'])",
                "[class*='orario']:not([class*='disabled'])",
                "[class*='fascia']:not([class*='esaurit']):not([class*='disabled'])",
                "[class*='slot']:not([class*='disabled']):not([class*='sold'])",
                "button[data-time]",
            ]
            for sel in slot_selectors:
                els = page.locator(sel)
                for i in range(await els.count()):
                    try:
                        txt = (await els.nth(i).inner_text()).strip()
                        if is_valid_slot(txt):
                            classes = (await els.nth(i).get_attribute("class") or "").lower()
                            if not any(bad in classes for bad in ["disabled", "esaurit", "sold", "unavailable"]):
                                available.append(txt)
                    except Exception:
                        pass

            if not available:
                raw_times = re.findall(r'\b(\d{1,2})[h:.](\d{2})\b', page_html)
                for h, mi in raw_times:
                    slot_str = f"{h}:{mi.zfill(2)}"
                    if is_valid_slot(slot_str):
                        available.append(slot_str)

            available = sorted(set(available))

        except Exception as e:
            log.error(f"Erro ao verificar {event['name']}: {e}", exc_info=True)
            try:
                await page.screenshot(path=f"debug_p{event['priority']}_error.png")
            except Exception:
                pass
        finally:
            await browser.close()

    return available


# ─────────────────────────────────────────────
# PRINCIPAL
# ─────────────────────────────────────────────
async def main():
    now_utc = datetime.utcnow()
    brt_hour = (now_utc.hour - 3) % 24
    brt_time = f"{brt_hour:02d}:{now_utc.strftime('%M')}"

    log.info(f"=== Verificação: {now_utc.strftime('%Y-%m-%d %H:%M UTC')} ({brt_time} Brasília) ===")

    found_any = False

    for event in sorted(EVENTS, key=lambda x: x["priority"]):
        slots = await check_event(event)

        if slots:
            found_any = True
            slots_list = "\n".join(f"  • {s}" for s in slots)

            subject = f"🚨 INGRESSOS DISPONÍVEIS — Cenacolo Vinciano 18/09!"

            body_text = (
                f"INGRESSOS DISPONÍVEIS — CORRA!\n\n"
                f"{event['name']}\n"
                f"18 de Setembro de 2026\n\n"
                f"Horários disponíveis (a partir das 16:30):\n"
                f"{slots_list}\n\n"
                f"COMPRAR AGORA:\n{event['url']}\n\n"
                f"Verificado às {brt_time} (horário de Brasília)\n"
                f"Os ingressos esgotam em minutos!"
            )

            body_html = f"""
            <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:20px">
              <h2 style="color:#d32f2f">🚨 INGRESSOS DISPONÍVEIS — CORRA!</h2>
              <p style="font-size:16px">
                <strong>📍 {event['name']}</strong><br>
                📅 18 de Setembro de 2026
              </p>
              <p style="font-size:15px"><strong>🕐 Horários disponíveis (≥ 16:30):</strong></p>
              <ul style="font-size:18px;font-weight:bold;color:#1a237e">
                {"".join(f"<li>{s}</li>" for s in slots)}
              </ul>
              <a href="{event['url']}"
                 style="display:inline-block;margin-top:16px;padding:14px 28px;
                        background:#d32f2f;color:#fff;text-decoration:none;
                        border-radius:8px;font-size:16px;font-weight:bold">
                👉 COMPRAR AGORA
              </a>
              <p style="margin-top:20px;color:#666;font-size:13px">
                Verificado às {brt_time} (horário de Brasília)<br>
                ⚡ Os ingressos esgotam em minutos!
              </p>
            </div>
            """

            log.info(f"🎉 DISPONÍVEL: {event['name']} — {slots}")
            send_email(subject, body_text, body_html)
            break  # Para na primeira opção com disponibilidade

        else:
            log.info(f"❌ Sem disponibilidade: {event['name']}")

    if not found_any:
        log.info("Nenhum ingresso encontrado. Próxima verificação em 20 minutos.")

    log.info("=== Verificação concluída ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
