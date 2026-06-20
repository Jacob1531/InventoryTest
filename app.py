import os

from flask import (Flask, redirect, render_template, request, send_from_directory, url_for)
from azure.storage.blob import BlobServiceClient

from db import SessionLocal
from models import Inventory
from services.inventory_update import update_inventory_quantity
from services.image_handler import upload_inventory_image

app = Flask(__name__)


@app.route("/")
def dashboard():
    #return "Flask is running"
    return render_template("dashboard.html", title="Dashboard")

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.png')


#from db import engine
#from models import Base

#@app.route("/init-db")
#def init_db():
    #Base.metadata.create_all(engine)
    #return "Tables created!"


@app.route("/inventory")
def inventory():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()
    db.close()
    return render_template("inventory.html", items=items)


@app.route("/inventory/update", methods=["POST"])
def update_inventory():
    item_id = request.form["item_id"]
    new_qty = int(request.form["quantity"])

    update_inventory_quantity(item_id, new_qty)

    return redirect(url_for("inventory"))


@app.route("/inventory/add", methods=["POST"])
def add_inventory():
    db = SessionLocal()
    #Will likely makle price optional. Also need to eventually do checks against the db
    #to ensure unique entries and no duplicates
    try:
        #Obtains values first
        name = request.form.get("name")
        category = request.form.get("category")
        quantity = request.form.get("quantity")
        price = request.form.get("price")
        image_file = request.files.get("image")

        #Checks validity of fields
        if not all([name, category, quantity, price, image_file]):
            return "Error: All fields including image are required.", 400

        #Checks numbers being valid
        try:
            quantity = int(quantity)
            price = float(price)

            if quantity < 0 or price < 0:
                return "Error: Quantity and price must be positive.", 400

        except:
            return "Error: Invalid numeric input.", 400

        #Validates image type
        if not image_file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            return "Error: Only PNG/JPG images allowed.", 400

        #uploads only after image passes check
        image_path = upload_inventory_image(image_file)

        item = Inventory(
            name=name,
            category=category,
            quantity=quantity,
            price=price,
            image_blob_path=image_path
            is_active=True
        )

        db.add(item)
        db.commit()

        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Server error: {str(e)}", 500

    finally:
        db.close()

#for debug purposes. Wont exist for deployment
@app.route("/debug-db")
def debug_db():
    db = SessionLocal()
    items = db.query(Inventory).all()

    output = []
    for item in items:
        output.append({
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "quantity": item.quantity,
            "price": str(item.price),
            "image": item.image_blob_path
        })

    db.close()
    return {"items": output}

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