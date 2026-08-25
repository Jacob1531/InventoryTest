"""
app.py
=====================================================================
Application setup and blueprint registration.

Routes live in blueprints/ - one module per domain:
  main       dashboard, favicon, one-time DB migrations
  inventory  inventory list, add/edit/delete, low stock
  orders     placing/receiving/cancelling stock orders
  imports    the three-step Excel import flow
  reports    inventory change history
  files      file submissions
  settings   settings hub, database settings, account settings
  hardware   hardware assets and warranty info

Shared permission checks live in permissions.py. Business logic lives
in services/. This file only wires things together.

Endpoint names are namespaced by blueprint, e.g.
url_for("inventory.inventory") rather than url_for("inventory").
The URLs themselves are unchanged.
=====================================================================
"""
import os

from flask import Flask
from flask_wtf.csrf import CSRFProtect, CSRFError

from auth import get_user

from blueprints.main import bp as main_bp
from blueprints.inventory import bp as inventory_bp
from blueprints.orders import bp as orders_bp
from blueprints.imports import bp as imports_bp
from blueprints.reports import bp as reports_bp
from blueprints.files import bp as files_bp
from blueprints.settings import bp as settings_bp
from blueprints.hardware import bp as hardware_bp

app = Flask(__name__)

# Required for CSRF token signing. Set FLASK_SECRET_KEY in the Azure App
# Service configuration (same place as PGUSER/PGPASSWORD/etc).
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
csrf = CSRFProtect(app)

# Flask-WTF expires CSRF tokens after 1 hour by default, on a clock
# separate from the session - so a tab left open over lunch would fail on
# submit even though the user is still signed in, losing whatever they had
# typed. 28800 seconds (8 hours) covers a full workday while keeping a
# hard cap as a backstop.
#
# If a token does expire past this window, handle_csrf_error below returns
# a clean "session expired, please refresh" message rather than Flask's
# raw HTML error page.
app.config["WTF_CSRF_TIME_LIMIT"] = 28800

# Applies to every request, not just Files - there was previously no cap
# anywhere in the app. 25MB comfortably covers normal documents/scans for
# Files and is far more than inventory images or Excel imports need, so
# this shouldn't affect any existing upload path.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

app.register_blueprint(main_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(imports_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(files_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(hardware_bp)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    # Flask-WTF's default is a full HTML error page. Every form in this app
    # submits via fetch() and shows the response body inline, so an HTML
    # page would get dumped into a small error banner as raw markup.
    # Returning plain text keeps that banner readable, and reads sensibly
    # on its own for the few plain (non-fetch) form posts too.
    return (
        "Your session expired while this page was open. "
        "Please refresh the page and try again.",
        400,
    )


@app.errorhandler(413)
def file_too_large(e):
    # Without this, exceeding MAX_CONTENT_LENGTH would show Werkzeug's raw
    # default error page - same "never show a raw error page" reasoning
    # as the fetch-based form submissions elsewhere in the app. The
    # upload forms already read the response body as plain text on
    # failure and display it inline, so this renders in place automatically.
    return "That file is too large. Maximum upload size is 25 MB.", 413


@app.context_processor
def inject_current_user():
    """Makes the signed-in user's identity available in every template
    (used by the header's account chip) without passing it through every
    single render_template call."""
    return {"header_user": get_user()}


if __name__ == "__main__":
    # Only turns on the interactive debugger if FLASK_DEBUG=true is set
    # locally. gunicorn (the real entry point in Azure) never hits this
    # block at all, but this keeps the file itself safe if it's ever run
    # directly (e.g. `python app.py` on a dev machine or test VM).
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)
