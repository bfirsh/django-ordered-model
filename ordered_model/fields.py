from django.db.models.fields.related_descriptors import (
    ManyToManyDescriptor,
    create_forward_many_to_many_manager,
)
from django.utils.functional import cached_property
from django.db import models

# OrderedManyToManyField can be used in place of ManyToManyField and will
# sort the returned data by the model Meta ordering when traversing child
# objects


def create_sorted_forward_many_to_many_manager(superclass, rel, reverse):
    cls = create_forward_many_to_many_manager(superclass, rel, reverse)

    class SortedManyRelatedManager(cls):
        def get_queryset(self):
            qs = super().get_queryset()
            m = rel.through._meta
            if m.ordering:
                ors = []
                for field in m.ordering:
                    if not isinstance(field, str):
                        # expression based ordering cannot be rewritten as a lookup
                        # path through the through model
                        continue
                    if field == "?":
                        ors.append(field)
                    elif field.startswith("-"):
                        ors.append("-" + m.model_name + "__" + field[1:])
                    else:
                        ors.append(m.model_name + "__" + field)
                if ors:
                    qs = qs.order_by(*ors)
            return qs

    return SortedManyRelatedManager


class SortedManyToManyDescriptor(ManyToManyDescriptor):
    def __init__(self, field):
        super().__init__(field.remote_field)

    @cached_property
    def related_manager_cls(self):
        related_model = self.rel.related_model if self.reverse else self.rel.model

        return create_sorted_forward_many_to_many_manager(
            related_model._default_manager.__class__,
            self.rel,
            reverse=self.reverse,
        )


class OrderedManyToManyField(models.ManyToManyField):
    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        # print(f"contributed to {cls} {name} remote_field={self.remote_field}")
        setattr(cls, self.name, SortedManyToManyDescriptor(self))
