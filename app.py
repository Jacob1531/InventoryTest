import os

from flask import (Flask, redirect, render_template, request, send_from_directory, url_for)
from azure.storage.blob import BlobServiceClient
from sqlalchemy import text

from db import SessionLocal, engine
from models import Inventory, InventoryAudit
from services.inventory_update import update_inventory_quantity
from services.image_handler import generate_image_url, upload_inventory_image

from auth import get_user
#from services.notifications import send_low_stock_email

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

#can be used as a one time db migration when needed as a workaround
#@app.route("/run-migration-once")
#def run_migration_once():
#    with engine.connect() as conn:
#        conn.execute(text("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER"))
#        conn.commit()
#    return "Migration applied"


@app.route("/inventory")
def inventory():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()

    
    for item in items:
        if item.image_blob_path:
            item.image_url = generate_image_url(item.image_blob_path)
        else:
            item.image_url = None


    db.close()
    return render_template("inventory.html", items=items)


@app.route("/inventory/update", methods=["POST"])
def update_inventory():
    id = request.form["id"]
    new_qty = int(request.form["quantity"])

    update_inventory_quantity(id, new_qty)
    return redirect(url_for("inventory"))

@app.route("/inventory/edit/<int:item_id>", methods=["POST"])
def edit_inventory_item(item_id):
    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()
        if not item:
            return "Item not found", 404
        
        new_name = request.form.get("name")
        new_category = request.form.get("category")
        new_quantity = int(request.form.get("quantity"))
        new_price = float(request.form.get("price"))

        if not new_name:
            return "Name is required", 400
        if not new_category:
            return "Category is required", 400
        
        try:
            new_quantity = int(new_quantity)
            new_price = float(new_price)
        except:
            return "Invalid numeric input", 400

        if new_quantity < 0:
            return "Quantity can't be negative", 400
        if new_price < 0.01:
            return "Price must be positive", 400
        
        old_quantity = item.quantity

        changes = []
        if item.name != new_name:
            changes.append(("name", item.name, new_name))
        if item.category != new_category:
            changes.append(("category", item.category, new_category))
        if item.quantity != new_quantity:
            changes.append(("quantity", str(item.quantity), str(new_quantity)))
        if float(item.price) != new_price:
            changes.append(("price", str(item.price), str(new_price)))

        item.name = new_name
        item.category = new_category
        item.quantity = new_quantity
        item.price = new_price

        image_file = request.files.get("image")

        if image_file and image_file.filename:
            image_path = upload_inventory_image(image_file)
            item.image_blob_path = image_path
            changes.append(("image", "previous image", "new image"))

        for field_name, old_value, new_value in changes:
            audit = InventoryAudit(
                item_id=str(item.id),
                action="UPDATE",
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                changed_by=get_user(),
                source="UI"
            )
            db.add(audit)
        
        #crossed_threshold = (
        #    item.low_stock_threshold is not None
        #    and old_quantity >= item.low_stock_threshold
        #    and new_quantity < item.low_stock_threshold
        #)

        #if crossed_threshold:
        #    try:
        #        send_low_stock_email(item)
        #    except Exception as e:
        #        print(f"Low stock email failed: {e}")

        db.commit()
        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Update failed: {str(e)}", 500

    finally:
        db.close()


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
            image_blob_path=image_path,
            is_active=True
        )

        db.add(item)
        db.flush()  # populates item.id before commit, needed for the audit entry below

        audit = InventoryAudit(
            item_id=str(item.id),
            action="ADD",
            field_name=None,
            old_value=None,
            new_value=name,
            changed_by=get_user(),
            source="UI"
        )

        db.add(audit)
        db.commit()

        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Server error: {str(e)}", 500

    finally:
        db.close()


@app.route("/inventory/delete/<int:item_id>", methods=["POST"])
def delete_inventory(item_id):
    db = SessionLocal()

    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()

        if not item:
            return "Item not found", 404

        # Soft delete
        item.is_active = False

        audit = InventoryAudit(
            item_id=str(item.id),
            action="DELETE",
            field_name="is_active",
            old_value="True",
            new_value="False",
            changed_by=get_user(),
            source="UI"
        )
        db.add(audit)
        
        db.commit()

        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Delete failed: {str(e)}", 500

    finally:
        db.close()

@app.route("/reports")
def reports():
    db = SessionLocal()
    logs = db.query(InventoryAudit).order_by(InventoryAudit.changed_at.desc()).all()

    # Map item_id -> item name for display
    item_names = {
        str(item.id): item.name
        for item in db.query(Inventory).all()
    }

    for log in logs:
        log.item_name = item_names.get(log.item_id, log.item_id)

    db.close()
    return render_template("reports.html", logs=logs)

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
            "price": item.price,
            "image": item.image_blob_path,
            "is_active": item.is_active
        })

    db.close()
    return {"items": output}

if __name__ == "__main__":
    app.run(debug=True)

@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/settings/database")
def database_settings():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()
    db.close()
    return render_template("database_settings.html", items=items)


@app.route("/settings/database/update/<int:item_id>", methods=["POST"])
def update_threshold(item_id):
    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()
        if not item:
            return "Item not found", 404

        threshold = request.form.get("threshold")
        item.low_stock_threshold = int(threshold) if threshold else None

        db.commit()
        return redirect(url_for("database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to update threshold: {str(e)}", 500
    finally:
        db.close()


@app.route("/settings/account")
def account_settings():
    return render_template("account_settings.html")



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