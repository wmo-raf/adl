"""
Who may take a manual action on a connection or a dispatch channel.

The manual-action buttons — trigger a collection, dispatch now, reset the
dispatch locks, test a destination, probe a source — are registered through
``register_admin_urls``, which Wagtail wraps in ``require_admin_access``.
That gate is "any user who can log into the admin", including one
provisioned purely to read the monitoring pages, so each action needs a
gate of its own.

The gate is the **change permission for the object being acted on**, not a
dedicated permission per action: someone who can edit a connection or a
channel and its credentials can already make the runtime dial that host,
and a new permission would have to be discovered and assigned across 26
deployments before the buttons worked again.

Both models are polymorphic, and the admin registers a viewset per
*concrete subclass* — so ``change_ftpconnection`` is what a deployment
actually grants a connection operator, while ``change_networkconnection``
is what a superuser or a deliberately-global group holds. Either one is
"may edit this object", so both pass. Reading only the base would leave the
buttons visible to nobody but a superuser, which is the outcome the
"no new permission to assign" reasoning exists to avoid.

One rule, one module: the ingestion diagnostic's probe and run buttons ask
the same question about the same connection as the station-link page's
collection trigger, and two spellings of it would answer differently for an
operator granted rights on a concrete connection type — the same user, the
same object, two verdicts.
"""


def _change_perm(opts):
    return f"{opts.app_label}.change_{opts.model_name}"


def _can_change(user, instance, base_model):
    """Whether ``user`` holds the change permission for ``instance``'s own
    concrete class or for its polymorphic base ``base_model``.

    ``user`` may be ``None``: a component renders without a request in
    contexts that have no user to ask about, and the answer there is "no
    button", not an error.
    """
    if user is None:
        return False

    return (user.has_perm(_change_perm(instance._meta))
            or user.has_perm(_change_perm(base_model._meta)))


def can_manage_connection(user, connection):
    """Whether ``user`` may take a manual action against ``connection`` —
    run it, probe its source, or trigger a collection for one of its
    station links.

    A station link is gated on its connection rather than on itself: the
    connection is what holds the credentials the action will use.
    """
    from .models import NetworkConnection

    return _can_change(user, connection, NetworkConnection)


def can_manage_channel(user, channel):
    """Whether ``user`` may take a manual action against ``channel`` —
    dispatch it, reset its locks, or test its destination."""
    from .models import DispatchChannel

    return _can_change(user, channel, DispatchChannel)
