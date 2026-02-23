import os
env = os.getenv('DJANGO_ENV', 'DEV')
if env == 'PROD':
    from .production import *
else:
    from .development import *
