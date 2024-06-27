from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-t3mb3m94f-km24_yg%j-9s)1uo(7=el@8p&ut^t6pvb=$_fmw+"

# SECURITY WARNING: define the correct hosts in production!
ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

GDAL_LIBRARY_PATH = env.str('GDAL_LIBRARY_PATH', None)
GEOS_LIBRARY_PATH = env.str('GEOS_LIBRARY_PATH', None)

try:
    from .local import *
except ImportError:
    pass
