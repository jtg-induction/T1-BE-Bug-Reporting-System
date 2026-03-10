import logging
import os
import smtplib
from urllib.parse import urlencode

from django.core.mail import EmailMessage
from dotenv import load_dotenv

load_dotenv()
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL")
if not FRONTEND_BASE_URL:
    raise ValueError("FRONTEND_BASE_URL environment variable is not set")

logger = logging.getLogger(__name__)


def send_verification_email(email, token):
    """
    Constructs and sends a HTML verification email to a new user.

    Args:
        email (str): The recipient's email address.
        token (str/UUID): The unique verification token for the registration link.

    Raises:
        smtplib.SMTPException: Logged if the mail server fails to deliver the message.
    """
    params = urlencode({"token": token, "email": email})
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

    email_message = EmailMessage(subject=subject, body=html_content, to=[email])

    email_message.content_subtype = "html"

    try:
        email_message.send()
    except smtplib.SMTPException as e:
        logger.error(f"Email sending failed: {e}")
