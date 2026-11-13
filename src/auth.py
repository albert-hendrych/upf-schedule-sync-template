import os
import json
import logging
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Optional
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.sync_api import sync_playwright

from src.config import get_settings

logger = logging.getLogger(__name__)

_INTERCEPTED_SESSIONS: List[Dict[str, Any]] = []
_INTERCEPTED_START_EPOCH: Optional[int] = None
_INTERCEPTED_END_EPOCH: Optional[int] = None
_INTERCEPTED_ENDPOINT_URL: Optional[str] = None


def get_intercepted_sessions() -> List[Dict[str, Any]]:
    """Retorna les sessions interceptades de la xarxa durant la navegació."""
    return list(_INTERCEPTED_SESSIONS)


def get_intercepted_metadata() -> Dict[str, Any]:
    """Retorna les metadades de la crida Ajax interceptada (start, end, endpoint URL)."""
    return {
        "start_epoch": _INTERCEPTED_START_EPOCH,
        "end_epoch": _INTERCEPTED_END_EPOCH,
        "endpoint_url": _INTERCEPTED_ENDPOINT_URL,
    }


def clear_intercepted_sessions() -> None:
    """Neteja la llista de sessions interceptades i les seves metadades."""
    global _INTERCEPTED_START_EPOCH, _INTERCEPTED_END_EPOCH, _INTERCEPTED_ENDPOINT_URL
    _INTERCEPTED_SESSIONS.clear()
    _INTERCEPTED_START_EPOCH = None
    _INTERCEPTED_END_EPOCH = None
    _INTERCEPTED_ENDPOINT_URL = None


class AuthenticationError(Exception):
    """Llançada quan falla l'autenticació a la universitat."""
    pass


