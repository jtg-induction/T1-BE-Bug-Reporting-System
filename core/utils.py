import logging
import re
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlparse

import pytz
import requests
from django.db import models
from django.db.models import Count, F, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from tickets.models import Ticket

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
                    "Received an invalid response format from Jira.",
                    status_code=response.status_code,
                )

            if not (200 <= response.status_code < 300):
                error_msg = (
                    "An unexpected error occurred while communicating with Jira."
                )

                if isinstance(response_data, dict):
                    error_messages = response_data.get("errorMessages", [])
                    field_errors = response_data.get("errors", {})

                    friendly_msgs = []

                    if error_messages:
                        friendly_msgs.extend(error_messages)

                    if field_errors:
                        for field, error in field_errors.items():
                            clean_field = field.replace("_", " ").capitalize()
                            friendly_msgs.append(f"{clean_field}: {error}")

                    if friendly_msgs:
                        error_msg = " | ".join(friendly_msgs)

                raise JiraClientException(
                    error_msg,
                    status_code=response.status_code,
                    response_data=response_data,
                )

            return response_data

        except requests.exceptions.RequestException:
            raise JiraClientException(
                "Network error: Unable to reach Jira. Please check your connection or Jira URL."
            )

    @staticmethod
    def markdown_to_adf(text):
        """
        Converts basic Markdown text into Jira's Atlassian Document Format (ADF).
        Supports: Headings (1-6), Unordered/Ordered Lists, Blockquotes, Paragraphs,
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
        current_blockquote = None

        def flush_containers():
            nonlocal current_list, current_list_type, current_blockquote
            if current_list:
                blocks.append({"type": current_list_type, "content": current_list})
                current_list = None
                current_list_type = None

            if current_blockquote is not None:
                blocks.append({"type": "blockquote", "content": current_blockquote})
                current_blockquote = None

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
                flush_containers()
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
            if heading_match:
                flush_containers()
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
                    flush_containers()
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
                    flush_containers()
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

            # --- Blockquotes ---
            blockquote_match = re.match(r"^>\s?(.*)", line)
            if blockquote_match:
                if current_blockquote is None:
                    flush_containers()
                    current_blockquote = []
                current_blockquote.append(
                    {
                        "type": "paragraph",
                        "content": parse_inline(blockquote_match.group(1)),
                    }
                )
                continue

            flush_containers()
            blocks.append({"type": "paragraph", "content": parse_inline(line)})

        flush_containers()
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

    def update_project(self, key, name, description, lead_account_id, project_id):
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
        return self._request("PUT", f"/rest/api/3/project/{project_id}/", json=payload)

    def archive_project(self, project_id):
        """
        Archives a software project in Jira using the provided configuration.
        """
        return self._request("POST", f"/rest/api/3/project/{project_id}/archive/")

    def unarchive_project(self, project_id):
        """
        Unarchives a software project in Jira using the provided configuration.
        """
        return self._request("POST", f"/rest/api/3/project/{project_id}/restore/")

    def create_ticket(
        self,
        project_key,
        title,
        description,
        severity=None,
        assignee_id=None,
        deadline=None,
        status=None,
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

        create_response = self._request("POST", "/rest/api/3/issue", json=payload)
        if status and create_response and "id" in create_response and status != "Open":
            self.transition_ticket(create_response["id"], status)

        return create_response

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

    def get_project_issues_page(
        self, project_key, additional_jql=None, max_results=15, next_token=None
    ):
        """
        Fetches a list of issues for a specific Jira project.
        Allows an optional custom JQL string to further filter the results.
        """
        jql = f'project="{project_key}"'

        if additional_jql:
            jql += f" AND ({additional_jql})"

        endpoint = "/rest/api/3/search/jql"
        payload = {
            "jql": jql,
            "fields": ["summary", "description", "reporter", "assignee"],
            "maxResults": max_results,
        }

        if next_token:
            payload["nextPageToken"] = next_token

        return self._request("POST", endpoint, json=payload)

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

class ReportGenerator:
    def __init__(self, start_date=None, end_date=None, tz_name="UTC", include_null=False):

        try:
            self.user_tz = pytz.timezone(tz_name) if tz_name else timezone.get_default_timezone()
        except pytz.UnknownTimeZoneError:
            self.user_tz = timezone.get_default_timezone()

        filter_date_format = "%Y-%m-%d"
        self.output_date_format = "%d-%m-%Y"
        self.now = timezone.now()
        self.now_local = self.now.astimezone(self.user_tz)

        if not start_date and not end_date:
            self.start_dt = (
                self.now - timedelta(days=self.now.weekday())
            ).date()
            self.end_dt = (
                self.now + timedelta(days=6 - self.now.weekday())
            ).date()
        else:
            self.start_dt = (
                datetime.strptime(start_date, filter_date_format).date()
                if start_date
                else None
            )
            self.end_dt = (
                datetime.strptime(end_date, filter_date_format).date()
                if end_date
                else None
            )

        date_range_filter = models.Q(deadline__date__range=(self.start_dt, self.end_dt))
        with_null_filter = models.Q(deadline__isnull=True)

        if include_null:
            self.base_filter = models.Q(date_range_filter | with_null_filter)
        else:
            self.base_filter = models.Q(date_range_filter)

    def _get_styled_table(self, data, col_widths, color="#2C3E50"):
            if len(data) <= 1:
                return Paragraph("<i>No tickets with deadlines.</i>", getSampleStyleSheet()["Italic"])
            t = Table(data, colWidths=col_widths)
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(color)),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            return t
    
    def _get_metrics_and_trends(self, base_qs):

        summary_metrics = base_qs.aggregate(
            completed=Count("id", filter=Q(status=4)),
            total=Count("id"),
            missed_deadline=Count("id", filter=Q(deadline__lt=self.now) & ~Q(status=4)),
            open=Count("id", filter=Q(status=1)),
            in_progress=Count("id", filter=Q(status=2)),
            resolved=Count("id", filter=Q(status=3)),
            lowest=Count("id", filter=Q(severity=1)),
            low=Count("id", filter=Q(severity=2)),
            medium=Count("id", filter=Q(severity=3)),
            high=Count("id", filter=Q(severity=4)),
            highest=Count("id", filter=Q(severity=5)),
        )

        deadline_trend = (
            base_qs.filter(deadline__isnull=False).annotate(day=TruncDay("deadline", tzinfo=self.user_tz))
            .values("day")
            .annotate(
                missed=Count(
                    "id",
                    filter=Q(closed_at__date__gt=F("deadline__date"))
                    | Q(closed_at__isnull=True, deadline__lt=self.now),
                ),
                on_time=Count("id", filter=Q(closed_at__date=F("deadline__date"))),
                before_time=Count(
                    "id", filter=Q(closed_at__date__lt=F("deadline__date"))
                ),
            )
            .order_by("day")
        )

        overview = [["Total Tickets", "Completed", "Missed Deadline", "Completion %"]]
        status_distribution = [["Open", "In Progress", "Resolved", "Closed"]]
        severity_distribution = [["Lowest", "Low", "Medium", "High", "Highest"]]
        trends = [["Date", "Missed", "On Time", "Before Time"]]

        if summary_metrics["total"] > 0:
            overview.append([
                summary_metrics["total"],
                summary_metrics["completed"],
                summary_metrics["missed_deadline"],
                f"{(summary_metrics['completed'] / summary_metrics['total'] * 100):.1f}%",
            ])

            status_distribution.append([
                summary_metrics["open"],
                summary_metrics["in_progress"],
                summary_metrics["resolved"],
                summary_metrics["completed"],
            ])

            severity_distribution.append([
                summary_metrics["lowest"],
                summary_metrics["low"],
                summary_metrics["medium"],
                summary_metrics["high"],
                summary_metrics["highest"],
            ])

            for deadline_data in deadline_trend:
                trends.append([
                    deadline_data["day"].astimezone(self.user_tz).strftime(self.output_date_format),
                    deadline_data["missed"],
                    deadline_data["on_time"],
                    deadline_data["before_time"],
                ])

        data = {
            "overview": overview,
            "status_distribution": status_distribution,
            "severity_distribution": severity_distribution,
            "trends": trends,
        }

        return data


    def generate_project_report(self, project_key, project_id, user_ids_raw=""):

        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        self.user_ids = re.findall(uuid_pattern, str(user_ids_raw).lower())

        base_qs = Ticket.objects.filter(project_id=project_id).select_related("assignee", "reporter").filter(self.base_filter)
        
        if self.user_ids:
            base_qs = base_qs.filter(assignee__id__in=self.user_ids)

        metrics_and_trends = self._get_metrics_and_trends(base_qs)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20,
            leftMargin=20,
            topMargin=30,
            bottomMargin=30,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "MainTitle",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#2C3E50"),
            alignment=TA_LEFT,
        )
        sub_style = ParagraphStyle(
            "SubTitle",
            parent=styles["Heading2"],
            fontSize=11,
            textColor=colors.HexColor("#34495E"),
            spaceBefore=10,
            spaceAfter=5,
        )

        story = []

        story.append(Paragraph("Project Comprehensive Report", title_style))
        story.append(
            Paragraph(f"Generated: {self.now_local.strftime(f"{self.output_date_format} %H:%M")}", styles["Normal"])
        )
        story.append(
            Paragraph(
                f"Filter Period: {self.start_dt.strftime(self.output_date_format) or 'All'} to {self.end_dt.strftime(self.output_date_format) or 'Now'}",
                styles["Normal"],
            )
        )

        story.append(Spacer(1, 0.2 * inch))

        story.append(Paragraph("1. Ticket Overview", sub_style))
        t_global_data = metrics_and_trends["overview"]
        story.append(self._get_styled_table(t_global_data, [1.8 * inch] * 4))

        story.append(Paragraph("2. Ticket Status Distribution", sub_style))
        t_status_data = metrics_and_trends["status_distribution"]
        story.append(self._get_styled_table(t_status_data, [1.8 * inch] * 4, "#2980B9"))

        story.append(Paragraph("3. Ticket Severity Distribution", sub_style))
        t_sev_data = metrics_and_trends["severity_distribution"]
        story.append(self._get_styled_table(t_sev_data, [1.44 * inch] * 5, "#7F8C8D"))

        story.append(Paragraph("4. Deadline Performance", sub_style))
        t_dead_data = metrics_and_trends["trends"]
        story.append(self._get_styled_table(t_dead_data, [1.8 * inch] * 4, "#E67E22"))

        story.append(PageBreak())

        story.append(Paragraph("5. Detailed Ticket Log", sub_style))
        t_log_data = [
            [
                "SN",
                "Title",
                "Key",
                "Assignee",
                "Reporter",
                "Updated At",
                "Status",
                "Severity",
                "Deadline",
                "Closed At",
            ]
        ]
        for i, t in enumerate(base_qs, 1):
            title = Paragraph(t.title, style=styles["Normal"])
            key = Paragraph(t.jira_key if t.jira_key else "-", style=styles["Normal"])
            assignee = Paragraph(
                f"{t.assignee.first_name} {t.assignee.last_name}"
                if t.assignee
                else "Unassigned",
                style=styles["Normal"],
            )
            reporter = Paragraph(
                f"{t.reporter.first_name} {t.reporter.last_name}",
                style=styles["Normal"],
            )
            updated_local = (
                t.updated_at.astimezone(self.user_tz) if t.updated_at else None
            )
            deadline_local = t.deadline.astimezone(self.user_tz) if t.deadline else None
            closed_at_local = (
                t.closed_at.astimezone(self.user_tz) if t.closed_at else None
            )
            t_log_data.append(
                [
                    i,
                    title,
                    key,
                    assignee,
                    reporter,
                    updated_local.strftime("%y-%m-%d") if updated_local else "-",
                    t.get_status_display(),
                    t.get_severity_display(),
                    deadline_local.strftime("%y-%m-%d") if deadline_local else "-",
                    closed_at_local.strftime("%y-%m-%d") if closed_at_local else "-",
                ]
            )

        log_widths = [
            0.3 * inch,
            0.9 * inch,
            0.6 * inch,
            0.95 * inch,
            0.95 * inch,
            0.7 * inch,
            0.7 * inch,
            0.7 * inch,
            0.7 * inch,
            0.7 * inch,
        ]
        story.append(self._get_styled_table(t_log_data, log_widths, "#34495E"))

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.drawRightString(
                550, 20, f"Page {doc.page} | Project Key: {project_key}"
            )
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        buffer.seek(0)
        return buffer

    def generate_user_performance_report(self, user):

        initial_queryset = Ticket.objects.filter(assignee=user).filter(self.base_filter)

        metrics_and_trends = self._get_metrics_and_trends(initial_queryset)

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20,
            leftMargin=20,
            topMargin=30,
            bottomMargin=30,
        )
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "MainTitle",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#2980B9"),
            alignment=TA_LEFT,
        )
        sub_style = ParagraphStyle(
            "SubTitle",
            parent=styles["Heading2"],
            fontSize=11,
            textColor=colors.HexColor("#34495E"),
            spaceBefore=10,
            spaceAfter=5,
        )

        story = []
        user_name = f"{user.first_name} {user.last_name}"

        story.append(Paragraph(f"User Performance Report: {user_name}", title_style))
        story.append(
            Paragraph(f"Generated: {self.now_local.strftime(f'{self.output_date_format} %H:%M')}", styles["Normal"])
        )
        story.append(
            Paragraph(
                f"Reporting Period: {self.start_dt.strftime(self.output_date_format) or 'All'} to {self.end_dt.strftime(self.output_date_format) or 'Now'}",
                styles["Normal"],
            )
        )

        story.append(Spacer(1, 0.2 * inch))

        story.append(Paragraph("1. Ticket Overview", sub_style))
        t_global_data = metrics_and_trends["overview"]
        story.append(self._get_styled_table(t_global_data, [1.8 * inch] * 4))

        story.append(Paragraph("2. Ticket Status Distribution", sub_style))
        t_status_data = metrics_and_trends["status_distribution"]
        story.append(self._get_styled_table(t_status_data, [1.8 * inch] * 4, "#2980B9"))

        story.append(Paragraph("3. Ticket Severity Distribution", sub_style))
        t_sev_data = metrics_and_trends["severity_distribution"]
        story.append(self._get_styled_table(t_sev_data, [1.44 * inch] * 5, "#7F8C8D"))

        story.append(Paragraph("4. Deadline Performance", sub_style))
        t_dead_data = metrics_and_trends["trends"]
        story.append(self._get_styled_table(t_dead_data, [1.8 * inch] * 4, "#E67E22"))

        story.append(PageBreak())
        
        story.append(Paragraph("5. Detailed Ticket Log", sub_style))
        log_data = [["SN", "Ticket", "Key", "Status", "Severity", "Deadline"]]

        for i, t in enumerate(initial_queryset, 1):
            title = (Paragraph(t.title, style=styles["Normal"]),)
            deadline_local = t.deadline.astimezone(self.user_tz) if t.deadline else None
            log_data.append(
                [
                    i,
                    title,
                    t.jira_key or "-",
                    t.get_status_display(),
                    t.get_severity_display(),
                    deadline_local.strftime("%y-%m-%d") if deadline_local else "-",
                ]
            )

        log_widths = [
            0.5 * inch,
            2.5 * inch,
            1.0 * inch,
            1.0 * inch,
            1.0 * inch,
            1.2 * inch,
        ]
        story.append(self._get_styled_table(log_data, log_widths, "#34495E"))

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(550, 20, f"Page {doc.page} | User: {user_name}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        buffer.seek(0)
        return buffer
