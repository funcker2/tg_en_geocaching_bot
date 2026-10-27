import os
from dotenv import load_dotenv

load_dotenv()

# ── Environment ───────────────────────────────────────────────────────────────
TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMINS: set[int] = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH: str = os.getenv("DB_PATH", "data/quest_v2.db")
TZ: str = os.getenv("TZ", "Europe/Sofia")

# ── Game constants ────────────────────────────────────────────────────────────
# Base radius in metres within which a team may enter the code at a point
ACTIVATION_RADIUS_M: int = 15

# Cap on the extra slack (metres) granted from phone-reported GPS accuracy;
# without horizontal_accuracy the bonus is 0
ACCURACY_BONUS_CAP_M: int = 10

# A cached location older than this is stale and must not be trusted
LOCATION_STALE_S: int = 120

# Minimum gap between edits of the live-location status message
LIVE_EDIT_MIN_INTERVAL_S: float = 4.0
