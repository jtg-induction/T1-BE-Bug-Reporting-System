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
        if isinstance(data, dict) and 'success' in data and 'metadata' in data:
            return super().render(data, accepted_media_type, renderer_context)

        response = renderer_context.get('response')
        status_code = response.status_code if response else 200
        
        response_dict = {
            "success": True if status_code < 400 else False,
            "message": "Success" if status_code < 400 else "Error",
            "data": data,
            "errors": None
        }

        if status_code >= 400:
            response_dict["errors"] = data
            response_dict["data"] = None

        return super().render(response_dict, accepted_media_type, renderer_context)