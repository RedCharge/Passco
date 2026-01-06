# pass_questions/utils/firebase_utils.py

import firebase_admin
from firebase_admin import auth

# Make sure you initialized Firebase in __init__.py
# firebase_admin.initialize_app(cred)

def verify_firebase_token(id_token):
    """Verify a Firebase ID token and return decoded info."""
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token  # contains uid, email, and custom claims
    except Exception:
        return None
