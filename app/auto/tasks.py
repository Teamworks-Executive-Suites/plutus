import logfire
from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db


def auto_complete():
    """
    Function called every hour, checks if trip is complete and if current
    time is past trip end time.
    """
    with logfire.span('auto_complete'):
        # Iterate through every property
        properties_ref = db.collection('properties').stream()
        for prop in properties_ref:
            # Iterate through every trip in property
            trips = db.collection('trips').where(filter=FieldFilter('propertyRef', '==', prop.reference)).stream()

            for trip in trips:
                if not trip.exists:
                    app_logger.error('Trip document not found for property %s', prop.id)
                    continue  # Changed from return to continue to process the next trip

                if (not trip.get('complete') or trip.get('upcoming')) and (current_time > trip.get('tripEndDateTime')):
                    try:
                        trip.reference.update({'complete': True, 'upcoming': False})
                        app_logger.info('Trip %s for property %s marked as complete', trip.id, prop.id)
                    except Exception as e:
                        app_logger.error('Failed to update trip %s for property %S: %s', trip.id, prop.id, e)

    return True  # Added a return statement for consistency
