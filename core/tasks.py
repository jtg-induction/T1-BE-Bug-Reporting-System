import os
from html import escape
from urllib.parse import urlencode

from celery import shared_task
from django.core.mail import EmailMessage

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL")


@shared_task(bind=True, max_retries=3)
def send_verification_email(self, email, token):

    params = urlencode({"token": str(token), "email": email})
    verification_url = f"{FRONTEND_BASE_URL}/signup/complete?{params}"

    subject = "Let's get you started!"

    html_content = f"""
        <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello User,</h2>
                        <p>Thank you for registering. Please click the button below to verify your email address:</p>
                        
                        <!-- Bulletproof Button -->
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{verification_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        Verify Email
                                    </a>
                                </td>
                            </tr>
                        </table>
                        
                        <p>If you did not register, please ignore this email.</p>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
    """

    email_message = EmailMessage(
        subject=subject, body=html_content, to=[email]
    )

    email_message.content_subtype = "html"
    try:
        email_message.send()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def send_invitation_email(self, pid, title, email):

    accept_url = f"{FRONTEND_BASE_URL}/projects/{pid}/accept"
    reject_url = f"{FRONTEND_BASE_URL}/projects/{pid}/reject"
    safe_title = escape(title)
    subject = "Ready for a new Journey?"

    html_content = f"""
        <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello User,</h2>
                        <p>You have been invited to the Project {safe_title}</p>
                        
                        <!-- Bulletproof Button -->
                        <table cellspacing="4" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#00FF00" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{accept_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        Accept
                                    </a>
                                </td>
                                <td bgcolor="#FF0000" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{reject_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        Reject
                                    </a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>
    """

    email_message = EmailMessage(
        subject=subject, body=html_content, to=[email]
    )

    email_message.content_subtype = "html"
    try:
        email_message.send()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
