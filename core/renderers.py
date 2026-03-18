from rest_framework.renderers import JSONRenderer


class GlobalJSONRenderer(JSONRenderer):
    """
    Custom Renderer to standardize all API responses into a unified JSON structure.

    This renderer intercepts the response data and wraps it in a consistent
    'envelope' containing success status, messages, and error details.

    Response Structure:
        {
            "success": bool,    # True if status < 400
            "message": str,     # Summary of the outcome
            "data": dict/list,  # The actual payload
            "errors": dict/list # Error details
        }
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        """
        Customizes the final output before it is sent to the client.
        But also checks if Pagination applied standardization already.

        Args:
            data: The data returned by the view or serializer.
            accepted_media_type: The content type being requested.
            renderer_context: Dictionary containing 'response', 'view', etc.

        Returns:
            A JSON-rendered string of the standardized response dictionary.
        """
        if isinstance(data, dict) and "success" in data:
            return super().render(data, accepted_media_type, renderer_context)

        response = renderer_context.get("response") if renderer_context else None
        status_code = response.status_code if response else 200

        custom_message = None
        if isinstance(data, dict):
            custom_message = data.pop("message", None)

            if not custom_message and status_code >= 400:
                custom_message = data.pop("detail", None)

        is_success = status_code < 400

        response_dict = {
            "success": is_success,
            "message": custom_message or ("Success" if is_success else "Error"),
            "data": data if is_success else None,
            "errors": None if is_success else data,
        }

        return super().render(response_dict, accepted_media_type, renderer_context)
