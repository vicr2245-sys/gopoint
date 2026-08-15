"""
Entry point. Wires up whichever providers have API keys configured (see
config.py / .env) and launches the desktop window.

Run with: python main.py
"""
import logging
import sys
import traceback

from PyQt5.QtWidgets import QApplication

from config import diagnose_env_setup, get_configured_providers
from core.route_engine import RouteEngine
from ui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

IS_FROZEN = getattr(sys, "frozen", False)


def _pause_before_exit():
    """
    Keeps the console window open when this is a packaged .exe launched by
    double-clicking from Explorer — that launches a fresh console which
    closes the INSTANT the process exits, so any printed error/traceback
    would otherwise flash and vanish before there's any chance to read it.
    Skipped for `python main.py`, where the terminal you launched it from
    stays open on its own regardless.
    """
    if IS_FROZEN:
        input("\nPress Enter to exit...")


import os
import ctypes
from PyQt5.QtGui import QIcon

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, relative_path)

def main():
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('GoPoint.AI.RoutePlanner.1.0')
        except Exception:
            pass

    providers, geocode_providers = get_configured_providers()

    # providers is never empty now (OSRM needs no key and is always
    # included), so this can't hard-fail the way it used to when neither
    # ORS nor Mapbox was configured. But running silently in that reduced
    # mode when the user actually believes they set up a key would be
    # confusing — diagnose and surface the real reason clearly instead.
    startup_notice = diagnose_env_setup()
    if startup_notice:
        print(startup_notice)

    engine = RouteEngine(providers, geocode_providers)

    app = QApplication(sys.argv)
    
    icon_path = get_resource_path("gopoint_icon.ico")
    if not os.path.exists(icon_path):
        icon_path = get_resource_path("gopoint_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow(engine, startup_notice=startup_notice)
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # intentional exits (including the one above) — let them through untouched
    except Exception:
        print("\nRoute Planner crashed on startup:\n")
        traceback.print_exc()
        _pause_before_exit()
        sys.exit(1)
