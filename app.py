import os

from flask import (Flask, redirect, render_template, request, send_from_directory, url_for)
from azure.storage.blob import BlobServiceClient

app = Flask(__name__)

@app.route("/")
def dashboard():
    return render_template("dashboard.html", title="Dashboard")

@app.route("/inventory")
def inventory():
    records = list_inventory_files()
    return render_template("inventory.html", title="Inventory", records=records)

def list_inventory_files():
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    container_name = "inventory"

    blob_service_client = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service_client.get_container_client(container_name)

    files = []
    for blob in container_client.list_blobs():
        files.append(blob.name)

    return files

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