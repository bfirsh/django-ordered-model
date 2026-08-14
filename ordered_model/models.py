from functools import partial, reduce

from django.core import checks
from django.core.exceptions import ObjectDoesNotExist, FieldDoesNotExist
from django.db import models, router, transaction
from django.db.models import Max, Min, F
from django.db.models.fields.related import ForeignKey
from django.db.models.constants import LOOKUP_SEP
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _


def get_lookup_value(obj, wrt_field, use_fkid=True):
    # starting with obj, traverse the wrt_field path and return the value of the
    # final field. if field_path *ends* at a ForeignKey, and use_fkid=True, return the pk
    # of the fk rather than build the object itself.
    try:
        mc = type(obj)
        path = wrt_field.split(LOOKUP_SEP)
        leafindex = len(path) - 1
        for depth, p in enumerate(path):
            f = mc._meta.get_field(p)
            if depth == leafindex and use_fkid and isinstance(f, ForeignKey):
                return getattr(obj, p + "_id")
            elif depth == leafindex:
                return getattr(obj, p)
            else:
                mc = f.remote_field.model
                obj = getattr(obj, p)
                if obj is None:
                    # nullable intermediate relation, there is nothing to traverse
                    return None

    except ObjectDoesNotExist:
        return None


def get_ordering_field_names(ordering):
    # field names referenced by a Meta.ordering, or None when an entry is an
    # expression we cannot read a field name out of
    names = []
    for entry in ordering:
        if isinstance(entry, str):
            names.append(entry.lstrip("-"))
            continue
        # eg. F("order") or F("order").desc(), which wraps the F in an OrderBy
        name = getattr(getattr(entry, "expression", entry), "name", None)
        if name is None:
            return None
        names.append(name)
    return names


