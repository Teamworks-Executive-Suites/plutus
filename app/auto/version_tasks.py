import httpx
from firebase_admin import remote_config

from app.auto._utils import app_logger
from app.firebase_setup import app as firebase_app

BUNDLE_ID = "com.onlineolive.teamworks"
ITUNES_LOOKUP_URL = f"https://itunes.apple.com/lookup?bundleId={BUNDLE_ID}"


def auto_update_cloud_version():
    """Check App Store for latest published version and update Remote Config."""
    try:
        # 1. Fetch current App Store version
        resp = httpx.get(ITUNES_LOOKUP_URL, timeout=10)
        data = resp.json()
        if data.get("resultCount", 0) == 0:
            app_logger.warning("No results from iTunes lookup")
            return

        store_version = data["results"][0]["version"]  # e.g. "2.1.21"

        # 2. Fetch current Remote Config
        template = remote_config.get_server_template(app=firebase_app)
        server_config = template.evaluate()
        current_cloud = server_config.getString("CloudVersion")  # e.g. "v2.1.20"

        # 3. Compare — normalize both to "X.Y.Z" format
        store_clean = store_version.lstrip("v")
        cloud_clean = current_cloud.lstrip("v")

        if store_clean == cloud_clean:
            return  # Already in sync

        # 4. Only update if store version is newer than current cloud version
        store_parts = [int(x) for x in store_clean.split(".")]
        cloud_parts = [int(x) for x in cloud_clean.split(".")]

        if store_parts <= cloud_parts:
            return  # Store version not newer

        # 5. Update Remote Config
        template = remote_config.get_server_template(app=firebase_app)
        template.set("CloudVersion", f"v{store_clean}")
        remote_config.publish_server_template(template)

        app_logger.info(f"Updated CloudVersion: {current_cloud} -> v{store_clean}")

    except Exception as e:
        app_logger.error(f"Version check failed: {e}")
