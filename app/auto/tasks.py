import logging
from google.cloud.firestore_v1 import FieldFilter
from devtools import debug

from app.firebase_setup import db, current_time

def auto_complete():
    """
    Function called every hour, checks if trip is complete and if current
    time is past trip end time.
    """
    logging.info("Running Auto Complete")

    # Iterate through every property
    properties_ref = db.collection("properties").stream()
    for prop in properties_ref:
        # Iterate through every trip in property
        trips = (
            db.collection("trips")
            .where(filter=FieldFilter("propertyRef", "==", prop.reference))
            .stream()
        )

        for trip in trips:
            if not trip.exists:
                logging.error(f"Trip document not found for property {prop.id}")
                continue  # Changed from return to continue to process the next trip

            if (not trip.get("complete") or trip.get("upcoming")) and (
                current_time > trip.get("tripEndDateTime")
            ):
                try:
                    trip.reference.update({"complete": True, "upcoming": False})
                    logging.info(
                        f"Trip {trip.id} for property {prop.id} marked as complete"
                    )
                except Exception as e:
                    logging.error(
                        f"Failed to update trip {trip.id} for property {prop.id}: {str(e)}"
                    )

    logging.info("Auto Complete Run Completed")
    return True  # Added a return statement for consistency
