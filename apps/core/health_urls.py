from django.urls import path
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(_request):
    return Response({"status": "ok"})


urlpatterns = [
    path("", health, name="health"),
]
