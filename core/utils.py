import logging
import re
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlparse

import requests
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
                    f"Jira returned invalid JSON: {response.text[:200]}",
                    status_code=response.status_code,
                )

            if not (200 <= response.status_code < 300):
                if isinstance(response_data, dict):
                    error_messages = response_data.get("errorMessages", [])
                    error_msg = (
                        error_messages[0] if error_messages else "Unknown Jira Error"
                    )

                    field_errors = response_data.get("errors", {})
                else:
                    error_msg = "Unknown Jira Error"
                    field_errors = {}

                if field_errors:
                    if error_msg == "Unknown Jira Error":
                        error_msg = field_errors
                    else:
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


class ReportGenerator:
    def generate_project_report(
        self, project_key, project_id, start_date=None, end_date=None, user_ids_raw=""
    ):
        filter_date_format = "%Y-%m-%d"
        now = timezone.now()

        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        user_ids = re.findall(uuid_pattern, str(user_ids_raw).lower())

        base_qs = Ticket.objects.filter(project_id=project_id)
        if user_ids:
            base_qs = base_qs.filter(assignee__id__in=user_ids)

        if not start_date and not end_date:
            start_dt = (now - timedelta(days=now.weekday())).date()
            end_dt = now.date()
        else:
            start_dt = (
                datetime.strptime(start_date, filter_date_format).date()
                if start_date
                else None
            )
            end_dt = (
                datetime.strptime(end_date, filter_date_format).date()
                if end_date
                else None
            )

        created_qs = base_qs
        if start_dt:
            created_qs = created_qs.filter(created_at__date__gte=start_dt)
        if end_dt:
            created_qs = created_qs.filter(created_at__date__lte=end_dt)

        summary_metrics = created_qs.aggregate(
            completed=Count("id", filter=Q(status=4)),
            total=Count("id"),
            missed_deadline=Count("id", filter=Q(deadline__lt=now) & ~Q(status=4)),
            open=Count("id", filter=Q(status=1)),
            in_progress=Count("id", filter=Q(status=2)),
            resolved=Count("id", filter=Q(status=3)),
            lowest=Count("id", filter=Q(severity=1)),
            low=Count("id", filter=Q(severity=2)),
            medium=Count("id", filter=Q(severity=3)),
            high=Count("id", filter=Q(severity=4)),
            highest=Count("id", filter=Q(severity=5)),
        )

        deadline_qs = base_qs.filter(deadline__isnull=False)
        if start_dt:
            deadline_qs = deadline_qs.filter(deadline__date__gte=start_dt)
        if end_dt:
            deadline_qs = deadline_qs.filter(deadline__date__lte=end_dt)

        deadline_trend = (
            deadline_qs.annotate(day=TruncDay("deadline"))
            .values("day")
            .annotate(
                missed=Count(
                    "id",
                    filter=Q(closed_at__date__gt=F("deadline__date"))
                    | Q(closed_at__isnull=True, deadline__lt=now),
                ),
                on_time=Count("id", filter=Q(closed_at__date=F("deadline__date"))),
                before_time=Count(
                    "id", filter=Q(closed_at__date__lt=F("deadline__date"))
                ),
            )
            .order_by("day")
        )

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
            Paragraph(f"Generated: {now.strftime('%Y-%m-%d %H:%M')}", styles["Normal"])
        )
        story.append(
            Paragraph(
                f"Filter Period: {start_dt or 'All'} to {end_dt or 'Now'}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.2 * inch))

        def get_table_or_nodata(data_list, col_widths, bg_color="#2C3E50"):
            if len(data_list) <= 1:
                return Paragraph("<i>No tickets with deadlines.</i>", styles["Italic"])
            t = Table(data_list, colWidths=col_widths)
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(bg_color)),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ]
                )
            )
            return t

        story.append(Paragraph("1. Global Ticket Overview", sub_style))
        t_global_data = [
            ["Total Tickets", "Completed", "Missed Deadline", "Completion %"]
        ]
        if summary_metrics["total"] > 0:
            t_global_data.append(
                [
                    summary_metrics["total"],
                    summary_metrics["completed"],
                    summary_metrics["missed_deadline"],
                    f"{(summary_metrics['completed'] / summary_metrics['total'] * 100):.1f}%",
                ]
            )
        story.append(get_table_or_nodata(t_global_data, [1.8 * inch] * 4))

        story.append(Paragraph("2. Ticket Status Distribution", sub_style))
        t_status_data = [["Open", "In Progress", "Resolved", "Closed"]]
        if summary_metrics["total"] > 0:
            t_status_data.append(
                [
                    summary_metrics["open"],
                    summary_metrics["in_progress"],
                    summary_metrics["resolved"],
                    summary_metrics["completed"],
                ]
            )
        story.append(get_table_or_nodata(t_status_data, [1.8 * inch] * 4, "#2980B9"))

        story.append(Paragraph("3. Severity Breakdown", sub_style))
        t_sev_data = [["Lowest", "Low", "Medium", "High", "Highest"]]
        if summary_metrics["total"] > 0:
            t_sev_data.append(
                [
                    summary_metrics["lowest"],
                    summary_metrics["low"],
                    summary_metrics["medium"],
                    summary_metrics["high"],
                    summary_metrics["highest"],
                ]
            )
        story.append(get_table_or_nodata(t_sev_data, [1.44 * inch] * 5, "#7F8C8D"))

        story.append(Paragraph("4. Daily Deadline Performance", sub_style))
        t_dead_data = [["Date", "Missed", "On Time", "Before Time"]]
        for d in deadline_trend[:8]:
            t_dead_data.append(
                [
                    d["day"].strftime("%Y-%m-%d"),
                    d["missed"],
                    d["on_time"],
                    d["before_time"],
                ]
            )
        story.append(get_table_or_nodata(t_dead_data, [1.8 * inch] * 4, "#E67E22"))

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
        for i, t in enumerate(created_qs, 1):
            t_log_data.append(
                [
                    i,
                    (t.title[:15] + "..") if len(t.title) > 17 else t.title,
                    t.jira_key or "-",
                    f"{t.assignee.first_name[0]}. {t.assignee.last_name}"
                    if t.assignee
                    else "N/A",
                    f"{t.reporter.first_name[0]}. {t.reporter.last_name}",
                    t.updated_at.strftime("%y-%m-%d") if t.updated_at else "-",
                    t.get_status_display(),
                    t.get_severity_display(),
                    t.deadline.strftime("%y-%m-%d") if t.deadline else "No Deadline",
                    t.closed_at.strftime("%y-%m-%d") if t.closed_at else "-",
                ]
            )

        log_widths = [
            0.3 * inch,
            1.3 * inch,
            0.6 * inch,
            0.9 * inch,
            0.9 * inch,
            0.6 * inch,
            0.6 * inch,
            0.4 * inch,
            0.65 * inch,
            0.65 * inch,
        ]
        story.append(get_table_or_nodata(t_log_data, log_widths, "#34495E"))

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

    def generate_user_performance_report(self, user, start_date=None, end_date=None):
        filter_date_format = "%Y-%m-%d"
        now = timezone.now()

        if not start_date and not end_date:
            start_dt = (now - timedelta(days=now.weekday())).date()
            end_dt = now.date()
        else:
            start_dt = (
                datetime.strptime(start_date, filter_date_format).date()
                if start_date
                else None
            )
            end_dt = (
                datetime.strptime(end_date, filter_date_format).date()
                if end_date
                else None
            )

        initial_queryset = Ticket.objects.filter(assignee=user)

        created_qs = initial_queryset
        if start_dt:
            created_qs = created_qs.filter(created_at__date__gte=start_dt)
        if end_dt:
            created_qs = created_qs.filter(created_at__date__lte=end_dt)

        metrics = created_qs.aggregate(
            open=Count("id", filter=Q(status=1)),
            in_progress=Count("id", filter=Q(status=2)),
            resolved=Count("id", filter=Q(status=3)),
            closed=Count("id", filter=Q(status=4)),
            total=Count("id"),
            lowest=Count("id", filter=Q(severity=1)),
            low=Count("id", filter=Q(severity=2)),
            medium=Count("id", filter=Q(severity=3)),
            high=Count("id", filter=Q(severity=4)),
            highest=Count("id", filter=Q(severity=5)),
        )

        deadline_qs = initial_queryset.filter(deadline__isnull=False)
        if start_dt:
            deadline_qs = deadline_qs.filter(deadline__date__gte=start_dt)
        if end_dt:
            deadline_qs = deadline_qs.filter(deadline__date__lte=end_dt)

        deadline_trend = (
            deadline_qs.annotate(day=TruncDay("deadline"))
            .values("day")
            .annotate(
                missed=Count(
                    "id",
                    filter=Q(closed_at__date__gt=F("deadline__date"))
                    | Q(closed_at__isnull=True, deadline__lt=now),
                ),
                on_time=Count("id", filter=Q(closed_at__date=F("deadline__date"))),
                before_time=Count(
                    "id", filter=Q(closed_at__date__lt=F("deadline__date"))
                ),
            )
            .order_by("day")
        )

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
            Paragraph(f"Generated: {now.strftime('%Y-%m-%d %H:%M')}", styles["Normal"])
        )
        story.append(
            Paragraph(
                f"Reporting Period: {start_dt or 'All'} to {end_dt or 'Now'}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.2 * inch))

        def get_styled_table(data, col_widths, color="#2C3E50"):
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

        story.append(Paragraph("1. Workload Summary", sub_style))
        status_data = [["Total Tickets", "Open", "In Progress", "Resolved", "Closed"]]
        status_data.append(
            [
                metrics["total"],
                metrics["open"],
                metrics["in_progress"],
                metrics["resolved"],
                metrics["closed"],
            ]
        )
        story.append(get_styled_table(status_data, [1.5 * inch] * 5, "#2C3E50"))

        story.append(Paragraph("2. Assigned Severity Breakdown", sub_style))
        sev_data = [["Lowest", "Low", "Medium", "High", "Highest"]]
        sev_data.append(
            [
                metrics["lowest"],
                metrics["low"],
                metrics["medium"],
                metrics["high"],
                metrics["highest"],
            ]
        )
        story.append(get_styled_table(sev_data, [1.5 * inch] * 5, "#7F8C8D"))

        story.append(Paragraph("3. Deadline Performance (Trend)", sub_style))
        if deadline_trend.exists():
            dead_data = [["Deadline Date", "Missed", "On Time", "Before Time"]]
            for d in deadline_trend[:10]:
                dead_data.append(
                    [
                        d["day"].strftime("%Y-%m-%d"),
                        d["missed"],
                        d["on_time"],
                        d["before_time"],
                    ]
                )
            story.append(get_styled_table(dead_data, [1.8 * inch] * 4, "#E67E22"))
        else:
            story.append(
                Paragraph(
                    "<i>No deadline data available for this period.</i>",
                    styles["Italic"],
                )
            )

        story.append(PageBreak())
        story.append(Paragraph("4. Detailed Task Log", sub_style))
        log_data = [["SN", "Ticket", "Key", "Status", "Severity", "Deadline"]]

        for i, t in enumerate(created_qs, 1):
            log_data.append(
                [
                    i,
                    (t.title[:30] + "..") if len(t.title) > 32 else t.title,
                    t.jira_key or "-",
                    t.get_status_display(),
                    t.get_severity_display(),
                    t.deadline.strftime("%y-%m-%d") if t.deadline else "-",
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
        story.append(get_styled_table(log_data, log_widths, "#34495E"))

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(550, 20, f"Page {doc.page} | User: {user_name}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        buffer.seek(0)
        return buffer
