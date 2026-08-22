"""
hardware.py
=====================================================================
Hardware assets and their warranty information.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"hardware.<function_name>" for url_for().
=====================================================================
"""
from flask import Blueprint, render_template
from permissions import require_elevated_access

bp = Blueprint("hardware", __name__)


@bp.route("/hardware-warranty")
@require_elevated_access
def hardware_warranty():
    return render_template("hardware_warranty.html", title="Hardware & Warranty")
