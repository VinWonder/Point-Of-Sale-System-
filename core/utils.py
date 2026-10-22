from django.core.paginator import Paginator


def paginate(request, queryset, per_page=25):
    """Return the requested page of `queryset`; bad page numbers fall back gracefully."""
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))
