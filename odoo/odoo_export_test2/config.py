import os
import logging
from dotenv import load_dotenv

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

def load_config():
    load_dotenv()
    config = {
        "url": os.getenv("ODOO_URL", "").rstrip("/"),
        "db": os.getenv("ODOO_DB"),
        "username": os.getenv("ODOO_USERNAME"),
        "api_key": os.getenv("ODOO_API_KEY"),
    }

    if not all(config.values()):
        raise EnvironmentError("Missing environment variables. Set ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY in .env")
    
    return config
