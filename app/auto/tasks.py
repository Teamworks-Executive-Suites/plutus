from google.cloud.firestore_v1 import FieldFilter

from app.auto._utils import app_logger
from app.firebase_setup import current_time, db


def auto_complete():
    """
    Function called every hour, checks if trip is complete and if current
    time is past trip end time.
    """
    app_logger.info('Running Auto Complete')

    # Iterate through every property
    properties_ref = db.collection('properties').stream()
    for prop in properties_ref:
        # Iterate through every trip in property
        trips = db.collection('trips').where(filter=FieldFilter('propertyRef', '==', prop.reference)).stream()

        for trip in trips:
            if not trip.exists:
                app_logger.error(f'Trip document not found for property {prop.id}')
                continue  # Changed from return to continue to process the next trip

            if (not trip.get('complete') or trip.get('upcoming')) and (current_time > trip.get('tripEndDateTime')):
                try:
                    trip.reference.update({'complete': True, 'upcoming': False})
                    app_logger.info(f'Trip {trip.id} for property {prop.id} marked as complete')
                except Exception as e:
                    app_logger.error(f'Failed to update trip {trip.id} for property {prop.id}: {str(e)}')

    app_logger.info('Auto Complete Run Completed')
    return True  # Added a return statement for consistency
