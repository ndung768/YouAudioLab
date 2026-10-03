"""Auth API — register / login (Gate A1)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.serializers import AuthLoginSerializer, AuthRegisterSerializer, user_out
from apps.workspace.services.auth import AuthService


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_register(request):
    ser = AuthRegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    user, token = AuthService().register(
        display_name=data["display_name"],
        login_identifier=data["login_identifier"],
        password=data["password"],
    )
    return Response(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": user_out(user),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_login(request):
    ser = AuthLoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    user, token = AuthService().login(
        login_identifier=data["login_identifier"],
        password=data["password"],
    )
    return Response(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": user_out(user),
        }
    )
