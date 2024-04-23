from flask import Flask
from pymongo import MongoClient

app = Flask(__name__)

from server import routes

# db 연동
client = MongoClient(host='localhost', port=27017)
db = client['e2e_database']
hierarchy = db.ui_hierarchy
action_collection = db.action_collection
app.config['HIERARCHY'] = db.ui_hierarchy
app.config['ACTION_COLLECTION'] = db.action_collection