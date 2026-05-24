import os

from flask import (Flask, redirect, render_template, request, send_from_directory, url_for)
from azure.storage.blob import BlobServiceClient

from db import SessionLocal
from models import Inventory
from services.inventory_update import update_inventory_quantity

app = Flask(__name__)


@app.route("/")
def dashboard():
    #return "Flask is running"
    return render_template("dashboard.html", title="Dashboard")

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.png')


#app.route("/inventory")
#def inventory():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()
    db.close()
    return render_template("inventory.html", items=items)


#@app.route("/inventory/update", methods=["POST"])
#def update_inventory():
    item_id = request.form["item_id"]
    new_qty = int(request.form["quantity"])

    update_inventory_quantity(item_id, new_qty)

    return redirect(url_for("inventory"))


if __name__ == "__main__":
    app.run(debug=True)





#@app.route('/')
#def index():
#   print('Request for index page received')
#   return render_template('index.html')
#
#
#@app.route('/diaspora_logo.png')
#def favicon():
#    return send_from_directory(
#        os.path.join(app.root_path, 'static'),
#        'diaspora_logo.png',
#        mimetype='image/png'
#    )

#@app.route('/hello', methods=['POST'])
#def hello():
#   name = request.form.get('name')
#
#   if name:
#       print('Request for hello page received with name=%s' % name)
#       return render_template('hello.html', name = name)
#   else:
#       print('Request for hello page received with no name or blank name -- redirecting')
#       return redirect(url_for('index'))


#if __name__ == '__main__':
#   app.run()