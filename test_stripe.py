import stripe
from devtools import debug
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

payment_intent_id = "pi_3Nk791DzTJHYWfEw02mD0ylu"


charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)

debug(charge)

# charge = stripe.Charge.retrieve(
#   "ch_3Nk791DzTJHYWfEw0cULikcQ",
# )

stripe.Refund.create(
  charge=charge.id,
  amount=1000,
)


debug(charge)

