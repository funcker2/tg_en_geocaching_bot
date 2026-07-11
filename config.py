import os
from dotenv import load_dotenv

load_dotenv()

TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMINS: set[int] = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH: str = os.getenv("DB_PATH", "data/quest.db")

# Fixed game constant — radius in metres to consider user "at a point"
ACTIVATION_RADIUS_M: int = 20

# How much extra slack (metres) to grant to the "nearby" check based on the
# phone-reported GPS accuracy, so a still-converging fix doesn't hide a point
# the player is actually standing on. Capped to avoid turning a bad fix into
# a free pass at a point that's genuinely far away.
ACCURACY_BONUS_CAP_M: int = 25

# horizontal_accuracy above this is flagged to the player as "poor signal"
POOR_ACCURACY_THRESHOLD_M: int = 40

# A cached last-known-location older than this is considered stale and must
# not be trusted for activation (player may have walked away since sending it)
LOCATION_STALE_S: int = 120

# Minimum gap between edited-message (live location) status edits per user,
# to stay well clear of Telegram's edit-message rate limits
LIVE_EDIT_MIN_INTERVAL_S: float = 4.0
