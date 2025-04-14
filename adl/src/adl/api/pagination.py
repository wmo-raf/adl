from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 200  # default page size
    page_size_query_param = 'limit'
    max_page_size = 1000
