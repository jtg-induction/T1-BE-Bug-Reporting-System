import os
from celery import Celery
from dotenv import load_dotenv
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bugreportingsystem.settings')
load_dotenv()
app = Celery("bugreportingsystem")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()