def login_and_get_cookies(target_date: Optional[date] = None) -> Dict[str, str]:
    """
    Executa un navegador Chromium headless mitjançant Playwright per completar
    el login al portal de Matrícula / Secretaria Virtual de la UPF, navegar
    fins a 'Horaris de classe' -> 'Veure Calendari' i extreure les cookies de sessió (JSESSIONID).
    A més, intercepta directament les respostes Ajax de FullCalendar si es carreguen.
    En cas d'error, desa captura de pantalla i traces per a diagnòstic.
    """
    global _INTERCEPTED_START_EPOCH, _INTERCEPTED_END_EPOCH, _INTERCEPTED_ENDPOINT_URL
    settings = get_settings()
    if not settings.UNI_USERNAME or not settings.UNI_PASSWORD:
        raise AuthenticationError("UNI_USERNAME o UNI_PASSWORD no estan configurats a l'entorn.")

    clear_intercepted_sessions()

    trace_dir = Path(settings.TRACE_DIR)
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "trace.zip"
    screenshot_path = trace_dir / "login_failed.png"

    logger.info("Iniciant navegador Chromium headless per autenticar a UPF...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=settings.HEADLESS_BROWSER,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

        # Capturar peticions/respostes Ajax del calendari en qualsevol pàgina del context
        def handle_response(response):
            if "selecionarRangoHorarios" in response.url:
                try:
                    global _INTERCEPTED_START_EPOCH, _INTERCEPTED_END_EPOCH, _INTERCEPTED_ENDPOINT_URL
                    parsed = urllib.parse.urlparse(response.url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if "start" in qs and "end" in qs:
                        s_epoch = int(qs["start"][0])
                        e_epoch = int(qs["end"][0])
                        _INTERCEPTED_START_EPOCH = s_epoch if _INTERCEPTED_START_EPOCH is None else min(_INTERCEPTED_START_EPOCH, s_epoch)
                        _INTERCEPTED_END_EPOCH = e_epoch if _INTERCEPTED_END_EPOCH is None else max(_INTERCEPTED_END_EPOCH, e_epoch)
                    _INTERCEPTED_ENDPOINT_URL = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                    body = response.body()
                    try:
                        text = body.decode("utf-8")
                    except UnicodeDecodeError:
                        text = body.decode("iso-8859-1")
                    data = json.loads(text)
                    if isinstance(data, list) and len(data) > 0:
                        logger.info(f"Interceptades {len(data)} sessions oficials de la crida Ajax del calendari ({_INTERCEPTED_START_EPOCH} a {_INTERCEPTED_END_EPOCH})!")
                        _INTERCEPTED_SESSIONS.extend(data)
                except Exception as e:
                    logger.debug(f"Error processant resposta Ajax interceptada: {e}")

        context.on("response", handle_response)

        # Monitoritzar qualsevol nova finestra o pestanya emergent
        new_pages = []
        context.on("page", lambda p_new: new_pages.append(p_new))

        page = context.new_page()

        try:
            logger.info(f"Navegant a {settings.CAMPUS_LOGIN_URL}...")
            page.goto(settings.CAMPUS_LOGIN_URL, timeout=30000)

            # Accept cookies if banner is present
            cookie_btn = page.locator(".botonCookie, button:has-text('Acceptar')").first
            try:
                if cookie_btn.is_visible(timeout=3000):
                    logger.info("Acceptant bàner de cookies...")
                    cookie_btn.click()
            except Exception:
                pass

            # Locate username input (supports #idUsuario on matricula or general selectors)
            user_input = page.locator(
                "#idUsuario, input[name='idUsuario'], input[name='username'], input[name='user'], input[type='text']:visible"
            ).first
            pass_input = page.locator(
                "#password, input[name='password'], input[type='password']:visible"
            ).first

            if not user_input.is_visible(timeout=5000):
                # Try clicking any login button if on portal landing page
                login_btn_entry = page.locator(
                    "a:has-text('Entra'), a:has-text('Inicia'), a:has-text('Login'), button:has-text('Entra')"
                ).first
                if login_btn_entry.is_visible():
                    login_btn_entry.click()
                    page.wait_for_load_state("networkidle", timeout=10000)

            logger.info("Emplenant credencials d'accés...")
            user_input.fill(settings.UNI_USERNAME)
            pass_input.fill(settings.UNI_PASSWORD)

            # Submit form
            submit_btn = page.locator(
                "button:has-text('Entrar'), button[onClick*='lanzarUrlLogin'], input[type='submit'], button[type='submit'], button:has-text('Inicia')"
            ).first
            submit_btn.click()

            # Wait for load after login
            page.wait_for_load_state("networkidle", timeout=20000)
            logger.info(f"Pàgina carregada després del login. URL: {page.url}")

            # Check if STILL on login page (username input is still visible)
            try:
                if user_input.is_visible(timeout=2000):
                    err_el = page.locator(".alert-danger, .has-error, .text-danger, #msgError, .msgError").first
                    if err_el.is_visible(timeout=2000):
                        err_text = err_el.inner_text().strip()
                        if err_text and "normativa" not in err_text.lower():
                            raise AuthenticationError(f"Error de credencials al portal UPF: {err_text}")
                    raise AuthenticationError(
                        "L'inici de sessió no ha avançat; el formulari continua visible. Revisa les credencials."
                    )
            except AuthenticationError:
                raise
            except Exception:
                pass

            logger.info("Login realitzat amb èxit. Cercant 'Horaris de classe'...")
            horaris_selectors = [
                "a:has-text('Horaris de classe')",
                "button:has-text('Horaris de classe')",
                "input[value*='Horari' i]",
                "a:has-text('Els meus horaris')",
                "button:has-text('Els meus horaris')",
                "a:has-text('Horaris')",
                "button:has-text('Horaris')",
                "a[href*='PubliHoraAlum']",
                "a[href*='secretariavirtual']",
            ]
            clicked_horaris = False
            for frame in [page] + page.frames:
                for sel in horaris_selectors:
                    el = frame.locator(sel).first
                    try:
                        if el.is_visible(timeout=2000):
                            logger.info(f"Fent clic a l'apartat d'horaris ({sel})...")
                            el.click()
                            clicked_horaris = True
                            break
                    except Exception:
                        pass
                if clicked_horaris:
                    break

            page.wait_for_timeout(2000)

            # Check if popup was opened
            cal_page = page
            if new_pages:
                cal_page = new_pages[-1]
                logger.info(f"Pestanya o popup detectat: {cal_page.url}")
                try:
                    cal_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

            logger.info("Cercant botó o enllaç 'Veure Calendari'...")
            cal_selectors = [
                "a:has-text('Veure Calendari')",
                "button:has-text('Veure Calendari')",
                "input[value*='Calendari' i]",
                "input[value*='Veure' i]",
                "a:has-text('Calendari')",
                "button:has-text('Calendari')",
                "a[href*='PubliHoraAlum']",
                "a[href*='secretariavirtual']",
            ]
            clicked_cal = False
            for frame in [cal_page] + cal_page.frames:
                for sel in cal_selectors:
                    el = frame.locator(sel).first
                    try:
                        if el.is_visible(timeout=2000):
                            logger.info(f"Fent clic a 'Veure Calendari' ({sel})...")
                            el.click()
                            cal_page.wait_for_timeout(2000)
                            clicked_cal = True
                            break
                    except Exception:
                        pass
                if clicked_cal:
                    break

            if new_pages:
                cal_page = new_pages[-1]
                try:
                    cal_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

            # Si ja tenim sessions interceptades de la xarxa, el calendari ja ha respost amb èxit
            if _INTERCEPTED_SESSIONS:
                logger.info(f"Ja s'han interceptat {len(_INTERCEPTED_SESSIONS)} sessions oficials. Calendari carregat correctament.")
            else:
                # Cercar si alguna pàgina del context ha arribat a secretariavirtual.upf.edu o matricula.upf.edu/pds
                target_cal_page = None
                for p_ctx in context.pages:
                    if "secretariavirtual.upf.edu" in p_ctx.url or "PubliHoraAlum" in p_ctx.url:
                        target_cal_page = p_ctx
                        break

                if not target_cal_page:
                    logger.info("Navegant el navegador directament a Secretaria Virtual (PubliHoraAlumCalendario)...")
                    try:
                        cal_page.goto(
                            "https://secretariavirtual.upf.edu/pds/control/PubliHoraAlumCalendario?rnd=176.0",
                            timeout=20000
                        )
                        cal_page.wait_for_load_state("networkidle", timeout=10000)
                        target_cal_page = cal_page
                    except Exception as e:
                        logger.warning(f"Navegació a Secretaria Virtual ha tingut un avís: {e}")
                        target_cal_page = cal_page
                else:
                    logger.info(f"Pàgina de calendari activa: {target_cal_page.url}")

                # Esperar a la càrrega del calendari FullCalendar i les peticions Ajax
                try:
                    target_cal_page.wait_for_selector("#calendar, .fc, .fc-view", timeout=8000)
                    logger.info("Contenidor FullCalendar detectat al DOM.")
                except Exception:
                    pass

                target_cal_page.wait_for_timeout(3000)

            # Si s'ha especificat target_date, verificar si el rang interceptat cobreix tota la setmana
            active_cal_page = target_cal_page if ('target_cal_page' in locals() and target_cal_page) else cal_page
            if target_date and active_cal_page:
                tz = ZoneInfo(settings.TIMEZONE)
                monday = target_date - timedelta(days=target_date.weekday())
                sunday = monday + timedelta(days=6)
                start_dt = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=tz)
                end_dt = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=tz)
                target_start_epoch = int(start_dt.timestamp())
                target_end_epoch = int(end_dt.timestamp())

                start_date = datetime.fromtimestamp(_INTERCEPTED_START_EPOCH, tz).date() if _INTERCEPTED_START_EPOCH is not None else None
                is_covered = (
                    _INTERCEPTED_START_EPOCH is not None
                    and _INTERCEPTED_END_EPOCH is not None
                    and start_date is not None
                    and start_date <= monday
                    and _INTERCEPTED_END_EPOCH >= target_end_epoch
                )
                if not is_covered:
                    logger.info(
                        f"Les sessions interceptades inicials ({_INTERCEPTED_START_EPOCH} a {_INTERCEPTED_END_EPOCH}) "
                        f"no cobreixen completament la setmana {monday} a {sunday} ({target_start_epoch} a {target_end_epoch}). "
                        f"Sol·licitant rang complet oficial directament des del navegador..."
                    )
                    try:
                        ajax_path = f"/pds/control/[Ajax]selecionarRangoHorarios?rnd=4236.0&start={target_start_epoch}&end={target_end_epoch}"
                        raw_data = active_cal_page.evaluate(f"""async () => {{
                            const res = await fetch('{ajax_path}', {{
                                method: 'POST',
                                headers: {{ 'X-Requested-With': 'XMLHttpRequest' }}
                            }});
                            const text = await res.text();
                            try {{
                                return JSON.parse(text);
                            }} catch (e) {{
                                return null;
                            }}
                        }}""")
                        if isinstance(raw_data, list):
                            logger.info(f"Obtingudes {len(raw_data)} sessions oficials per a la setmana {monday} a {sunday} des del navegador!")
                            _INTERCEPTED_SESSIONS.extend(raw_data)
                            _INTERCEPTED_START_EPOCH = min(_INTERCEPTED_START_EPOCH or target_start_epoch, target_start_epoch)
                            _INTERCEPTED_END_EPOCH = max(_INTERCEPTED_END_EPOCH or target_end_epoch, target_end_epoch)
                            if not _INTERCEPTED_ENDPOINT_URL:
                                parsed = urllib.parse.urlparse(active_cal_page.url)
                                _INTERCEPTED_ENDPOINT_URL = f"{parsed.scheme}://{parsed.netloc}/pds/control/[Ajax]selecionarRangoHorarios"
                    except Exception as e:
                        logger.warning(f"Avís en sol·licitar setmana des del navegador: {e}")

            # Collect cookies from all pages/domains in context, prioritzant secretariavirtual.upf.edu
            cookies = context.cookies()
            secretaria_cookies = {
                c["name"]: c["value"]
                for c in cookies
                if "secretariavirtual" in c.get("domain", "")
            }
            matricula_cookies = {
                c["name"]: c["value"]
                for c in cookies
                if "matricula" in c.get("domain", "")
            }
            all_cookies = {c["name"]: c["value"] for c in cookies}

            # Prioritat absoluta per a cookies de secretariavirtual.upf.edu
            cookie_dict = {**all_cookies, **matricula_cookies, **secretaria_cookies}
            logger.info(
                f"Cookies capturades al context ({len(cookie_dict)}): {list(cookie_dict.keys())}. "
                f"JSESSIONID de Secretaria Virtual present: {'JSESSIONID' in secretaria_cookies}"
            )

            if not any("JSESSIONID" in k.upper() or "SESSION" in k.upper() for k in cookie_dict.keys()):
                raise AuthenticationError(
                    f"No s'ha obtingut la cookie de sessió JSESSIONID. Cookies trobades: {list(cookie_dict.keys())}"
                )

            context.tracing.stop()
            browser.close()
            logger.info(f"Autenticació UPF completada amb èxit ({len(cookie_dict)} cookies obtingudes).")
            return cookie_dict

        except Exception as exc:
            logger.error(f"Error d'autenticació: {exc}. Desant captura i traces a {trace_dir}...")
            try:
                page.screenshot(path=str(screenshot_path))
                context.tracing.stop(path=str(trace_path))
            except Exception as trace_err:
                logger.error(f"No s'ha pogut desar la traça: {trace_err}")
            browser.close()
            raise AuthenticationError(f"Fallada en l'autenticació a la UPF: {exc}") from exc
