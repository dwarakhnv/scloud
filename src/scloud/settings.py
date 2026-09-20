"""
Django settings for scloud project.

Core paths, secret key, debug flag and data locations all come from
``scloud.constants.Constants``, which reads ``config/config.env``.
"""

from pathlib import Path

from scloud.constants import Constants

BASE_DIR = Path(__file__).resolve().parent.parent

Constants.ensure_dirs()

SECRET_KEY = Constants.SECRET_KEY
DEBUG = Constants.DEBUG
ALLOWED_HOSTS = Constants.ALLOWED_HOSTS


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'storage',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'scloud.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'scloud.wsgi.application'


# Database
# Sqlite file lives under ../data/database.db (see config/config.env)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(Constants.DATABASE_PATH),
    }
}

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'storage:home'
LOGOUT_REDIRECT_URL = 'accounts:login'


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static & media files

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Uploaded files themselves are NOT served through Django's MEDIA machinery;
# they live under Constants.DATA_ROOT and are streamed via storage.views.

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Upload handling - built for multi-gigabyte media files.
#
# DATA_UPLOAD_MAX_MEMORY_SIZE only gates non-file POST data (form fields),
# never the file content itself (that's streamed straight to a temp file on
# disk) - so it's safe to disable outright rather than tie it to the upload
# size limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = None
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # 2MB before spooling to disk

# Where Django (and our own chunk-assembly code) stage in-progress uploads.
# This lives under Constants.DATA_ROOT rather than the OS temp dir so it:
#   (a) shares a drive with the final destination - finalizing a multi-GB
#       upload is a fast os.replace() instead of a slow cross-drive copy, and
#   (b) never fills up a small system/boot drive when DATA_ROOT points at a
#       large external drive.
FILE_UPLOAD_TEMP_DIR = str(Constants.upload_tmp_dir())

EMAIL_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend' if Constants.EMAIL_HOST
    else 'django.core.mail.backends.console.EmailBackend'
)
EMAIL_HOST = Constants.EMAIL_HOST
EMAIL_PORT = Constants.EMAIL_PORT
EMAIL_HOST_USER = Constants.EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = Constants.EMAIL_HOST_PASSWORD
EMAIL_USE_TLS = Constants.EMAIL_USE_TLS
DEFAULT_FROM_EMAIL = Constants.DEFAULT_FROM_EMAIL
