import os
from dotenv import load_dotenv

load_dotenv()

TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMINS: set[int] = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH: str = os.getenv("DB_PATH", "data/quest.db")

# Fixed game constant — radius in metres to consider user "at a point"
ACTIVATION_RADIUS_M: int = 20
