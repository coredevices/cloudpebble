import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings

ENV_VAR_MASK = '******'


def _get_fernet_key():
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key)


def encrypt_value(plaintext):
    f = Fernet(_get_fernet_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext):
    f = Fernet(_get_fernet_key())
    return f.decrypt(ciphertext.encode()).decode()