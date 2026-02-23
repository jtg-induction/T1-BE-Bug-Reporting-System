from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "date_of_birth", "designation", "phone", "jiraID", "created_at", "updated_at"]
        read_only_fields = ["email", "jiraID", "created_at", "updated_at"]
        
    def validate(self, data):
        if self.instance:
            for field_name in self.Meta.read_only_fields:
                if field_name in self.initial_data:
                    raise serializers.ValidationError({
                        field_name: "This field cannot be updated."
                    })
        return data