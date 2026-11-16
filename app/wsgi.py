"""Production entry point: python3 -m waitress --listen=127.0.0.1:8102 --threads=4 wsgi:app"""
from versioncontrol import create_app

app = create_app()
