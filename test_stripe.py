import os

import stripe
from devtools import debug
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# payment_intent_id = "'pi_3NjuEBDzTJHYWfEw15tkFZkh'"

# charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)
#
# debug(charge)

# charge = stripe.Charge.retrieve(
#   "ch_3Nk791DzTJHYWfEw0cULikcQ",
# )

# stripe.Refund.create(
#     charge=charge.id,
#     amount=1000,
# )

# stripe.PaymentMethod.list(
#   customer='cus_OK8AP9RpPEMrsM',
#   type="card",
# )


try:
    stripe.PaymentIntent.create(
        amount=1099,
        currency='usd',
        # In the latest version of the API, specifying the `automatic_payment_methods` parameter is optional because Stripe enables its functionality by default.
        automatic_payment_methods={"enabled": True},
        customer='cus_OK8AP9RpPEMrsM', # need to get from payment intent
        payment_method='pm_1NotP1DzTJHYWfEwXlBaphWv', # need to get from payment intent
        # return_url='https://example.com/order/123/complete',
        off_session=True,
        confirm=True,
    )
except stripe.error.CardError as e:
    err = e.error
    # Error code will be authentication_required if authentication is needed
    print("Code is: %s" % err.code)
    payment_intent_id = err.payment_intent['id']
    payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

