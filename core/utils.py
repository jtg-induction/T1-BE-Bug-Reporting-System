import logging
import os
import smtplib
from urllib.parse import urlencode, urlparse

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

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
    verification_url = f"{settings.FRONTEND_BASE_URL}/signup/complete?{params}"
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


class JiraClientException(Exception):
    """
    Custom exception for errors encountered during Jira API interactions.
    Captures the error message, HTTP status code, and raw response data for easier debugging.
    """

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class JiraClient:
    """
    Utility client for communicating with the Jira REST API.
    Handles URL formatting, basic authentication, and standardized request execution.
    """

    def __init__(self, raw_url, email, access_token):
        if not raw_url.startswith("http"):
            raw_url = f"https://{raw_url}"

        parsed = urlparse(raw_url)
        if not parsed.netloc:
            raise ValueError("Invalid Jira URL format.")

        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.auth = HTTPBasicAuth(email, access_token)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _request(self, method, endpoint, **kwargs):
        """
        Internal helper to execute HTTP requests against the Jira API.
        Automatically handles timeouts, JSON parsing, and standardizes error formatting.
        """
        url = f"{self.base_url}{endpoint}"
        response_data = None
        try:
            response = requests.request(method, url, headers=self.headers, auth=self.auth, timeout=30, **kwargs)

            try:
                response_data = response.json() if response.text else {}
            except ValueError:
                raise JiraClientException(
                    f"Jira returned invalid JSON: {response.text[:200]}", status_code=response.status_code
                )

            if not (200 <= response.status_code < 300):
                error_msg = (
                    response_data.get("errorMessages", ["Unknown Jira Error"])[0]
                    if isinstance(response_data, dict)
                    else "Unknown Jira Error"
                )
                raise JiraClientException(
                    f"Jira API Error: {error_msg}", status_code=response.status_code, response_data=response_data
                )

            return response_data

        except requests.exceptions.RequestException as e:
            raise JiraClientException(f"Network error while contacting Jira: {str(e)}")

    def create_project(self, key, name, description, lead_account_id):
        """
        Creates a new software project in Jira using the provided configuration.
        """
        payload = {
            "key": key,
            "name": name,
            "description": description,
            "projectTypeKey": "software",
            "leadAccountId": lead_account_id,
        }
        return self._request("POST", "/rest/api/3/project", json=payload)
