import logging
import re
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
            raise JiraClientException(
                f"Network error while contacting Jira: {e}"
            ) from e

    @staticmethod
    def markdown_to_adf(text):
        """
        Converts basic Markdown text into Jira's Atlassian Document Format (ADF).
        Supports: Headings (1-6), Unordered/Ordered Lists, Paragraphs,
        and Inline Marks (Bold, Italic, Underline, Strikethrough, Code).
        """
        if not text:
            return {
                "version": 1,
                "type": "doc",
                "content": [{"type": "paragraph", "content": []}],
            }

        blocks = []
        lines = text.split("\n")

        current_list = None
        current_list_type = None

        def flush_list():
            nonlocal current_list, current_list_type
            if current_list:
                blocks.append({"type": current_list_type, "content": current_list})
                current_list = None
                current_list_type = None

        def parse_inline(inline_text):
            """Helper to parse inline markdown like **bold**, *italic*, __underline__"""
            tokens = []
            pattern = re.compile(
                r"(\*\*(.*?)\*\*)|(\*(.*?)\*)|(__(.*?)__)|(~~(.*?)~~)|(`(.*?)`)|([^_*~`]+|[_*~`])"
            )

            for match in pattern.finditer(inline_text):
                if match.group(1):
                    tokens.append(
                        {
                            "type": "text",
                            "text": match.group(2),
                            "marks": [{"type": "strong"}],
                        }
                    )
                elif match.group(3):
                    tokens.append(
                        {
                            "type": "text",
                            "text": match.group(4),
                            "marks": [{"type": "em"}],
                        }
                    )
                elif match.group(5):
                    tokens.append(
                        {
                            "type": "text",
                            "text": match.group(6),
                            "marks": [{"type": "underline"}],
                        }
                    )
                elif match.group(7):
                    tokens.append(
                        {
                            "type": "text",
                            "text": match.group(8),
                            "marks": [{"type": "strike"}],
                        }
                    )
                elif match.group(9):
                    tokens.append(
                        {
                            "type": "text",
                            "text": match.group(10),
                            "marks": [{"type": "code"}],
                        }
                    )
                else:
                    plain = match.group(11)
                    if plain:
                        if tokens and not tokens[-1].get("marks"):
                            tokens[-1]["text"] += plain
                        else:
                            tokens.append({"type": "text", "text": plain})
            return tokens

        for line in lines:
            line = line.strip()

            if not line:
                flush_list()
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
            if heading_match:
                flush_list()
                blocks.append(
                    {
                        "type": "heading",
                        "attrs": {"level": len(heading_match.group(1))},
                        "content": parse_inline(heading_match.group(2)),
                    }
                )
                continue

            ul_match = re.match(r"^[\*\-]\s+(.*)", line)
            if ul_match:
                if current_list_type != "bulletList":
                    flush_list()
                    current_list_type = "bulletList"
                    current_list = []
                current_list.append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": parse_inline(ul_match.group(1)),
                            }
                        ],
                    }
                )
                continue

            ol_match = re.match(r"^\d+\.\s+(.*)", line)
            if ol_match:
                if current_list_type != "orderedList":
                    flush_list()
                    current_list_type = "orderedList"
                    current_list = []
                current_list.append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": parse_inline(ol_match.group(1)),
                            }
                        ],
                    }
                )
                continue

            flush_list()
            blocks.append({"type": "paragraph", "content": parse_inline(line)})

        flush_list()
        if not blocks:
            blocks.append({"type": "paragraph", "content": []})

        return {"version": 1, "type": "doc", "content": blocks}

    @staticmethod
    def adf_to_markdown(adf_dict):
        """
        Converts Jira's Atlassian Document Format (ADF) dictionary back into Markdown string.
        Supports: Paragraphs, Headings, Ordered/Unordered Lists, and Inline Marks
        (Bold, Italic, Underline, Strikethrough, Code).
        """
        if not adf_dict or not isinstance(adf_dict, dict):
            return ""

        def process_element(element, list_type=None, list_index=0, depth=0):
            element_type = element.get("type")
            content = element.get("content", [])

            if element_type == "doc":
                blocks = [process_element(child) for child in content]
                return "\n\n".join(filter(None, blocks))
            elif element_type == "paragraph":
                return "".join(process_element(child) for child in content)

            elif element_type == "heading":
                level = element.get("attrs", {}).get("level", 1)
                heading_text = "".join(process_element(child) for child in content)
                return f"{'#' * level} {heading_text}"

            elif element_type == "bulletList":
                items = [
                    process_element(child, list_type="bullet", depth=depth)
                    for child in content
                ]
                return "\n".join(items)

            elif element_type == "orderedList":
                items = [
                    process_element(
                        child, list_type="ordered", list_index=i, depth=depth
                    )
                    for i, child in enumerate(content, 1)
                ]
                return "\n".join(items)

            elif element_type == "listItem":
                indent = "  " * depth
                item_text = "".join(process_element(child) for child in content)

                if list_type == "bullet":
                    return f"{indent}* {item_text}"
                elif list_type == "ordered":
                    return f"{indent}{list_index}. {item_text}"
                return item_text

            elif element_type == "text":
                text = element.get("text", "")
                marks = element.get("marks", [])

                for mark in marks:
                    m_type = mark.get("type")
                    if m_type == "strong":
                        text = f"**{text}**"
                    elif m_type == "em":
                        text = f"*{text}*"
                    elif m_type == "strike":
                        text = f"~~{text}~~"
                    elif m_type == "code":
                        text = f"`{text}`"
                    elif m_type == "underline":
                        text = f"__{text}__"
                return text

            elif element_type == "hardBreak":
                return "\n"

            else:
                if content:
                    return "".join(process_element(child) for child in content)
                return ""

        return process_element(adf_dict).strip()

    @staticmethod
    def extract_text_from_adf(adf_node):
        """
        Recursively extract plain text from Jira's Atlassian Document Format (ADF).
        """
        if not adf_node or not isinstance(adf_node, dict):
            return ""

        text = ""
        if adf_node.get("type") == "text":
            text += adf_node.get("text", "")

        for child in adf_node.get("content", []):
            text += JiraClient.extract_text_from_adf(child)

        if adf_node.get("type") in ["paragraph", "heading", "listItem"]:
            text += "\n"

        return text

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

    def get_project_issues(self, project_key, additional_jql=None):
        """
        Fetches a list of issues for a specific Jira project.
        Allows an optional custom JQL string to further filter the results.
        """
        jql = f'project="{project_key}"'
        if additional_jql:
            jql += f" AND ({additional_jql})"

        endpoint = "/rest/api/3/search/jql"
        params = {"jql": jql, "fields": "summary,description,reporter,assignee"}
        return self._request("GET", endpoint, params=params)

    def get_ticket(self, jira_id_or_key):
        """
        Fetches the full details of a single ticket from Jira.
        """
        endpoint = f"/rest/api/3/issue/{jira_id_or_key}"
        return self._request("GET", endpoint)

    def get_ticket_comments(self, jira_id_or_key):
        """
        Fetches all comments for a specific issue.
        Using this endpoint exposes the 'parentId' field for nested replies.
        """
        endpoint = f"/rest/api/3/issue/{jira_id_or_key}/comment"
        return self._request("GET", endpoint)

    def add_comment(self, jira_issue_key, text):
        """
        Adds a comment to a specific Jira issue using Atlassian Document Format (ADF).
        Converts Markdown to ADF before sending.
        """
        adf_body = self.markdown_to_adf(text)

        payload = {"body": adf_body}
        return self._request(
            "POST", f"/rest/api/3/issue/{jira_issue_key}/comment", json=payload
        )

    def update_comment(self, jira_issue_key, jira_comment_id, text):
        """
        Updates an existing comment on a Jira issue.
        Converts Markdown to ADF before sending.
        """
        adf_body = self.markdown_to_adf(text)

        payload = {"body": adf_body}
        return self._request(
            "PUT",
            f"/rest/api/3/issue/{jira_issue_key}/comment/{jira_comment_id}",
            json=payload,
        )

    def delete_comment(self, jira_issue_key, jira_comment_id):
        """
        Deletes a specific comment from a Jira issue.
        """
        return self._request(
            "DELETE", f"/rest/api/3/issue/{jira_issue_key}/comment/{jira_comment_id}"
        )
