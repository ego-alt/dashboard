"""__TITLE__: __DESCRIPTION__"""
import os
import pathlib

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app(config=None):
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    pathlib.Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "dev"))
    if config:
        app.config.update(config)
    # Behind the dashboard's nginx at /__NAME__/: trust its X-Forwarded-*
    # headers, so url_for() and request.script_root include the prefix.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    return app
