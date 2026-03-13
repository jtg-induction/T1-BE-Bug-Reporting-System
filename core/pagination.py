from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response


class StandardResultsSetPagination(LimitOffsetPagination):
    """
    Custom Limit-Offset Pagination to match the Global API Response structure.

    This class overrides the default DRF paginated response to include
    standardized success flags, messages, and a 'metadata' dictionary
    containing navigation links and record counts.

    """

    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"
    max_limit = 100

    def get_paginated_response(self, data):
        """
        Wraps the paginated data into the standardized response envelope.

        Args:
            data (list): The list of serialized objects for the current offset.

        Returns:
            Response: A DRF Response object containing the wrapped data and metadata.
        """
        return Response(
            {
                "success": True,
                "message": "Paginated data retrieved",
                "metadata": {
                    "count": self.count,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                    "limit": self.limit,
                    "offset": self.offset,
                },
                "data": data,
                "errors": None,
            }
        )
