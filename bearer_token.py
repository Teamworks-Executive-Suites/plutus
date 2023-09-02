import uuid
from devtools import debug


def generate_bearer_token():
    # Generate a random UUID to act as the token
    token = str(uuid.uuid4())

    # Export the new bearer token to the 'bearer_token.txt' file, overwriting any previous content
    # This is where we save the bearer token for future use and verification
    with open("bearer_token.txt", "w") as export_file:
        export_file.write(token)

    print('new bearer token: ', token)

    return token
