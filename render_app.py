from threading import Event

from app import create_app
from receipt_extraction import start_worker


def create_render_app():
    application = create_app()
    start_worker(application, Event())
    return application
