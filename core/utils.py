import logging
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


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

        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(email, access_token)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "POST"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _request(self, method, endpoint, **kwargs):
        """
        Internal helper to execute HTTP requests against the Jira API.
        Automatically handles retries, timeouts, JSON parsing, and error formatting.
        """
        url = f"{self.base_url}{endpoint}"
        response_data = None
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)

            try:
                response_data = response.json() if response.text else {}
            except ValueError:
                raise JiraClientException(
                    f"Jira returned invalid JSON: {response.text[:200]}",
                    status_code=response.status_code,
                )

            if not (200 <= response.status_code < 300):
                error_msg = (
                    response_data.get("errorMessages", ["Unknown Jira Error"])[0]
                    if isinstance(response_data, dict)
                    else "Unknown Jira Error"
                )
                raise JiraClientException(
                    f"Jira API Error: {error_msg}",
                    status_code=response.status_code,
                    response_data=response_data,
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
