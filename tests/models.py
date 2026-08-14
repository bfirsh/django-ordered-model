from django.db import models

from ordered_model.models import OrderedModel, OrderedModelBase
from ordered_model.fields import OrderedManyToManyField
import uuid


# test simple automatic ordering
class Item(OrderedModel):
    name = models.CharField(max_length=100)


# test Answer.order_with_respect_to being a tuple
class Question(models.Model):
    pass


class TestUser(models.Model):
    pass


class Answer(OrderedModel):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answers"
    )
    user = models.ForeignKey(TestUser, on_delete=models.CASCADE, related_name="answers")
    order_with_respect_to = ("question", "user")

    class Meta:
        ordering = ("question", "user", "order")

    def __unicode__(self):
        return "Answer #{0:d} of question #{1:d} for user #{2:d}".format(
            self.order, self.question_id, self.user_id
        )


# test ordering whilst overriding the automatic primary key (ie. not models.Model.id)
class CustomItem(OrderedModel):
    pkid = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100)
    modified = models.DateTimeField(null=True, blank=True)


# test ordering over custom ordering field (ie. not OrderedModel.order)
class CustomOrderFieldModel(OrderedModelBase):
    sort_order = models.PositiveIntegerField(editable=False, db_index=True)
    name = models.CharField(max_length=100)
    order_field_name = "sort_order"

    class Meta:
        ordering = ("sort_order",)


# test ThroughModel ordering with Pizzas/Topping
class Topping(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Pizza(models.Model):
    name = models.CharField(max_length=100)
    toppings = models.ManyToManyField(Topping, through="PizzaToppingsThroughModel")

    def __str__(self):
        return self.name


class PizzaToppingsThroughModel(OrderedModel):
    pizza = models.ForeignKey(Pizza, on_delete=models.CASCADE)
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE)
    order_with_respect_to = "pizza"

    class Meta:
        ordering = ("pizza", "order")


# Admin only allows each model class to be registered once. However you can register a proxy class,
# and (for presentation purposes only) rename it to match the existing in Admin
class PizzaProxy(Pizza):
    class Meta:
        proxy = True
        verbose_name = "Pizza"
        verbose_name_plural = "Pizzas"


# test many-one where the item has custom PK
class CustomPKGroup(models.Model):
    name = models.CharField(max_length=100)


class CustomPKGroupItem(OrderedModel):
    group = models.ForeignKey(CustomPKGroup, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, primary_key=True)
    order_with_respect_to = "group"


# test ordering on a base class (with order_class_path)
# ie. OpenQuestion and GroupedItem can be ordered wrt each other
class BaseQuestion(OrderedModel):
    order_class_path = __module__ + ".BaseQuestion"
    question = models.TextField(max_length=100)

    class Meta:
        ordering = ("order",)


class MultipleChoiceQuestion(BaseQuestion):
    good_answer = models.TextField(max_length=100)
    wrong_answer1 = models.TextField(max_length=100)
    wrong_answer2 = models.TextField(max_length=100)
    wrong_answer3 = models.TextField(max_length=100)


class OpenQuestion(BaseQuestion):
    answer = models.TextField(max_length=100)


# test grouping by a foreign model field (group__user)
class ItemGroup(models.Model):
    user = models.ForeignKey(
        TestUser, on_delete=models.CASCADE, related_name="item_groups"
    )


class GroupedItem(OrderedModel):
    group = models.ForeignKey(ItemGroup, on_delete=models.CASCADE, related_name="items")
    order_with_respect_to = "group__user"


# test grouping by a foreign model field through a nullable relation
class NullableGroupedItem(OrderedModel):
    group = models.ForeignKey(
        ItemGroup,
        on_delete=models.CASCADE,
        related_name="nullable_items",
        null=True,
        blank=True,
    )
    order_with_respect_to = "group__user"


class CascadedParentModel(models.Model):
    pass


class CascadedOrderedModel(OrderedModel):
    parent = models.ForeignKey(to=CascadedParentModel, on_delete=models.CASCADE)


class Flow(models.Model):
    pass


class StateMachine(OrderedModel):
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    name = models.CharField(max_length=32)
    flow = models.ForeignKey(Flow, on_delete=models.PROTECT, null=True, blank=True)
    order_with_respect_to = "flow"


# Duplicate Pizza models using OrderedManyToManyField
class PizzaOM2M(models.Model):
    name = models.CharField(max_length=100)
    toppings = OrderedManyToManyField(Topping, through="PizzaOM2MToppingsThroughModel")


class PizzaOM2MToppingsThroughModel(OrderedModel):
    pizza = models.ForeignKey(PizzaOM2M, on_delete=models.CASCADE)
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE)
    order_with_respect_to = "pizza"

    class Meta:
        ordering = ("pizza", "order")


# same, but with a descending Meta.ordering on the through model
class PizzaOM2MDesc(models.Model):
    name = models.CharField(max_length=100)
    toppings = OrderedManyToManyField(
        Topping, through="PizzaOM2MDescToppingsThroughModel"
    )


class PizzaOM2MDescToppingsThroughModel(OrderedModel):
    pizza = models.ForeignKey(PizzaOM2MDesc, on_delete=models.CASCADE)
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE)
    order_with_respect_to = "pizza"

    class Meta:
        ordering = ("pizza", "-order")


# issue 298
class Training(models.Model):
    pass


class TrainingExercise(OrderedModel, models.Model):
    WARMUP = 1
    MAINPART = 2
    ENDPART = 3
    TrainingChoices = [
        (WARMUP, "WarmUp"),
        (MAINPART, "MainPart"),
        (ENDPART, "EndPart"),
    ]
    training = models.ForeignKey(Training, on_delete=models.CASCADE)
    stage = models.PositiveSmallIntegerField(choices=TrainingChoices)
    order_with_respect_to = ("training", "stage")

    class Meta:
        ordering = ("training", "stage", "order")


# issue 320 parent/child models
class Foobar(models.Model):
    name = models.CharField(max_length=100)


class ParentModel(OrderedModel):
    name = models.CharField(max_length=100)
    foobar = models.ForeignKey(Foobar, on_delete=models.CASCADE)
    order_with_respect_to = "foobar"


class ChildModel(ParentModel):
    age = models.IntegerField()
