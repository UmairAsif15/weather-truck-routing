from django.urls import include, path, re_path

from trips.views import spa_index

urlpatterns = [
    path("api/", include("trips.urls")),
    # Everything that is not the API is handled by the React single-page app.
    re_path(r"^(?!api/|static/).*$", spa_index, name="spa"),
]
