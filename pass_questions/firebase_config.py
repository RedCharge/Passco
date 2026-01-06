import firebase_admin
from firebase_admin import credentials, auth

# Initialize Firebase Admin
cred = credentials.Certificate("pass_questions/serviceAccountKey.json")  # adjust path if needed
default_app = firebase_admin.initialize_app(cred)
