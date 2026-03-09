from rest_framework import serializers
from tickets.models import Ticket,TicketSubscriber
from projects.models import ProjectMember

class TicketListSerializer(serializers.ModelSerializer):
    assignee = serializers.EmailField(source='assignee.email', read_only=True)
    reporter = serializers.EmailField(source='reporter.email', read_only=True)
    project = serializers.CharField(source='project.key', read_only=True)
    project_id=serializers.UUIDField(source='project.id',read_only=True)
    is_subscribed=serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            'id', 
            'title', 
            'assignee', 
            'reporter', 
            'project', 
            'status', 
            'severity', 
            'deadline',
            'project_id',
            'jira_id',
            'is_subscribed'
        ]
    
    def get_is_subscribed(self, obj):
        request = self.context.get('request')

        if request:
            return TicketSubscriber.objects.filter(
                ticket=obj,
                user=request.user,
                status=TicketSubscriber.Status.SUBSCRIBED
            ).exists()
        
        return False

class TicketReadSerializer(TicketListSerializer):
    permission_class = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ['description','permission_class']
        read_only_fields = fields

    def get_permission_class(self, obj):
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return 1 

        user = request.user

        # Reporter : 4
        if obj.reporter == user:
            return 4
        
        # Admin : 3
        is_admin = ProjectMember.objects.filter(
            project=obj.project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE
        ).exists()
        
        if is_admin:
            return 3
        
        # Assignee : 2
        if obj.assignee == user:
            return 2
        
        # Normal Dev : 1
        return 1

class TicketWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            'id', 'title', 'description',
            'assignee', 'status', 
            'severity', 'deadline'
        ]
        
    