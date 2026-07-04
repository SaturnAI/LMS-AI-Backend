import os
import sys

path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, path)
from dotenv import load_dotenv

load_dotenv()

from src.mongodb.super_admin_master import SuperAdminMaster

super_admin_master = SuperAdminMaster()

request_data = {
    "email": "jainvibhu.2002@gmail.com",
    "name": "Vibhu",
    "phone_number": "9873681590",
}

result = super_admin_master.add_super_admin(request_data=request_data, current_user_email=request_data["email"])

print(result)
