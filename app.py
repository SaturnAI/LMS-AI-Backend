import os
import sys

from dotenv import load_dotenv

load_dotenv()

path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, path)

from scripts import create_app

app = create_app()


# run with: uvicorn app:app --reload --port 5015
