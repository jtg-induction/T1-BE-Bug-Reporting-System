import os
from datetime import timedelta

from celery import shared_task
from django.core.mail import EmailMessage
from django.utils import timezone
from dotenv import load_dotenv

from tickets.models import Ticket, TicketSubscriber

load_dotenv()
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL")


@shared_task(bind=True, max_retries=3)
def send_ticket_assignment_email(
    self, email, ticket_id, ticket_title, project_id, project_title
):
    ticket_url = f"{FRONTEND_BASE_URL}/project/{project_id}/tickets/{ticket_id}"

    subject = f"Ticket Assigned: {ticket_title}"

    html_content = f"""
        <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>You have been assigned to a new ticket in the project <strong>{project_title}</strong>.</p>
                        <p><strong>Ticket Title:</strong> {ticket_title}</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
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

    email_message = EmailMessage(subject=subject, body=html_content, to=[email])

    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def notify_ticket_subscribers(self, ticket_id, new_status):
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        return

    subscribers = TicketSubscriber.objects.filter(
        ticket=ticket, status=TicketSubscriber.Status.SUBSCRIBED
    ).select_related("user")

    emails = [sub.user.email for sub in subscribers if sub.user.email]

    if not emails:
        return

    ticket_url = f"{FRONTEND_BASE_URL}/project/{ticket.project.id}/tickets/{ticket.id}"
    subject = f"Ticket Status Updated: {ticket.title}"

    html_content = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>A ticket you are subscribed to has been updated.</p>
                        <p><strong>Ticket:</strong> {ticket.title}</p>
                        <p><strong>New Status:</strong> {new_status}</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
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

    email_message = EmailMessage(subject=subject, body=html_content, bcc=emails)

    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def notify_reporter_resolved(self, reporter_email, ticket_title, ticket_id, project_id):

    ticket_url = f"{FRONTEND_BASE_URL}/project/{project_id}/tickets/{ticket_id}"

    subject = f"Resolved: {ticket_title}"

    html_content = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5">
    <tr>
        <td align="center" style="padding: 20px;">
            <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                <tr>
                    <td>
                        <h2>Hello,</h2>
                        <p>Great news! A ticket you reported has been marked as <strong>Resolved</strong>.</p>
                        <p><strong>Ticket Title:</strong> {ticket_title}</p>
                        <p>Please review the ticket to confirm the issue is fixed. If everything looks good, you can now mark it as Closed.</p>
                        
                        <table cellspacing="0" cellpadding="0" border="0">
                            <tr>
                                <td bgcolor="#28a745" style="padding: 10px 20px; border-radius: 4px;">
                                    <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                        View Ticket
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
        subject=subject, body=html_content, to=[reporter_email]
    )

    email_message.content_subtype = "html"
    email_message.send()


@shared_task(bind=True, max_retries=3)
def send_deadline_reminder(self, ticket_id, is_two_hour=False):
    try:
        ticket = Ticket.objects.select_related("assignee", "reporter", "project").get(
            id=ticket_id
        )
    except Ticket.DoesNotExist:
        return f"Ticket {ticket_id} no longer exists. Task aborted."

    to_emails = []
    cc_emails = []

    if ticket.assignee and ticket.assignee.email:
        to_emails.append(ticket.assignee.email)
        if ticket.reporter and ticket.reporter.email:
            cc_emails.append(ticket.reporter.email)
    else:
        if ticket.reporter and ticket.reporter.email:
            to_emails.append(ticket.reporter.email)

    assignee_name = (
        ticket.assignee.get_full_name() or ticket.assignee.email
        if ticket.assignee
        else "Unassigned"
    )

    ticket_url = f"{FRONTEND_BASE_URL}/projects/{ticket.project.id}/tickets/{ticket.id}"

    if ticket.status == Ticket.Status.RESOLVED:
        status_msg = (
            "This ticket is marked as RESOLVED. Please verify if it can be closed."
        )
    else:
        status_msg = "Please ensure the required work is completed on time."

    if is_two_hour:
        subject = f"Urgent Deadline Reminder: {ticket.title} (Due in 2 hours)"
        time_text = "is due in approximately <b>2 hours</b>"
    else:
        subject = f"Deadline Reminder: {ticket.title}"
        time_text = "has a deadline of <b>tomorrow</b>"

    message = f"""
    <table width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f5f5" style="font-family: Arial, sans-serif;">
        <tr>
            <td align="center" style="padding: 20px;">
                <table width="600" cellspacing="0" cellpadding="0" border="0" style="background-color: #ffffff; padding: 20px; border-radius: 5px;">
                    <tr>
                        <td>
                            <h2>Hello,</h2>
                            <p>This is an automated reminder that the ticket <b>'{ticket.title}'</b> in project <b>'{ticket.project.title}'</b> {time_text} ({ticket.deadline}).</p>
                            
                            <p>
                                <strong>Assignee:</strong> {assignee_name}<br>
                                <strong>Current Status:</strong> {ticket.get_status_display()}
                            </p>
                            
                            <p>{status_msg}</p>
                            
                            <table cellspacing="0" cellpadding="0" border="0" style="margin-top: 20px;">
                                <tr>
                                    <td bgcolor="#007bff" style="padding: 10px 20px; border-radius: 4px;">
                                        <a href="{ticket_url}" target="_blank" style="color: #ffffff; text-decoration: none; font-weight: bold; font-family: Arial, sans-serif;">
                                            View Ticket
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

    email = EmailMessage(
        subject=subject,
        body=message,
        to=to_emails,
        cc=cc_emails,
    )
    email.content_subtype = "html"
    email.send(fail_silently=False)

    if not is_two_hour:
        two_hours_before = ticket.deadline - timedelta(hours=2)

        if two_hours_before > timezone.now():
            next_task = send_deadline_reminder.apply_async(
                args=[ticket.id], kwargs={"is_two_hour": True}, eta=two_hours_before
            )
            ticket.reminder_task_id = next_task.id
        else:
            ticket.reminder_task_id = None
    else:
        ticket.reminder_task_id = None

    ticket.save(update_fields=["reminder_task_id"])
