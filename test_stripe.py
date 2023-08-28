import stripe
from devtools import debug

stripe.api_key = "sk_test_51LQ7q1DzTJHYWfEwPPpWGKBy5szd2b5O0OjbhQW9JVLAfCxPpy31zCN91pTe92zbjWmxO9OQ9xafA132bO0BkNiH00wBtBrAxI"

payment_intent_id = "pi_3Nk791DzTJHYWfEw02mD0ylu"


charge = stripe.Charge.list(payment_intent=payment_intent_id, limit=1)

debug(charge)

# charge = stripe.Charge.retrieve(
#   "ch_3Nk791DzTJHYWfEw0cULikcQ",
# )

stripe.Refund.create(
  charge=charge.id,
  amount=,
)


debug(charge)

