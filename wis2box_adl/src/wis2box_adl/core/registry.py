from django.core.exceptions import ImproperlyConfigured


class Instance(object):
    """
    This abstract class represents a custom instance that can be added to the registry.
    It must be extended so properties and methods can be added.
    """

    type = ""
    compat_type = ""

    def __init__(self):
        if not self.type:
            raise ImproperlyConfigured("The type of an instance must be set.")

    def after_register(self):
        """
        Hook that is called after an instance is registered in a registry.
        """

    def before_unregister(self):
        """
        Hook that is called before an instance is unregistered from a registry.
        """


class Registry(Instance):
    name = None

    def __init__(self):
        if not getattr(self, "name", None):
            raise ImproperlyConfigured(
                "The name must be set on an "
                "InstanceModelRegistry to raise proper errors."
            )

        self.registry = {}

    def get(self, type_name):
        """
        Returns a registered instance of the given type name.

        :param type_name: The unique name of the registered instance.
        :type type_name: str
        :raises InstanceTypeDoesNotExist: If the instance with the provided `type_name`
            does not exist in the registry.
        :return: The requested instance.
        :rtype: InstanceModelInstance
        """

        # If the `type_name` isn't in the registry,
        # we may raise `InstanceTypeDoesNotExist`.
        if type_name not in self.registry:
            # But first, we'll test to see if it matches an Instance's
            # `compat_name`. If it does, we'll use that Instance's `type`.
            type_name_via_compat = self.get_by_type_name_by_compat(type_name)
            if type_name_via_compat:
                type_name = type_name_via_compat
            else:
                raise self.does_not_exist_exception_class(
                    type_name, f"The {self.name} type {type_name} does not exist."
                )

        return self.registry[type_name]

    def get_by_type_name_by_compat(self, compat_name):
        """
        Returns a registered instance's `type` by using the compatibility name.
        """

        for instance in self.get_all():
            if instance.compat_type == compat_name:
                return instance.type

    def get_by_type(self, instance_type):
        return self.get(instance_type.type)

    def get_all(self):
        """
        Returns all registered instances

        :return: A list of the registered instances.
        :rtype: List[InstanceModelInstance]
        """

        return self.registry.values()

    def get_types(self):
        """
        Returns a list of available type names.

        :return: The list of available types.
        :rtype: List
        """

        return list(self.registry.keys())

    def get_types_as_tuples(self):
        """
        Returns a list of available type names.

        :return: The list of available types.
        :rtype: List[Tuple[str,str]]
        """

        return [(k, k) for k in self.registry.keys()]

    def register(self, instance):
        """
        Registers a new instance in the registry.

        :param instance: The instance that needs to be registered.
        :type instance: Instance
        :raises ValueError: When the provided instance is not an instance of Instance.
        :raises InstanceTypeAlreadyRegistered: When the instance's type has already
            been registered.
        """

        if not isinstance(instance, Instance):
            raise ValueError(f"The {self.name} must be an instance of Instance.")

        if instance.type in self.registry:
            raise self.already_registered_exception_class(
                f"The {self.name} with type {instance.type} is already registered."
            )

        self.registry[instance.type] = instance

        instance.after_register()

    def unregister(self, value):
        """
        Removes a registered instance from the registry. An instance or type name can be
        provided as value.

        :param value: The instance or type name.
        :type value: Instance or str
        :raises ValueError: If the provided value is not an instance of Instance or
            string containing the type name.
        """

        if isinstance(value, Instance):
            for type_name, instance in self.registry.items():
                if instance == value:
                    value = type_name

        if isinstance(value, str):
            instance = self.registry[value]
            instance.before_unregister()
            del self.registry[value]
        else:
            raise ValueError(
                f"The value must either be an {self.name} instance or type name"
            )
