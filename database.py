import json
import os

DB_FILE="accounts_db.json"


def init_db():

    if not os.path.exists(DB_FILE):
        save_db({})

def load_db():
    
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(data):

    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)
