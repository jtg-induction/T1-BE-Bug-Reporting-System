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
            allowed_methods=[
                "HEAD",
                "GET",
                "PUT",
                "DELETE",
                "OPTIONS",
                "POST",
            ],
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
                    response_data.get("errorMessages", ["Unknown Jira Error"])
                    if isinstance(response_data, dict)
                    else "Unknown Jira Error"
                )
                field_errors = (
                    response_data.get("errors", {})
                    if isinstance(response_data, dict)
                    else {}
                )
                if field_errors:
                    error_msg = f"{error_msg}. Field errors: {field_errors}"

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
        return self._request("POST", "/rest/api/3/project/", json=payload)

    def update_project(
        self, key, name, description, lead_account_id, project_id
    ):
        """
        Updates an existing software project in Jira using the provided configuration.
        """
        payload = {
            "key": key,
            "name": name,
            "description": description,
            "projectTypeKey": "software",
            "leadAccountId": lead_account_id,
        }
        return self._request(
            "PUT", f"/rest/api/3/project/{project_id}/", json=payload
        )

    def archive_project(self, project_id):
        """
        Archives a software project in Jira using the provided configuration.
        """
        return self._request(
            "POST", f"/rest/api/3/project/{project_id}/archive/"
        )

    def unarchive_project(self, project_id):
        """
        Unarchives a software project in Jira using the provided configuration.
        """
        return self._request(
            "POST", f"/rest/api/3/project/{project_id}/restore/"
        )

    def create_ticket(
        self,
        project_key,
        title,
        description,
        severity=None,
        assignee_id=None,
        deadline=None,
    ):
        """
        Creates a new ticket (issue) in the specified Jira project.
        """
        fields = {
            "project": {"key": project_key},
            "summary": title,
            "issuetype": {"name": "Task"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": description or "No description provided.",
                            }
                        ],
                    }
                ],
            },
        }

        if severity:
            fields["priority"] = {"name": severity}

        if assignee_id:
            fields["assignee"] = {"id": assignee_id}

        if deadline:
            fields["duedate"] = deadline

        payload = {"fields": fields}
        return self._request("POST", "/rest/api/3/issue", json=payload)

    def update_ticket(
        self,
        jira_id,
        title=None,
        description=None,
        severity=None,
        assignee_id=None,
        deadline=None,
        clear_assignee=False,
        clear_deadline=False,
    ):
        """
        Updates an existing ticket (issue) fields in Jira.
        """
        fields = {}
        if title is not None:
            fields["summary"] = title
        if description is not None:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": description or "No description.",
                            }
                        ],
                    }
                ],
            }
        if severity is not None:
            fields["priority"] = {"name": severity}
        if clear_deadline:
            fields["duedate"] = None
        if clear_assignee:
            fields["assignee"] = None
        elif assignee_id is not None:
            fields["assignee"] = {"id": assignee_id}

        if deadline is not None:
            fields["duedate"] = deadline

        if fields:
            return self._request(
                "PUT", f"/rest/api/3/issue/{jira_id}", json={"fields": fields}
            )
        return {}

    def transition_ticket(self, jira_id, local_status_display):
        """
        Transitions a ticket to a new status in Jira.
        """
        transitions_data = self._request(
            "GET", f"/rest/api/3/issue/{jira_id}/transitions"
        )
        transitions = transitions_data.get("transitions", [])

        status_map = {
            "open": "to do",
            "in progress": "in progress",
            "resolved": "in progress",
            "closed": "done",
        }
        jira_target = status_map.get(local_status_display.lower())

        trans_id = next(
            (t["id"] for t in transitions if t["to"]["name"].lower() == jira_target),
            None,
        )

        if trans_id:
            return self._request(
                "POST",
                f"/rest/api/3/issue/{jira_id}/transitions",
                json={"transition": {"id": trans_id}},
            )
        else:
            raise JiraClientException(
                f"No valid Jira transition for status: {jira_target}"
            )

    def delete_ticket(self, jira_id):
        """
        Deletes a ticket (issue) from Jira.
        """
        return self._request("DELETE", f"/rest/api/3/issue/{jira_id}")

    def get_project_issues(self, project_key):
        """
        Fetches a list of issues for a specific Jira project using the updated /search/jql endpoint.
        Limits fields to summary, description, reporter, and assignee to save bandwidth.
        """
        jql = f'project="{project_key}"'
        endpoint = f"/rest/api/3/search/jql?jql={jql}&fields=summary,description,reporter,assignee&maxResults=100"

        return self._request("GET", endpoint)

    def get_ticket(self, jira_id_or_key):
        """
        Fetches the full details of a single ticket from Jira.
        """
        endpoint = f"/rest/api/3/issue/{jira_id_or_key}"
        return self._request("GET", endpoint)
