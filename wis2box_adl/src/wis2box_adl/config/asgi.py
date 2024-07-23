from django.core.asgi import get_asgi_application

from channels.routing import ProtocolTypeRouter

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {"http": django_asgi_app, }
)
