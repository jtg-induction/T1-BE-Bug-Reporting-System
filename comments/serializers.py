from rest_framework import serializers

from comments.models import Comment


class CommentSerializer(serializers.ModelSerializer):
    """
    Serializer for Ticket Comments.
    Handles read/write of the description
    """

    author_email = serializers.EmailField(source="author.email", read_only=True)

    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id",
            "description",
            "author",
            "author_name",
            "author_email",
            "jira_id",
            "created_at",
            "can_edit",
        ]
        read_only_fields = [
            "id",
            "author",
            "author_name",
            "jira_id",
            "created_at",
        ]

    def get_can_edit(self, obj):
        """
        Checks if the user making the request is the author of the comment.
        """
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            return obj.author == request.user

        return False