class OrderedModelQuerySet(models.QuerySet):
    def _get_order_field_name(self):
        return self.model.order_field_name

    def _get_order_field_lookup(self, lookup):
        order_field_name = self._get_order_field_name()
        return LOOKUP_SEP.join([order_field_name, lookup])

    def get_max_order(self):
        order_field_name = self._get_order_field_name()
        return self.aggregate(Max(order_field_name)).get(
            self._get_order_field_lookup("max")
        )

    def get_min_order(self):
        order_field_name = self._get_order_field_name()
        return self.aggregate(Min(order_field_name)).get(
            self._get_order_field_lookup("min")
        )

    def get_next_order(self):
        order = self.get_max_order()
        return order + 1 if order is not None else 0

    def above(self, order, inclusive=False):
        """Filter items above order."""
        lookup = "gte" if inclusive else "gt"
        return self.filter(**{self._get_order_field_lookup(lookup): order})

    def above_instance(self, ref, inclusive=False):
        """Filter items above ref's order."""
        order_field_name = self._get_order_field_name()
        order = getattr(ref, order_field_name)
        return self.above(order, inclusive=inclusive)

    def below(self, order, inclusive=False):
        """Filter items below order."""
        lookup = "lte" if inclusive else "lt"
        return self.filter(**{self._get_order_field_lookup(lookup): order})

    def below_instance(self, ref, inclusive=False):
        """Filter items below ref's order."""
        order_field_name = self._get_order_field_name()
        order = getattr(ref, order_field_name)
        return self.below(order, inclusive=inclusive)

    def decrease_order(self, **extra_kwargs):
        """Decrease `order_field_name` value by 1."""
        order_field_name = self._get_order_field_name()
        update_kwargs = {order_field_name: F(order_field_name) - 1}
        if extra_kwargs:
            update_kwargs.update(extra_kwargs)
        return self.update(**update_kwargs)

    def increase_order(self, **extra_kwargs):
        """Increase `order_field_name` value by 1."""
        order_field_name = self._get_order_field_name()
        update_kwargs = {order_field_name: F(order_field_name) + 1}
        if extra_kwargs:
            update_kwargs.update(extra_kwargs)
        return self.update(**update_kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        order_field_name = self._get_order_field_name()
        order_with_respect_to = self.model.get_order_with_respect_to()
        objs = list(objs)
        order_with_respect_to_mapping = {}
        for obj in objs:
            key = frozenset(obj._wrt_map().items())
            if key in order_with_respect_to_mapping:
                order_with_respect_to_mapping[key] += 1
            else:
                order_with_respect_to_mapping[key] = self.filter(
                    **obj._wrt_map()
                ).get_next_order()
            setattr(obj, order_field_name, order_with_respect_to_mapping[key])
        return super().bulk_create(objs, *args, **kwargs)


class OrderedModelManager(models.Manager.from_queryset(OrderedModelQuerySet)):
    pass


class OrderedModelBase(models.Model):
    """
    An abstract model that allows objects to be ordered relative to each other.
    Usage (See ``OrderedModel``):
     - create a model subclassing ``OrderedModelBase``
     - add an indexed ``PositiveIntegerField`` to the model
     - set ``order_field_name`` to the name of that field
     - use the same field name in ``Meta.ordering``
    [optional]
     - set ``order_with_respect_to`` to limit order to a subset
     - specify ``order_class_path`` in case of polymorphic classes
    """

    objects = OrderedModelManager()

    order_field_name = None
    order_with_respect_to = None
    order_class_path = None

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super(OrderedModelBase, self).__init__(*args, **kwargs)
        # Only the local end of each order_with_respect_to path is captured here.
        # Resolving a path such as "group__user" traverses a relation and hits the
        # database, and __init__ runs once per row loaded from a queryset, so the
        # full map is only resolved when save() sees a root value change.
        self._original_wrt_roots = self._wrt_roots()

    def _wrt_map(self):
        d = {}
        for order_wrt_name in self.get_order_with_respect_to():
            d[order_wrt_name] = get_lookup_value(self, order_wrt_name, use_fkid=True)
        return d

    def _wrt_roots(self):
        # values of the local (first) field of each order_with_respect_to path, which
        # never requires traversing a relation
        d = {}
        for order_wrt_name in self.get_order_with_respect_to():
            root = order_wrt_name.split(LOOKUP_SEP)[0]
            d[order_wrt_name] = get_lookup_value(self, root, use_fkid=True)
        return d

    def _resolve_wrt_map(self, roots):
        # expand a {path: local root value} map into a full wrt map, following the
        # relations from the given root value rather than from this instance's own
        # (possibly already reassigned) related objects
        d = {}
        for order_wrt_name, root_value in roots.items():
            path = order_wrt_name.split(LOOKUP_SEP)
            if len(path) == 1:
                d[order_wrt_name] = root_value
                continue
            f = self._meta.get_field(path[0])
            root_obj = None
            if root_value is not None and isinstance(f, ForeignKey):
                root_obj = (
                    f.remote_field.model._base_manager.filter(
                        **{f.target_field.name: root_value}
                    )
                    .order_by()
                    .first()
                )
            d[order_wrt_name] = (
                get_lookup_value(root_obj, LOOKUP_SEP.join(path[1:]), use_fkid=True)
                if root_obj is not None
                else None
            )
        return d

    def _get_related_objects(self):
        # slow path, for use in the admin which requires the objects
        # expected to generate extra queries
        return [
            get_lookup_value(self, name, use_fkid=False)
            for name in self.get_order_with_respect_to()
        ]

    @classmethod
    def _on_ordered_model_delete(cls, sender=None, instance=None, **kwargs):
        """
        This signal handler makes sure that when an OrderedModelBase is deleted via
        cascade database deletes, or queryset delete that the models keep order.
        """

        if getattr(instance, "_was_deleted_via_delete_method", False):
            return

        # upshuffle logic from OrderedModelBase.delete can't be used here because signal
        # handlers run per instance, but not necessarily in the right order
        qs = instance.get_ordering_queryset().only("pk", instance.order_field_name)
        to_update = set()
        for i, item in enumerate(qs):
            if getattr(item, instance.order_field_name) != i:
                setattr(item, instance.order_field_name, i)
                to_update.add(item)
        qs.bulk_update(to_update, (instance.order_field_name,))

        setattr(instance, "_was_deleted_via_delete_method", True)

    @classmethod
    def get_order_with_respect_to(cls):
        if type(cls.order_with_respect_to) is tuple:
            return cls.order_with_respect_to
        elif type(cls.order_with_respect_to) is str:
            return (cls.order_with_respect_to,)
        elif cls.order_with_respect_to is None:
            return tuple()
        else:
            raise ValueError("Invalid value for model.order_with_respect_to")

    def _validate_ordering_reference(self, ref):
        if self._wrt_map() != ref._wrt_map():
            raise ValueError(
                "{0!r} can only be swapped with instances of {1!r} with equal {2!s} fields.".format(
                    self,
                    self._meta.default_manager.model,
                    " and ".join(
                        ["'{}'".format(o) for o in self.get_order_with_respect_to()]
                    ),
                )
            )

    def get_ordering_queryset(self, qs=None, wrt=None):
        if qs is None:
            if self.order_class_path:
                model = import_string(self.order_class_path)
                qs = model._meta.default_manager.all()
            else:
                qs = self._meta.default_manager.all()
        if wrt:
            return qs.filter(**wrt)
        return qs.filter(**self._wrt_map())

    def previous(self):
        """
        Get previous element in this object's ordered stack.
        """
        return self.get_ordering_queryset().below_instance(self).last()

    def next(self):
        """
        Get next element in this object's ordered stack.
        """
        return self.get_ordering_queryset().above_instance(self).first()

    def _get_write_db(self, using=None):
        return using or router.db_for_write(self.__class__, instance=self)

    def _add_order_to_update_fields(self, args, kwargs):
        # the order field was just (re)computed, so it has to be written out even
        # when the caller restricted the write with update_fields
        order_field_name = self.order_field_name
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = frozenset(kwargs["update_fields"]) | {
                order_field_name
            }
        return args, kwargs

    def save(self, *args, **kwargs):
        order_field_name = self.order_field_name
        wrt_roots = self._wrt_roots()
        original_wrt_map = None
        wrt_changed = wrt_roots != self._original_wrt_roots
        if wrt_changed:
            # the local values changed, but when the path traverses a relation the
            # ordering scope itself may still be the same (eg. two groups, one user)
            original_wrt_map = self._resolve_wrt_map(self._original_wrt_roots)
            wrt_changed = self._wrt_map() != original_wrt_map

        if not (getattr(self, order_field_name) is None or wrt_changed):
            # nothing to re-number, save as usual
            super().save(*args, **kwargs)
            self._original_wrt_roots = wrt_roots
            return

        # re-numbering the siblings and writing this row must not be left half done.
        # savepoint=False keeps this off the query path of every create, as
        # Model.save_base() does for its own related writes
        with transaction.atomic(
            using=self._get_write_db(kwargs.get("using")), savepoint=False
        ):
            if wrt_changed and getattr(self, order_field_name) is not None:
                # do delete-like upshuffle using original_wrt values!
                qs = self.get_ordering_queryset(wrt=original_wrt_map)
                qs.above_instance(self).decrease_order()

            order = self.get_ordering_queryset().get_next_order()
            setattr(self, order_field_name, order)
            args, kwargs = self._add_order_to_update_fields(args, kwargs)
            super().save(*args, **kwargs)

        self._original_wrt_roots = wrt_roots

    def delete(self, *args, extra_update=None, **kwargs):
        # Flag re-ordering performed so that post_delete signal
        # does not duplicate the re-ordering. See signals.py
        self._was_deleted_via_delete_method = True

        extra_update = {} if extra_update is None else extra_update
        with transaction.atomic(using=self._get_write_db(kwargs.get("using"))):
            qs = self.get_ordering_queryset()
            qs.above_instance(self).decrease_order(**extra_update)
            return super().delete(*args, **kwargs)

    def swap(self, replacement):
        """
        Swap the position of this object with a replacement object.
        """
        self._validate_ordering_reference(replacement)

        order_field_name = self.order_field_name
        order, replacement_order = (
            getattr(self, order_field_name),
            getattr(replacement, order_field_name),
        )
        setattr(self, order_field_name, replacement_order)
        setattr(replacement, order_field_name, order)
        with transaction.atomic(using=self._get_write_db()):
            self.save()
            replacement.save()

    def up(self):
        """
        Move this object up one position.
        """
        previous = self.previous()
        if previous:
            self.swap(previous)

    def down(self):
        """
        Move this object down one position.
        """
        _next = self.next()
        if _next:
            self.swap(_next)

    def to(self, order, extra_update=None):
        """
        Move object to a certain position, updating all affected objects to move accordingly up or down.
        """
        if order is None:
            # no position to move to, eg. top()/bottom() on an empty ordering scope
            return

        if not isinstance(order, int):
            raise TypeError(
                "Order value must be set using an 'int', not using a '{0}'.".format(
                    type(order).__name__
                )
            )

        order_field_name = self.order_field_name
        if getattr(self, order_field_name) == order:
            # object is already at desired position
            return
        extra_update = {} if extra_update is None else extra_update
        with transaction.atomic(using=self._get_write_db()):
            qs = self.get_ordering_queryset()
            if getattr(self, order_field_name) > order:
                qs.below_instance(self).above(order, inclusive=True).increase_order(
                    **extra_update
                )
            else:
                qs.above_instance(self).below(order, inclusive=True).decrease_order(
                    **extra_update
                )
            setattr(self, order_field_name, order)
            self.save()

    def above(self, ref, extra_update=None):
        """
        Move this object above the referenced object.
        """
        self._validate_ordering_reference(ref)
        order_field_name = self.order_field_name
        if getattr(self, order_field_name) == getattr(ref, order_field_name):
            return
        if getattr(self, order_field_name) > getattr(ref, order_field_name):
            o = getattr(ref, order_field_name)
        else:
            o = self.get_ordering_queryset().below_instance(ref).get_max_order() or 0
        self.to(o, extra_update=extra_update)

    def below(self, ref, extra_update=None):
        """
        Move this object below the referenced object.
        """
        self._validate_ordering_reference(ref)
        order_field_name = self.order_field_name
        if getattr(self, order_field_name) == getattr(ref, order_field_name):
            return
        if getattr(self, order_field_name) > getattr(ref, order_field_name):
            o = self.get_ordering_queryset().above_instance(ref).get_min_order() or 0
        else:
            o = getattr(ref, order_field_name)
        self.to(o, extra_update=extra_update)

    def top(self, extra_update=None):
        """
        Move this object to the top of the ordered stack.
        """
        o = self.get_ordering_queryset().get_min_order()
        self.to(o, extra_update=extra_update)

    def bottom(self, extra_update=None):
        """
        Move this object to the bottom of the ordered stack.
        """
        o = self.get_ordering_queryset().get_max_order()
        self.to(o, extra_update=extra_update)

    @classmethod
    def check(cls, **kwargs):
        errors = super().check(**kwargs)

        ordering = getattr(cls._meta, "ordering", None)
        if ordering is None or len(ordering) < 1:
            errors.append(
                checks.Error(
                    "OrderedModelBase subclass needs Meta.ordering specified.",
                    hint="If you have overwritten Meta, try inheriting with Meta(OrderedModel.Meta).",
                    obj=str(cls.__qualname__),
                    id="ordered_model.E001",
                )
            )
        elif cls.order_field_name:
            names = get_ordering_field_names(ordering)
            if names is not None and cls.order_field_name not in names:
                errors.append(
                    checks.Error(
                        "OrderedModelBase subclass Meta.ordering does not include the order field '{0}'. Rows within an ordering group are then returned in an arbitrary order, so moving and re-numbering operations act on an undefined sequence.".format(
                            cls.order_field_name
                        ),
                        hint="Add '{0}' to Meta.ordering, usually as the last entry.".format(
                            cls.order_field_name
                        ),
                        obj=str(cls.__qualname__),
                        id="ordered_model.E007",
                    )
                )
        owrt = getattr(cls, "order_with_respect_to")
        if not (type(owrt) is tuple or type(owrt) is str or owrt is None):
            errors.append(
                checks.Error(
                    "OrderedModelBase subclass order_with_respect_to value invalid. Expected tuple, str or None.",
                    obj=str(cls.__qualname__),
                    id="ordered_model.E002",
                )
            )
        if not issubclass(cls.objects.__class__, OrderedModelManager):
            # Not using our Manager. This is an Error if the queryset is also wrong, or
            # a Warning if our own QuerySet is returned.
            if issubclass(cls.objects.none().__class__, OrderedModelQuerySet):
                errors.append(
                    checks.Warning(
                        "OrderedModelBase subclass has a ModelManager that does not inherit from OrderedModelManager. This is not ideal but will work.",
                        obj=str(cls.__qualname__),
                        id="ordered_model.W003",
                    )
                )
            else:
                errors.append(
                    checks.Error(
                        "OrderedModelBase subclass has a ModelManager that does not inherit from OrderedModelManager.",
                        obj=str(cls.__qualname__),
                        id="ordered_model.E003",
                    )
                )
        elif not issubclass(cls.objects.none().__class__, OrderedModelQuerySet):
            errors.append(
                checks.Error(
                    "OrderedModelBase subclass ModelManager did not return a QuerySet inheriting from OrderedModelQuerySet.",
                    obj=str(cls.__qualname__),
                    id="ordered_model.E004",
                )
            )

        # each field may be an FK ref, until the leaf which may be an FK ref or another type of field
        try:
            for wrt_field in cls.get_order_with_respect_to():
                mc = cls
                path = wrt_field.split(LOOKUP_SEP)
                leafindex = len(path) - 1
                for depth, p in enumerate(path):
                    try:
                        f = mc._meta.get_field(p)
                        if depth < leafindex and not isinstance(f, ForeignKey):
                            errors.append(
                                checks.Error(
                                    "OrderedModel order_with_respect_to specifies intermediate field '{0}' (within '{1}') which is not a ForeignKey. This is unsupported.".format(
                                        p, wrt_field
                                    ),
                                    obj=str(cls.__qualname__),
                                    id="ordered_model.E005",
                                )
                            )
                            break

                        if isinstance(f, ForeignKey):
                            mc = f.remote_field.model

                    except FieldDoesNotExist:
                        errors.append(
                            checks.Error(
                                "OrderedModel order_with_respect_to specifies field '{0}' (within '{1}') which does not exist.".format(
                                    p, wrt_field
                                ),
                                obj=str(cls.__qualname__),
                                id="ordered_model.E006",
                            )
                        )
        except ValueError:
            # already handled by type checks for E002
            pass
        return errors


class OrderedModel(OrderedModelBase):
    """
    An abstract model that allows objects to be ordered relative to each other.
    Provides an ``order`` field.
    """

    order = models.PositiveIntegerField(_("order"), editable=False, db_index=True)
    order_field_name = "order"

    class Meta:
        abstract = True
        ordering = ("order",)
