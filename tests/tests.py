import uuid
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core import checks
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import Signal
from django.utils.timezone import now
from django.urls import reverse
from django.test import TestCase, SimpleTestCase
from django.test.utils import isolate_apps, override_system_checks
from django import VERSION


from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework import status
from tests.drf import ItemViewSet, router
from tests.utils import assertNumQueries

from ordered_model.models import OrderedModel, OrderedModelManager, OrderedModelQuerySet


from tests.models import (
    Answer,
    Item,
    Question,
    CustomItem,
    CustomOrderFieldModel,
    CustomPKGroupItem,
    CustomPKGroup,
    Pizza,
    PizzaOM2M,
    Topping,
    PizzaToppingsThroughModel,
    PizzaOM2MToppingsThroughModel,
    BaseQuestion,
    OpenQuestion,
    MultipleChoiceQuestion,
    ItemGroup,
    GroupedItem,
    TestUser,
    CascadedParentModel,
    CascadedOrderedModel,
    Flow,
    StateMachine,
    Training,
    TrainingExercise,
    Foobar,
    ChildModel,
    ParentModel,
)


class OrderGenerationTests(TestCase):
    def test_second_order_generation(self):
        first_item = Item.objects.create()
        self.assertEqual(first_item.order, 0)
        second_item = Item.objects.create()
        self.assertEqual(second_item.order, 1)


class ModelTestCase(TestCase):
    fixtures = ["test_items.json"]

    def assertNames(self, names):
        self.assertEqual(
            list(enumerate(names)), [(i.order, i.name) for i in Item.objects.all()]
        )

    def test_inserting_new_models(self):
        Item.objects.create(name="Wurble")
        self.assertNames(["1", "2", "3", "4", "Wurble"])

    def test_previous(self):
        self.assertEqual(Item.objects.get(pk=4).previous(), Item.objects.get(pk=3))

    def test_previous_first(self):
        self.assertEqual(Item.objects.get(pk=1).previous(), None)

    def test_previous_with_gap(self):
        self.assertEqual(Item.objects.get(pk=3).previous(), Item.objects.get(pk=2))

    def test_next(self):
        self.assertEqual(Item.objects.get(pk=1).next(), Item.objects.get(pk=2))

    def test_next_last(self):
        self.assertEqual(Item.objects.get(pk=4).next(), None)

    def test_next_with_gap(self):
        self.assertEqual(Item.objects.get(pk=2).next(), Item.objects.get(pk=3))

    def test_up(self):
        Item.objects.get(pk=4).up()
        self.assertNames(["1", "2", "4", "3"])

    def test_up_first(self):
        Item.objects.get(pk=1).up()
        self.assertNames(["1", "2", "3", "4"])

    def test_up_with_gap(self):
        Item.objects.get(pk=3).up()
        self.assertNames(["1", "3", "2", "4"])

    def test_down(self):
        Item.objects.get(pk=1).down()
        self.assertNames(["2", "1", "3", "4"])

    def test_down_last(self):
        Item.objects.get(pk=4).down()
        self.assertNames(["1", "2", "3", "4"])

    def test_down_with_gap(self):
        Item.objects.get(pk=2).down()
        self.assertNames(["1", "3", "2", "4"])

    def test_to(self):
        Item.objects.get(pk=4).to(0)
        self.assertNames(["4", "1", "2", "3"])
        Item.objects.get(pk=4).to(2)
        self.assertNames(["1", "2", "4", "3"])
        Item.objects.get(pk=3).to(1)
        self.assertNames(["1", "3", "2", "4"])

    def test_to_not_int(self):
        with self.assertRaises(TypeError):
            Item.objects.get(pk=4).to("1")

    def test_top(self):
        Item.objects.get(pk=4).top()
        self.assertNames(["4", "1", "2", "3"])
        Item.objects.get(pk=2).top()
        self.assertNames(["2", "4", "1", "3"])

    def test_bottom(self):
        Item.objects.get(pk=1).bottom()
        self.assertNames(["2", "3", "4", "1"])
        Item.objects.get(pk=3).bottom()
        self.assertNames(["2", "4", "1", "3"])

    def test_above(self):
        Item.objects.get(pk=3).above(Item.objects.get(pk=1))
        self.assertNames(["3", "1", "2", "4"])
        Item.objects.get(pk=4).above(Item.objects.get(pk=1))
        self.assertNames(["3", "4", "1", "2"])

    def test_above_self(self):
        Item.objects.get(pk=3).above(Item.objects.get(pk=3))
        self.assertNames(["1", "2", "3", "4"])

    def test_below(self):
        Item.objects.get(pk=1).below(Item.objects.get(pk=3))
        self.assertNames(["2", "3", "1", "4"])
        Item.objects.get(pk=3).below(Item.objects.get(pk=4))
        self.assertNames(["2", "1", "4", "3"])

    def test_below_self(self):
        Item.objects.get(pk=2).below(Item.objects.get(pk=2))
        self.assertNames(["1", "2", "3", "4"])

    def test_delete(self):
        deleted = Item.objects.get(pk=2).delete()
        # the default return value of delete is (num_deleted, deleted_count_per_model)
        # https://github.com/django/django/blob/main/django/db/models/deletion.py#L522
        self.assertEqual(deleted, (1, {"tests.Item": 1}))
        self.assertNames(["1", "3", "4"])
        Item.objects.get(pk=3).up()
        self.assertNames(["3", "1", "4"])


class OrderWithRespectToTests(TestCase):
    def setUp(self):
        q1 = Question.objects.create()
        q2 = Question.objects.create()
        u0 = TestUser.objects.create()
        self.q1_a1 = q1.answers.create(user=u0)
        self.q2_a1 = q2.answers.create(user=u0)
        self.q1_a2 = q1.answers.create(user=u0)
        self.q2_a2 = q2.answers.create(user=u0)

        with assertNumQueries(self, 1):
            Answer.objects.get(id=self.q1_a1.id)

    def test_saved_order(self):
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a1.pk, 0),
                (self.q1_a2.pk, 1),
                (self.q2_a1.pk, 0),
                (self.q2_a2.pk, 1),
            ],
        )

    def test_previous(self):
        self.assertEqual(self.q1_a2.previous(), self.q1_a1)

    def test_previous_first(self):
        self.assertEqual(self.q2_a1.previous(), None)

    def test_next(self):
        self.assertEqual(self.q2_a1.next(), self.q2_a2)

    def test_next_last(self):
        self.assertEqual(self.q1_a2.next(), None)

    def test_swap(self):
        with self.assertRaises(ValueError):
            self.q1_a1.swap(self.q2_a1)

        self.q1_a1.swap(self.q1_a2)
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a2.pk, 0),
                (self.q1_a1.pk, 1),
                (self.q2_a1.pk, 0),
                (self.q2_a2.pk, 1),
            ],
        )

    def test_up(self):
        self.q1_a2.up()
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a2.pk, 0),
                (self.q1_a1.pk, 1),
                (self.q2_a1.pk, 0),
                (self.q2_a2.pk, 1),
            ],
        )

    def test_down(self):
        self.q2_a1.down()
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a1.pk, 0),
                (self.q1_a2.pk, 1),
                (self.q2_a2.pk, 0),
                (self.q2_a1.pk, 1),
            ],
        )

    def test_to(self):
        self.q2_a1.to(1)
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a1.pk, 0),
                (self.q1_a2.pk, 1),
                (self.q2_a2.pk, 0),
                (self.q2_a1.pk, 1),
            ],
        )

    def test_above(self):
        with self.assertRaises(ValueError):
            self.q1_a2.above(self.q2_a1)
        self.q1_a2.above(self.q1_a1)
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a2.pk, 0),
                (self.q1_a1.pk, 1),
                (self.q2_a1.pk, 0),
                (self.q2_a2.pk, 1),
            ],
        )

    def test_below(self):
        with self.assertRaises(ValueError):
            self.q2_a1.below(self.q1_a2)
        self.q2_a1.below(self.q2_a2)
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a1.pk, 0),
                (self.q1_a2.pk, 1),
                (self.q2_a2.pk, 0),
                (self.q2_a1.pk, 1),
            ],
        )

    def test_top(self):
        self.q1_a2.top()
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a2.pk, 0),
                (self.q1_a1.pk, 1),
                (self.q2_a1.pk, 0),
                (self.q2_a2.pk, 1),
            ],
        )

    def test_bottom(self):
        self.q2_a1.bottom()
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_a1.pk, 0),
                (self.q1_a2.pk, 1),
                (self.q2_a2.pk, 0),
                (self.q2_a1.pk, 1),
            ],
        )


class OrderWithRespectToReorderTests(TestCase):
    def setUp(self):
        q1 = Question.objects.create()
        self.u0 = TestUser.objects.create()
        self.u1 = TestUser.objects.create()
        self.u0_a1 = q1.answers.create(user=self.u0)
        self.u0_a2 = q1.answers.create(user=self.u0)
        self.u0_a3 = q1.answers.create(user=self.u0)
        self.u1_a1 = q1.answers.create(user=self.u1)
        self.u1_a2 = q1.answers.create(user=self.u1)
        self.u1_a3 = q1.answers.create(user=self.u1)

        with assertNumQueries(self, 1):
            Answer.objects.get(id=self.u0_a1.id)

    def test_reorder_when_field_value_changed(self):
        self.u0_a2.user = self.u1
        with assertNumQueries(self, 4):
            self.u0_a2.save()

        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.u0_a1.pk, 0),
                (self.u0_a3.pk, 1),
                (self.u1_a1.pk, 0),
                (self.u1_a2.pk, 1),
                (self.u1_a3.pk, 2),
                (self.u0_a2.pk, 3),
            ],
        )


class CustomPKTest(TestCase):
    def setUp(self):
        self.item1 = CustomItem.objects.create(pkid=str(uuid.uuid4()), name="1")
        self.item2 = CustomItem.objects.create(pkid=str(uuid.uuid4()), name="2")
        self.item3 = CustomItem.objects.create(pkid=str(uuid.uuid4()), name="3")
        self.item4 = CustomItem.objects.create(pkid=str(uuid.uuid4()), name="4")

    def test_saved_order(self):
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order"),
            [
                (self.item1.pk, 0),
                (self.item2.pk, 1),
                (self.item3.pk, 2),
                (self.item4.pk, 3),
            ],
        )

    def test_order_to_extra_update(self):
        modified_time = now()
        self.item1.to(3, extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item2.pk, 0, modified_time),
                (self.item3.pk, 1, modified_time),
                (self.item4.pk, 2, modified_time),
                # This one is the primary item being operated on and modified would be
                # handled via auto_now or something
                (self.item1.pk, 3, None),
            ],
        )

    def test_bottom_extra_update(self):
        modified_time = now()
        self.item1.bottom(extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item2.pk, 0, modified_time),
                (self.item3.pk, 1, modified_time),
                (self.item4.pk, 2, modified_time),
                # This one is the primary item being operated on and modified would be
                # handled via auto_now or something
                (self.item1.pk, 3, None),
            ],
        )

    def test_top_extra_update(self):
        modified_time = now()
        self.item4.top(extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item4.pk, 0, None),
                (self.item1.pk, 1, modified_time),
                (self.item2.pk, 2, modified_time),
                # This one is the primary item being operated on and modified would be
                # handled via auto_now or something
                (self.item3.pk, 3, modified_time),
            ],
        )

    def test_below_extra_update(self):
        modified_time = now()
        self.item1.below(self.item4, extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item2.pk, 0, modified_time),
                (self.item3.pk, 1, modified_time),
                (self.item4.pk, 2, modified_time),
                # This one is the primary item being operated on and modified would be
                # handled via auto_now or something
                (self.item1.pk, 3, None),
            ],
        )

    def test_above_extra_update(self):
        modified_time = now()
        self.item4.above(self.item1, extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item4.pk, 0, None),
                (self.item1.pk, 1, modified_time),
                (self.item2.pk, 2, modified_time),
                # This one is the primary item being operated on and modified would be
                # handled via auto_now or something
                (self.item3.pk, 3, modified_time),
            ],
        )

    def test_delete_extra_update(self):
        modified_time = now()
        self.item1.delete(extra_update={"modified": modified_time})
        self.assertSequenceEqual(
            CustomItem.objects.values_list("pk", "order", "modified"),
            [
                (self.item2.pk, 0, modified_time),
                (self.item3.pk, 1, modified_time),
                (self.item4.pk, 2, modified_time),
            ],
        )


class CustomOrderFieldTest(TestCase):
    fixtures = ["test_items.json"]

    def assertNames(self, names):
        self.assertEqual(
            list(enumerate(names)),
            [(i.sort_order, i.name) for i in CustomOrderFieldModel.objects.all()],
        )

    def test_inserting_new_models(self):
        CustomOrderFieldModel.objects.create(name="Wurble")
        self.assertNames(["1", "2", "3", "4", "Wurble"])

    def test_previous(self):
        self.assertEqual(
            CustomOrderFieldModel.objects.get(pk=4).previous(),
            CustomOrderFieldModel.objects.get(pk=3),
        )

    def test_previous_first(self):
        self.assertEqual(CustomOrderFieldModel.objects.get(pk=1).previous(), None)

    def test_previous_with_gap(self):
        self.assertEqual(
            CustomOrderFieldModel.objects.get(pk=3).previous(),
            CustomOrderFieldModel.objects.get(pk=2),
        )

    def test_next(self):
        self.assertEqual(
            CustomOrderFieldModel.objects.get(pk=1).next(),
            CustomOrderFieldModel.objects.get(pk=2),
        )

    def test_next_last(self):
        self.assertEqual(CustomOrderFieldModel.objects.get(pk=4).next(), None)

    def test_next_with_gap(self):
        self.assertEqual(
            CustomOrderFieldModel.objects.get(pk=2).next(),
            CustomOrderFieldModel.objects.get(pk=3),
        )

    def test_up(self):
        CustomOrderFieldModel.objects.get(pk=4).up()
        self.assertNames(["1", "2", "4", "3"])

    def test_up_first(self):
        CustomOrderFieldModel.objects.get(pk=1).up()
        self.assertNames(["1", "2", "3", "4"])

    def test_up_with_gap(self):
        CustomOrderFieldModel.objects.get(pk=3).up()
        self.assertNames(["1", "3", "2", "4"])

    def test_down(self):
        CustomOrderFieldModel.objects.get(pk=1).down()
        self.assertNames(["2", "1", "3", "4"])

    def test_down_last(self):
        CustomOrderFieldModel.objects.get(pk=4).down()
        self.assertNames(["1", "2", "3", "4"])

    def test_down_with_gap(self):
        CustomOrderFieldModel.objects.get(pk=2).down()
        self.assertNames(["1", "3", "2", "4"])

    def test_to(self):
        CustomOrderFieldModel.objects.get(pk=4).to(0)
        self.assertNames(["4", "1", "2", "3"])
        CustomOrderFieldModel.objects.get(pk=4).to(2)
        self.assertNames(["1", "2", "4", "3"])
        CustomOrderFieldModel.objects.get(pk=3).to(1)
        self.assertNames(["1", "3", "2", "4"])

    def test_top(self):
        CustomOrderFieldModel.objects.get(pk=4).top()
        self.assertNames(["4", "1", "2", "3"])
        CustomOrderFieldModel.objects.get(pk=2).top()
        self.assertNames(["2", "4", "1", "3"])

    def test_bottom(self):
        CustomOrderFieldModel.objects.get(pk=1).bottom()
        self.assertNames(["2", "3", "4", "1"])
        CustomOrderFieldModel.objects.get(pk=3).bottom()
        self.assertNames(["2", "4", "1", "3"])

    def test_above(self):
        CustomOrderFieldModel.objects.get(pk=3).above(
            CustomOrderFieldModel.objects.get(pk=1)
        )
        self.assertNames(["3", "1", "2", "4"])
        CustomOrderFieldModel.objects.get(pk=4).above(
            CustomOrderFieldModel.objects.get(pk=1)
        )
        self.assertNames(["3", "4", "1", "2"])

    def test_above_self(self):
        CustomOrderFieldModel.objects.get(pk=3).above(
            CustomOrderFieldModel.objects.get(pk=3)
        )
        self.assertNames(["1", "2", "3", "4"])

    def test_below(self):
        CustomOrderFieldModel.objects.get(pk=1).below(
            CustomOrderFieldModel.objects.get(pk=3)
        )
        self.assertNames(["2", "3", "1", "4"])
        CustomOrderFieldModel.objects.get(pk=3).below(
            CustomOrderFieldModel.objects.get(pk=4)
        )
        self.assertNames(["2", "1", "4", "3"])

    def test_below_self(self):
        CustomOrderFieldModel.objects.get(pk=2).below(
            CustomOrderFieldModel.objects.get(pk=2)
        )
        self.assertNames(["1", "2", "3", "4"])

    def test_delete(self):
        CustomOrderFieldModel.objects.get(pk=2).delete()
        self.assertNames(["1", "3", "4"])
        CustomOrderFieldModel.objects.get(pk=3).up()
        self.assertNames(["3", "1", "4"])


class OrderedModelAdminTest(TestCase):
    def setUp(self):
        User.objects.create_superuser("admin", "a@example.com", "admin")
        self.assertTrue(self.client.login(username="admin", password="admin"))
        Item.objects.create(name="item1")
        Item.objects.create(name="item2")
        Item.objects.create(name="item3")

        self.ham = Topping.objects.create(name="Ham")
        self.pineapple = Topping.objects.create(name="Pineapple")

        self.pizza = Pizza.objects.create(name="Hawaiian Pizza")
        self.pizza_to_ham = PizzaToppingsThroughModel.objects.create(
            pizza=self.pizza, topping=self.ham
        )
        self.pizza_to_pineapple = PizzaToppingsThroughModel.objects.create(
            pizza=self.pizza, topping=self.pineapple
        )

    def test_move_links(self):
        res = self.client.get("/admin/tests/item/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("/admin/tests/item/1/move-up/", str(res.content))
        self.assertIn("/admin/tests/item/1/move-down/", str(res.content))
        self.assertIn("/admin/tests/item/1/move-top/", str(res.content))
        self.assertIn("/admin/tests/item/1/move-bottom/", str(res.content))

    def test_move_invalid_direction(self):
        res = self.client.get("/admin/tests/item/1/move-middle/")
        self.assertEqual(res.status_code, 404)

    def test_move_down(self):
        self.assertEqual(Item.objects.get(name="item1").order, 0)
        self.assertEqual(Item.objects.get(name="item2").order, 1)
        res = self.client.get("/admin/tests/item/1/move-down/")
        self.assertRedirects(res, "/admin/tests/item/")
        self.assertEqual(Item.objects.get(name="item1").order, 1)
        self.assertEqual(Item.objects.get(name="item2").order, 0)

    def test_move_up(self):
        self.assertEqual(Item.objects.get(name="item1").order, 0)
        self.assertEqual(Item.objects.get(name="item2").order, 1)
        res = self.client.get("/admin/tests/item/2/move-up/")
        self.assertRedirects(res, "/admin/tests/item/")
        self.assertEqual(Item.objects.get(name="item1").order, 1)
        self.assertEqual(Item.objects.get(name="item2").order, 0)

    def test_move_top(self):
        self.assertEqual(Item.objects.get(name="item1").order, 0)
        self.assertEqual(Item.objects.get(name="item2").order, 1)
        self.assertEqual(Item.objects.get(name="item3").order, 2)
        res = self.client.get("/admin/tests/item/3/move-top/")
        self.assertRedirects(res, "/admin/tests/item/")
        self.assertEqual(Item.objects.get(name="item1").order, 1)
        self.assertEqual(Item.objects.get(name="item2").order, 2)
        self.assertEqual(Item.objects.get(name="item3").order, 0)

    def test_move_bottom(self):
        self.assertEqual(Item.objects.get(name="item1").order, 0)
        self.assertEqual(Item.objects.get(name="item2").order, 1)
        self.assertEqual(Item.objects.get(name="item3").order, 2)
        res = self.client.get("/admin/tests/item/1/move-bottom/")
        self.assertRedirects(res, "/admin/tests/item/")
        self.assertEqual(Item.objects.get(name="item1").order, 2)
        self.assertEqual(Item.objects.get(name="item2").order, 0)
        self.assertEqual(Item.objects.get(name="item3").order, 1)

    def test_move_up_down_links_ordered_inline(self):
        # model list
        res = self.client.get("/admin/tests/pizza/")
        self.assertContains(
            res, text="/admin/tests/pizza/{}/change/".format(self.pizza.id)
        )

        # model page including inlines
        res = self.client.get("/admin/tests/pizza/{}/change/".format(self.pizza.id))
        self.assertContains(
            res,
            text='<a href="/admin/tests/pizza/{}/pizzatoppingsthroughmodel/{}/move-up/">'.format(
                self.pizza.id, self.pizza_to_ham.id
            ),
        )
        self.assertContains(
            res,
            text='<a href="/admin/tests/pizza/{}/pizzatoppingsthroughmodel/{}/move-up/">'.format(
                self.pizza.id, self.pizza_to_pineapple.id
            ),
        )

        # click the move-up link
        self.assertEqual(self.pizza_to_ham.order, 0)
        self.assertEqual(self.pizza_to_pineapple.order, 1)
        res = self.client.get(
            "/admin/tests/pizza/{}/pizzatoppingsthroughmodel/{}/move-up/".format(
                self.pizza.id, self.pizza_to_pineapple.id
            ),
            follow=True,
        )
        self.pizza_to_ham.refresh_from_db()
        self.pizza_to_pineapple.refresh_from_db()
        self.assertEqual(self.pizza_to_ham.order, 1)
        self.assertEqual(self.pizza_to_pineapple.order, 0)
        self.assertEqual(res.status_code, 200)

    def test_move_up_down_proxy_stacked_inline(self):
        res = self.client.get("/admin/tests/pizzaproxy/")
        self.assertContains(
            res, text="/admin/tests/pizzaproxy/{}/change/".format(self.pizza.id)
        )

        res = self.client.get(
            "/admin/tests/pizzaproxy/{}/change/".format(self.pizza.id)
        )
        self.assertContains(
            res,
            text='<a href="/admin/tests/pizzaproxy/{}/pizzatoppingsthroughmodel/{}/move-up/">'.format(
                self.pizza.id, self.pizza_to_ham.id
            ),
        )


class OrderWithRespectToTestsManyToMany(TestCase):
    def setUp(self):
        self.t1 = Topping.objects.create(name="tomatoe")
        self.t2 = Topping.objects.create(name="mozarella")
        self.t3 = Topping.objects.create(name="anchovy")
        self.t4 = Topping.objects.create(name="mushrooms")
        self.t5 = Topping.objects.create(name="ham")
        self.p1 = Pizza.objects.create(name="Napoli")  # tomatoe, mozarella, anchovy
        self.p2 = Pizza.objects.create(
            name="Regina"
        )  # tomatoe, mozarella, mushrooms, ham
        # Now put the toppings on the pizza
        self.p1_t1 = PizzaToppingsThroughModel(pizza=self.p1, topping=self.t1)
        with assertNumQueries(self, 2):
            self.p1_t1.save()

        self.p1_t2 = PizzaToppingsThroughModel(pizza=self.p1, topping=self.t2)
        self.p1_t2.save()
        self.p1_t3 = PizzaToppingsThroughModel(pizza=self.p1, topping=self.t3)
        self.p1_t3.save()
        self.p2_t1 = PizzaToppingsThroughModel(pizza=self.p2, topping=self.t1)
        self.p2_t1.save()
        self.p2_t2 = PizzaToppingsThroughModel(pizza=self.p2, topping=self.t2)
        self.p2_t2.save()
        self.p2_t3 = PizzaToppingsThroughModel(pizza=self.p2, topping=self.t4)
        self.p2_t3.save()
        self.p2_t4 = PizzaToppingsThroughModel()
        self.p2_t4.pizza = self.p2
        self.p2_t4.topping = self.t5
        self.p2_t4.save()

    def test_saved_order(self):
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t1.topping.pk, 0),
                (self.p1_t2.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t1.topping.pk, 0),
                (self.p2_t2.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_members_order_issue277(self):
        # make order differ from pk order
        self.p1_t3.top()  # anchovy, tomatoe, mozarella,

        # ManyToMany relationship iterates by 'to' model order, ie. PK of topping
        l1 = self.p1.toppings.all().values_list("name", flat=True)
        self.assertEqual(list(l1), ["tomatoe", "mozarella", "anchovy"])  # pk order

        # Through model ordering is ordered correctly
        l2 = (
            PizzaToppingsThroughModel.objects.filter(pizza=self.p1)
            .all()
            .values_list("topping__name", flat=True)
        )
        self.assertEqual(list(l2), ["anchovy", "tomatoe", "mozarella"])  # ordered

        # explicit ordering works
        l3 = (
            self.p1.toppings.all()
            .order_by("pizzatoppingsthroughmodel__order")
            .values_list("name", flat=True)
        )
        self.assertEqual(list(l3), ["anchovy", "tomatoe", "mozarella"])  # ordered

    def test_swap(self):
        with self.assertRaises(ValueError):
            self.p1_t1.swap(self.p2_t1)

    def test_previous(self):
        self.assertEqual(self.p1_t2.previous(), self.p1_t1)

    def test_previous_first(self):
        self.assertEqual(self.p2_t1.previous(), None)

    def test_next(self):
        self.assertEqual(self.p2_t1.next(), self.p2_t2)

    def test_next_last(self):
        self.assertEqual(self.p1_t3.next(), None)

    def test_up(self):
        self.p1_t2.up()
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t2.topping.pk, 0),
                (self.p1_t1.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t1.topping.pk, 0),
                (self.p2_t2.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_down(self):
        self.p2_t1.down()
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t1.topping.pk, 0),
                (self.p1_t2.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t2.topping.pk, 0),
                (self.p2_t1.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_to(self):
        self.p2_t1.to(1)
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t1.topping.pk, 0),
                (self.p1_t2.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t2.topping.pk, 0),
                (self.p2_t1.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_above(self):
        with self.assertRaises(ValueError):
            self.p1_t2.above(self.p2_t1)
        self.p1_t2.above(self.p1_t1)
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t2.topping.pk, 0),
                (self.p1_t1.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t1.topping.pk, 0),
                (self.p2_t2.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_below(self):
        with self.assertRaises(ValueError):
            self.p2_t1.below(self.p1_t2)
        self.p2_t1.below(self.p2_t2)
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t1.topping.pk, 0),
                (self.p1_t2.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t2.topping.pk, 0),
                (self.p2_t1.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_top(self):
        self.p1_t3.top()
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t3.topping.pk, 0),
                (self.p1_t1.topping.pk, 1),
                (self.p1_t2.topping.pk, 2),
                (self.p2_t1.topping.pk, 0),
                (self.p2_t2.topping.pk, 1),
                (self.p2_t3.topping.pk, 2),
                (self.p2_t4.topping.pk, 3),
            ],
        )

    def test_bottom(self):
        self.p2_t1.bottom()
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.values_list("topping__pk", "order"),
            [
                (self.p1_t1.topping.pk, 0),
                (self.p1_t2.topping.pk, 1),
                (self.p1_t3.topping.pk, 2),
                (self.p2_t2.topping.pk, 0),
                (self.p2_t3.topping.pk, 1),
                (self.p2_t4.topping.pk, 2),
                (self.p2_t1.topping.pk, 3),
            ],
        )


class ConstructorTest(TestCase):
    def test_constructors_issue196(self):
        self.f1 = Flow.objects.create()

        self.sm1 = StateMachine(name="a", flow_id=self.f1.id)
        self.sm1.save()

        self.sm2 = StateMachine()
        self.sm2.name = "b"
        self.sm2.flow = self.f1
        self.sm2.save()

        self.sm3 = StateMachine.objects.create(name="c", flow=self.f1)

        self.assertSequenceEqual(
            StateMachine.objects.values_list("flow__pk", "order", "name"),
            [
                (self.f1.pk, 0, "a"),
                (self.f1.pk, 1, "b"),
                (self.f1.pk, 2, "c"),
            ],
        )


class OrderWithRespectToTestsOrderedManyToManyField(TestCase):
    def setUp(self):
        self.t1 = Topping.objects.create(name="tomatoe")
        self.t2 = Topping.objects.create(name="mozarella")
        self.t3 = Topping.objects.create(name="anchovy")
        self.p1 = PizzaOM2M.objects.create(name="Napoli")
        # tomatoe, mozarella, anchovy
        self.p1_t1 = PizzaOM2MToppingsThroughModel.objects.create(
            pizza=self.p1, topping=self.t1
        )
        self.p1_t2 = PizzaOM2MToppingsThroughModel.objects.create(
            pizza=self.p1, topping=self.t2
        )
        self.p1_t3 = PizzaOM2MToppingsThroughModel.objects.create(
            pizza=self.p1, topping=self.t3
        )

    def test_members_order_issue277(self):
        # make order differ from pk order
        self.p1_t3.top()  # anchovy, tomatoe, mozarella,

        # OrderedManyToMany relationship iterates by ordered model order
        l1 = self.p1.toppings.all().values_list("name", flat=True)
        self.assertEqual(list(l1), ["anchovy", "tomatoe", "mozarella"])


class MultiOrderWithRespectToTests(TestCase):
    def setUp(self):
        q1 = Question.objects.create()
        q2 = Question.objects.create()
        u1 = TestUser.objects.create()
        u2 = TestUser.objects.create()
        self.q1_u1_a1 = q1.answers.create(user=u1)
        self.q2_u1_a1 = q2.answers.create(user=u1)
        self.q1_u1_a2 = q1.answers.create(user=u1)
        self.q2_u1_a2 = q2.answers.create(user=u1)
        self.q1_u2_a1 = q1.answers.create(user=u2)
        self.q2_u2_a1 = q2.answers.create(user=u2)
        self.q1_u2_a2 = q1.answers.create(user=u2)
        self.q2_u2_a2 = q2.answers.create(user=u2)

    def test_saved_order(self):
        self.assertSequenceEqual(
            Answer.objects.values_list("pk", "order"),
            [
                (self.q1_u1_a1.pk, 0),
                (self.q1_u1_a2.pk, 1),
                (self.q1_u2_a1.pk, 0),
                (self.q1_u2_a2.pk, 1),
                (self.q2_u1_a1.pk, 0),
                (self.q2_u1_a2.pk, 1),
                (self.q2_u2_a1.pk, 0),
                (self.q2_u2_a2.pk, 1),
            ],
        )

    def test_swap_fails(self):
        with self.assertRaises(ValueError):
            self.q1_u1_a1.swap(self.q2_u1_a2)


class OrderWithRespectToRelatedModelFieldTests(TestCase):
    def setUp(self):
        self.u1 = TestUser.objects.create()
        self.u2 = TestUser.objects.create()
        self.u1_g1 = self.u1.item_groups.create()
        self.u2_g1 = self.u2.item_groups.create()
        self.u2_g2 = self.u2.item_groups.create()
        self.u1_g2 = self.u1.item_groups.create()
        self.u2_g2_i1 = self.u2_g2.items.create()
        self.u2_g1_i1 = self.u2_g1.items.create()
        self.u1_g1_i1 = self.u1_g1.items.create()
        self.u1_g2_i1 = self.u1_g2.items.create()

    def test_query_count_on_create_model(self):
        with self.assertNumQueries(2):
            # 1 for calculating the order, 1 for inserting the model
            self.u1_g1.items.create()

    def test_query_count_on_save(self):
        with self.assertNumQueries(3):
            # 2 to check for wrt field changes, 1 to update the model.
            self.u1_g1_i1.save()

    def test_query_count_on_qs(self):
        with self.assertNumQueries(1):
            list(GroupedItem.objects.all())

    def test_query_count_on_select_related_qs(self):
        with self.assertNumQueries(1):
            list(GroupedItem.objects.select_related("group__user").all())

    def test_saved_order(self):
        self.assertSequenceEqual(
            GroupedItem.objects.filter(group__user=self.u1).values_list("pk", "order"),
            [(self.u1_g1_i1.pk, 0), (self.u1_g2_i1.pk, 1)],
        )

        self.assertSequenceEqual(
            GroupedItem.objects.filter(group__user=self.u2).values_list("pk", "order"),
            [(self.u2_g2_i1.pk, 0), (self.u2_g1_i1.pk, 1)],
        )

    def test_swap(self):
        i2 = self.u1_g1.items.create()
        self.assertSequenceEqual(
            GroupedItem.objects.filter(group__user=self.u1).values_list("pk", "order"),
            [(self.u1_g1_i1.pk, 0), (self.u1_g2_i1.pk, 1), (i2.pk, 2)],
        )

        i2.swap(self.u1_g1_i1)
        self.assertSequenceEqual(
            GroupedItem.objects.filter(group__user=self.u1).values_list("pk", "order"),
            [(i2.pk, 0), (self.u1_g2_i1.pk, 1), (self.u1_g1_i1.pk, 2)],
        )

    def test_swap_fails_between_users(self):
        with self.assertRaises(ValueError):
            self.u1_g1_i1.swap(self.u2_g1_i1)

    def test_above_between_groups(self):
        i2 = self.u1_g2.items.create()
        i2.above(self.u1_g1_i1)
        self.assertSequenceEqual(
            GroupedItem.objects.filter(group__user=self.u1).values_list("pk", "order"),
            [(i2.pk, 0), (self.u1_g1_i1.pk, 1), (self.u1_g2_i1.pk, 2)],
        )


class TestOrderWithRespectToNonFKFieldsTest(TestCase):
    def setUp(self):
        self.t1 = Training.objects.create()
        self.t2 = Training.objects.create()
        tc = TrainingExercise
        self.tc = tc
        self.te1_wu_0 = TrainingExercise.objects.create(
            training=self.t1, stage=tc.WARMUP
        )
        self.te1_wu_1 = TrainingExercise.objects.create(
            training=self.t1, stage=tc.WARMUP
        )
        self.te2_wu_0 = TrainingExercise.objects.create(
            training=self.t2, stage=tc.WARMUP
        )
        self.te2_mp_0 = TrainingExercise.objects.create(
            training=self.t2, stage=tc.MAINPART
        )
        self.te2_mp_1 = TrainingExercise.objects.create(
            training=self.t2, stage=tc.MAINPART
        )

    def test_move_between_groups(self):
        tc = self.tc
        self.te2_mp_1.stage = TrainingExercise.WARMUP
        self.te2_mp_1.save()

        self.assertSequenceEqual(
            TrainingExercise.objects.all().values_list(
                "pk", "training", "stage", "order"
            ),
            [
                (1, self.t1.pk, tc.WARMUP, 0),
                (2, self.t1.pk, tc.WARMUP, 1),
                (3, self.t2.pk, tc.WARMUP, 0),
                (5, self.t2.pk, tc.WARMUP, 1),
                (4, self.t2.pk, tc.MAINPART, 0),
            ],
        )


class PolymorphicOrderGenerationTests(TestCase):
    def test_order_of_baselist(self):
        o1 = OpenQuestion.objects.create()
        self.assertEqual(o1.order, 0)
        o1.save()
        m1 = MultipleChoiceQuestion.objects.create()
        self.assertEqual(m1.order, 1)
        m1.save()
        m2 = MultipleChoiceQuestion.objects.create()
        self.assertEqual(m2.order, 2)
        m2.save()
        o2 = OpenQuestion.objects.create()
        self.assertEqual(o2.order, 3)
        o2.save()

        m2.up()
        self.assertEqual(m2.order, 1)
        m1.refresh_from_db()
        self.assertEqual(m1.order, 2)
        o2.up()
        self.assertEqual(o2.order, 2)
        m1.refresh_from_db()
        self.assertEqual(m1.order, 3)

    def test_returns_polymorphic(self):
        o1 = OpenQuestion.objects.create()
        self.assertIsInstance(o1, OpenQuestion)


class BulkCreateTests(TestCase):
    def test(self):
        Item.objects.bulk_create([Item(name="1")])
        self.assertEqual(Item.objects.get(name="1").order, 0)

    def test_multiple(self):
        Item.objects.bulk_create([Item(name="1"), Item(name="2")])
        self.assertEqual(Item.objects.get(name="1").order, 0)
        self.assertEqual(Item.objects.get(name="2").order, 1)

    def test_with_existing(self):
        Item.objects.create()
        Item.objects.bulk_create([Item(name="1")])
        self.assertEqual(Item.objects.get(name="1").order, 1)

    def test_with_multiple_existing(self):
        Item.objects.create()
        Item.objects.create()
        Item.objects.bulk_create([Item(name="1")])
        self.assertEqual(Item.objects.get(name="1").order, 2)

    def test_order_field_name(self):
        CustomOrderFieldModel.objects.bulk_create([CustomOrderFieldModel(name="1")])
        self.assertEqual(CustomOrderFieldModel.objects.get(name="1").sort_order, 0)

    def test_order_with_respect_to(self):
        hawaiian_pizza = Pizza.objects.create(name="Hawaiian Pizza")
        napoli_pizza = Pizza.objects.create(name="Napoli")
        topping = Topping.objects.create(name="mozarella")
        PizzaToppingsThroughModel.objects.create(pizza=napoli_pizza, topping=topping)
        PizzaToppingsThroughModel.objects.bulk_create(
            [PizzaToppingsThroughModel(pizza=hawaiian_pizza, topping=topping)]
        )
        self.assertEqual(
            PizzaToppingsThroughModel.objects.get(pizza=hawaiian_pizza).order, 0
        )

    def test_order_with_respect_to_multiple(self):
        hawaiian_pizza = Pizza.objects.create(name="Hawaiian Pizza")
        napoli_pizza = Pizza.objects.create(name="Napoli")
        mozarella = Topping.objects.create(name="mozarella")
        pineapple = Topping.objects.create(name="Pineapple")
        PizzaToppingsThroughModel.objects.create(pizza=napoli_pizza, topping=mozarella)
        PizzaToppingsThroughModel.objects.bulk_create(
            [
                PizzaToppingsThroughModel(pizza=hawaiian_pizza, topping=mozarella),
                PizzaToppingsThroughModel(pizza=hawaiian_pizza, topping=pineapple),
            ]
        )
        self.assertSequenceEqual(
            PizzaToppingsThroughModel.objects.filter(pizza=hawaiian_pizza).values_list(
                "order", flat=True
            ),
            [0, 1],
        )


class OrderedModelAdminWithCustomPKInlineTest(TestCase):
    def setUp(self):
        User.objects.create_superuser("admin", "a@example.com", "admin")
        self.assertTrue(self.client.login(username="admin", password="admin"))
        group = CustomPKGroup.objects.create(name="g1")
        CustomPKGroupItem.objects.create(name="g1 i1", group=group)
        CustomPKGroupItem.objects.create(name="g1 i2", group=group)
        group = CustomPKGroup.objects.create(name="g2")
        CustomPKGroupItem.objects.create(name="g2 i1", group=group)

    def test_move_links(self):
        res = self.client.get("/admin/tests/custompkgroup/1/change", follow=True)
        self.assertContains(res, text="CustomPKGroupItem object (g1 i1)")
        self.assertContains(res, text="CustomPKGroupItem object (g1 i2)")

        # Check for the inline column header
        # see Django release notes https://docs.djangoproject.com/en/dev/releases/2.2/#django-contrib-admin
        # What’s new in Django 2.2 > Minor features > django.contrib.admin > Addd a CSS class to the column headers of TabularInline
        if VERSION >= (2, 2):
            self.assertContains(
                res, text='<th class="column-move_up_down_links">Move</th>', html=True
            )
        else:
            self.assertContains(
                res, text="<th>Move</th>", html=True
            )  # pragma: no cover

        # Check move up/down links
        self.assertContains(
            res,
            text='<a href="/admin/tests/custompkgroup/1/custompkgroupitem/g1%20i1/move-up/">',
        )
        self.assertContains(
            res,
            text='<a href="/admin/tests/custompkgroup/1/custompkgroupitem/g1%20i1/move-down/">',
        )


class ReorderModelTestCase(TestCase):
    fixtures = ["test_items.json"]

    def test_reorder_with_no_respect_to(self):
        """
        Test that 'reorder_model' changes the order of OpenQuestions
        when they overlap.
        """
        OpenQuestion.objects.create(order=0)
        OpenQuestion.objects.create(order=0)
        out = StringIO()
        call_command("reorder_model", "tests.OpenQuestion", verbosity=1, stdout=out)

        self.assertSequenceEqual(
            OpenQuestion.objects.values_list("order", flat=True).order_by("order"),
            [0, 1],
        )
        self.assertIn(
            "changing order of tests.OpenQuestion (2) from 0 to 1", out.getvalue()
        )

    def test_reorder_with_respect_to(self):
        """
        Test that when 'with_respect_to' is used 'reorder_model' changes to
        values of the 'order' field to unique values.
        """
        user1 = TestUser.objects.create()
        group1 = ItemGroup.objects.create(user=user1)

        GroupedItem.objects.create(group=group1, order=0)
        GroupedItem.objects.create(group=group1, order=1)
        GroupedItem.objects.create(group=group1, order=1)
        GroupedItem.objects.create(group=group1, order=3)
        GroupedItem.objects.create(group=group1, order=4)

        user2 = TestUser.objects.create()
        group2 = ItemGroup.objects.create(user=user2)

        GroupedItem.objects.create(group=group2)
        GroupedItem.objects.create(group=group2)
        GroupedItem.objects.create(group=group2)

        out = StringIO()
        call_command("reorder_model", "tests.GroupedItem", verbosity=1, stdout=out)

        self.assertSequenceEqual(
            GroupedItem.objects.filter(group=group1)
            .values_list("order", flat=True)
            .order_by("order"),
            [0, 1, 2, 3, 4],
        )

        self.assertSequenceEqual(
            GroupedItem.objects.filter(group=group2)
            .values_list("order", flat=True)
            .order_by("order"),
            [0, 1, 2],
        )

        self.assertEqual(
            "changing order of tests.GroupedItem (3) from 1 to 2\n", out.getvalue()
        )

    def test_reorder_with_respect_to_tuple(self):
        u1 = TestUser.objects.create()
        u2 = TestUser.objects.create()
        q1 = Question.objects.create()
        q2 = Question.objects.create()

        for q in (q1, q2):
            for u in (u1, u2):
                Answer.objects.create(user=u, question=q, order=0)
                Answer.objects.create(user=u, question=q, order=0)

        self.assertSequenceEqual(
            Answer.objects.filter(user=u2, question=q1).values_list("order", flat=True),
            [0, 0],
        )

        out = StringIO()
        call_command("reorder_model", "tests.Answer", verbosity=1, stdout=out)

        self.assertSequenceEqual(
            Answer.objects.filter(user=u2, question=q1).values_list("order", flat=True),
            [0, 1],
        )

        self.assertEqual(
            (
                "changing order of tests.Answer (2) from 0 to 1\n"
                + "changing order of tests.Answer (4) from 0 to 1\n"
                + "changing order of tests.Answer (6) from 0 to 1\n"
                + "changing order of tests.Answer (8) from 0 to 1\n"
            ),
            out.getvalue(),
        )

        out = StringIO()
        call_command("reorder_model", "tests.Answer", verbosity=1, stdout=out)

        self.assertEqual("", out.getvalue())

    def test_reorder_with_custom_order_field(self):
        """
        Test that 'reorder_model' changes the order of OpenQuestions
        when they overlap.
        """
        out = StringIO()
        CustomOrderFieldModel.objects.create(name="5", sort_order=0)
        call_command(
            "reorder_model", "tests.CustomOrderFieldModel", verbosity=1, stdout=out
        )
        self.assertSequenceEqual(
            CustomOrderFieldModel.objects.values_list("sort_order", flat=True).order_by(
                "sort_order"
            ),
            [0, 1, 2, 3, 4],
        )
        self.assertIn(
            "changing order of tests.CustomOrderFieldModel (5) from 0 to 1",
            out.getvalue(),
        )

    def test_shows_alternatives(self):
        out = StringIO()
        call_command("reorder_model", "test.Missing", verbosity=1, stdout=out)
        self.assertIn("Model 'test.Missing' is not an ordered model", out.getvalue())
        self.assertIn("tests.BaseQuestion", out.getvalue())

        out = StringIO()
        call_command("reorder_model", verbosity=1, stdout=out)
        self.assertIn("tests.BaseQuestion", out.getvalue())

    def test_delete_bypass(self):
        OpenQuestion.objects.create(answer="1", order=0)
        OpenQuestion.objects.create(answer="2", order=1)
        OpenQuestion.objects.create(answer="3", order=2)
        OpenQuestion.objects.create(answer="4", order=3)

        # bypass our OrderedModel delete logic to leave a hole in ordering
        # remove signal handlers
        # print(post_delete.receivers)
        self.assertTrue(
            post_delete.disconnect(
                sender=OpenQuestion, dispatch_uid=OpenQuestion.__name__
            )
        )
        self.assertTrue(
            post_delete.disconnect(
                sender=BaseQuestion, dispatch_uid=BaseQuestion.__name__
            )
        )

        # delete on the  queryset fires post_delete, but does not call model.delete()
        OpenQuestion.objects.filter(answer="3").delete()
        post_delete.connect(
            OpenQuestion._on_ordered_model_delete,
            sender=OpenQuestion,
            dispatch_uid=OpenQuestion.__name__,
        )

        self.assertEqual([0, 1, 3], [i.order for i in OpenQuestion.objects.all()])
        self.assertEqual(
            ["1", "2", "4"], [i.answer for i in OpenQuestion.objects.all()]
        )

        # repair
        out = StringIO()
        call_command("reorder_model", "tests.OpenQuestion", stdout=out)

        self.assertEqual([0, 1, 2], [i.order for i in OpenQuestion.objects.all()])
        self.assertEqual(
            ["1", "2", "4"], [i.answer for i in OpenQuestion.objects.all()]
        )

        self.assertEqual(
            "changing order of tests.OpenQuestion (4) from 3 to 2\n", out.getvalue()
        )

    def test_reorder_with_custom_batch_size(self):
        """
        Test that 'reorder_model' can be called with a valid `batch_size` argument.
        """
        OpenQuestion.objects.create(order=0)
        OpenQuestion.objects.create(order=0)
        out = StringIO()
        call_command(
            "reorder_model", "tests.OpenQuestion", verbosity=1, stdout=out, batch_size=2
        )

        self.assertSequenceEqual(
            OpenQuestion.objects.values_list("order", flat=True).order_by("order"),
            [0, 1],
        )
        self.assertIn(
            "changing order of tests.OpenQuestion (2) from 0 to 1", out.getvalue()
        )

    def test_reorder_with_invalid_custom_batch_size(self):
        """
        Test that 'reorder_model' raises a TypeError if a non-int value is passed
        as the `batch_size` argument.
        """
        OpenQuestion.objects.create(order=0)
        OpenQuestion.objects.create(order=0)

        with self.assertRaises(TypeError):
            call_command(
                "reorder_model",
                "tests.OpenQuestion",
                verbosity=1,
                stdout=StringIO(),
                batch_size="2",
            )


class DRFTestCase(APITestCase):
    fixtures = ["test_items.json"]

    def setUp(self):
        self.item1 = CustomItem.objects.create(pkid="a", name="1")
        self.item2 = CustomItem.objects.create(pkid="b", name="2")

    def test_create_shuffles_down(self):
        data = {"name": "3", "pkid": "c", "order": "0"}
        response = self.client.post(reverse("customitem-list"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CustomItem.objects.count(), 3)
        self.assertEqual(
            response.data, {"pkid": "c", "name": "3", "modified": None, "order": 0}
        )
        self.assertEqual(CustomItem.objects.get(pkid="a").order, 1)
        self.assertEqual(CustomItem.objects.get(pkid="b").order, 2)

        # check DRF exposes the modified value
        response = self.client.get(
            reverse("customitem-detail", kwargs={"pk": "b"}), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"pkid": "b", "name": "2", "modified": None, "order": 2}
        )

    def test_patch_shuffles_down(self):
        self.item3 = CustomItem.objects.create(pkid="c", name="3")

        # re-order an item
        response = self.client.patch(
            reverse("customitem-detail", kwargs={"pk": "b"}),
            {"order": 2, "name": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"pkid": "b", "name": "x", "modified": None, "order": 2}
        )
        self.assertEqual(CustomItem.objects.count(), 3)
        self.assertEqual(CustomItem.objects.get(pkid="a").order, 0)
        self.assertEqual(CustomItem.objects.get(pkid="c").order, 1)
        self.assertEqual(CustomItem.objects.get(pkid="b").order, 2)

    def test_custom_order_field_model(self):
        response = self.client.get(
            reverse("customorderfieldmodel-detail", kwargs={"pk": 1}), {}, format="json"
        )
        self.assertEqual(response.data, {"id": 1, "name": "1", "sort_order": 0})
        # re-order a lower item to top
        response = self.client.patch(
            reverse("customorderfieldmodel-detail", kwargs={"pk": 2}),
            {"sort_order": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"id": 2, "name": "2", "sort_order": 0})
        # check old first item is pushed down
        response = self.client.get(
            reverse("customorderfieldmodel-detail", kwargs={"pk": 1}), {}, format="json"
        )
        self.assertEqual(response.data, {"id": 1, "name": "1", "sort_order": 1})

    def test_serializer_renames_order_field(self):
        response = self.client.get(
            reverse("renameditem-detail", kwargs={"pk": "b"}), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"pkid": "b", "name": "2", "renamedOrder": 1})
        # move b to top
        response = self.client.patch(
            reverse("renameditem-detail", kwargs={"pk": "b"}),
            {"renamedOrder": 0},
            format="json",
        )
        self.assertEqual(response.data, {"pkid": "b", "name": "2", "renamedOrder": 0})
        self.assertEqual(CustomItem.objects.get(pkid="b").order, 0)
        self.assertEqual(CustomItem.objects.get(pkid="a").order, 1)


@isolate_apps("tests", attr_name="apps")
@override_system_checks([checks.model_checks.check_all_models])
class ChecksTest(SimpleTestCase):
    def test_no_inherited_ordering(self):
        class TestModel(OrderedModel):
            class Meta:
                verbose_name = "unordered"

        self.maxDiff = None
        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModelBase subclass needs Meta.ordering specified.",
                    hint="If you have overwritten Meta, try inheriting with Meta(OrderedModel.Meta).",
                    obj="ChecksTest.test_no_inherited_ordering.<locals>.TestModel",
                    id="ordered_model.E001",
                )
            ],
        )

    def test_explicit_ordering(self):
        class TestModel2(OrderedModel):
            class Meta:
                verbose_name = "unordered"
                ordering = ["order"]

        self.assertEqual(checks.run_checks(app_configs=self.apps.get_app_configs()), [])

    def test_inherited_ordering(self):
        class TestModel(OrderedModel):
            class Meta(OrderedModel.Meta):
                verbose_name = "unordered"

        self.assertEqual(checks.run_checks(app_configs=self.apps.get_app_configs()), [])

    def test_bad_owrt(self):
        class TestModel(OrderedModel):
            order_with_respect_to = 7

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModelBase subclass order_with_respect_to value invalid. Expected tuple, str or None.",
                    obj="ChecksTest.test_bad_owrt.<locals>.TestModel",
                    id="ordered_model.E002",
                )
            ],
        )

    def test_bad_manager(self):
        class BadModelManager(models.Manager.from_queryset(models.QuerySet)):
            pass

        class TestModel(OrderedModel):
            objects = BadModelManager()

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModelBase subclass has a ModelManager that does not inherit from OrderedModelManager.",
                    obj="ChecksTest.test_bad_manager.<locals>.TestModel",
                    id="ordered_model.E003",
                )
            ],
        )

    def test_builtin_manager_to_queryset(self):
        class TestModel(OrderedModel):
            objects = OrderedModelQuerySet.as_manager()

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Warning(
                    msg="OrderedModelBase subclass has a ModelManager that does not inherit from OrderedModelManager. This is not ideal but will work.",
                    obj="ChecksTest.test_builtin_manager_to_queryset.<locals>.TestModel",
                    id="ordered_model.W003",
                )
            ],
        )

    def test_bad_queryset(self):
        # I've swapped the inheritance order here so that the models.QuerySet is returned
        class BadQSModelManager(
            models.Manager.from_queryset(models.QuerySet), OrderedModelManager
        ):
            pass

        class TestModel(OrderedModel):
            objects = BadQSModelManager()

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModelBase subclass ModelManager did not return a QuerySet inheriting from OrderedModelQuerySet.",
                    obj="ChecksTest.test_bad_queryset.<locals>.TestModel",
                    id="ordered_model.E004",
                )
            ],
        )

    def test_owrt_not_foreign_key(self):
        class TestModel(OrderedModel):
            name = models.CharField(max_length=100)
            order_with_respect_to = "name"

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [],
        )

    def test_owrt_not_exist(self):
        class TestModel(OrderedModel):
            order_with_respect_to = "name"

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModel order_with_respect_to specifies field 'name' (within 'name') which does not exist.",
                    obj="ChecksTest.test_owrt_not_exist.<locals>.TestModel",
                    id="ordered_model.E006",
                )
            ],
        )

    def test_owrt_leaf_not_exist(self):
        class TestTargetModel(OrderedModel):
            pass

        class TestModel(OrderedModel):
            target = models.ForeignKey(to=TestTargetModel, on_delete=models.CASCADE)
            order_with_respect_to = "target__name"

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModel order_with_respect_to specifies field 'name' (within 'target__name') which does not exist.",
                    obj="ChecksTest.test_owrt_leaf_not_exist.<locals>.TestModel",
                    id="ordered_model.E006",
                )
            ],
        )

    def test_owrt_intermediate_not_fk(self):
        class TestModel(OrderedModel):
            target = models.CharField(max_length=100)
            order_with_respect_to = "target__name"

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [
                checks.Error(
                    msg="OrderedModel order_with_respect_to specifies intermediate field 'target' (within 'target__name') which is not a ForeignKey. This is unsupported.",
                    obj="ChecksTest.test_owrt_intermediate_not_fk.<locals>.TestModel",
                    id="ordered_model.E005",
                )
            ],
        )

    def test_owrt_deep(self):
        class TestTargetModel(OrderedModel):
            name = models.CharField(max_length=100)

        class TestMiddleModel(OrderedModel):
            target = models.ForeignKey(to=TestTargetModel, on_delete=models.CASCADE)

        class TestModel(OrderedModel):
            middle = models.ForeignKey(to=TestMiddleModel, on_delete=models.CASCADE)
            order_with_respect_to = "middle__target__name"

        self.assertEqual(
            checks.run_checks(app_configs=self.apps.get_app_configs()),
            [],
        )


class TestCascadedDelete(TestCase):
    def test_that_model_when_deleted_by_cascade_still_maintains_ordering(self):
        parent_for_order_0_child = CascadedParentModel.objects.create()
        child_with_order_0 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_0_child
        )

        parent__for_order_1_child = CascadedParentModel.objects.create()
        child_with_order_1 = CascadedOrderedModel.objects.create(
            parent=parent__for_order_1_child
        )

        parent_for_order_2_child = CascadedParentModel.objects.create()
        child_with_order_2 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_2_child
        )

        # Delete positition 1 parent, now there's a hole, which child_with_order_2 should take
        parent__for_order_1_child.delete()

        # Refresh children from db
        child_with_order_0.refresh_from_db()
        child_with_order_2.refresh_from_db()

        # Assert the hole has been filled
        self.assertEqual(child_with_order_0.order, 0)
        self.assertEqual(child_with_order_2.order, 1)

    def test_that_model_when_multiple_unordered_deleted_by_cascade_still_maintain_ordering(
        self,
    ):
        parent_for_order_1_and_0_child = CascadedParentModel.objects.create()
        # reverse the order on the first two children
        child_with_order_1 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_1_and_0_child,
            order=1,
        )
        child_with_order_0 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_1_and_0_child,
            order=0,
        )
        parent_for_order_2_and_3_child = CascadedParentModel.objects.create()
        child_with_order_2 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_2_and_3_child
        )
        child_with_order_3 = CascadedOrderedModel.objects.create(
            parent=parent_for_order_2_and_3_child
        )

        # Delete positition 0 and 1 parent, now there's a hole of two, which child_with_order_2 and 3 should take
        parent_for_order_1_and_0_child.delete()

        # Refresh children from db
        child_with_order_2.refresh_from_db()
        child_with_order_3.refresh_from_db()

        # Assert the hole has been filled
        self.assertEqual(child_with_order_2.order, 0)
        self.assertEqual(child_with_order_3.order, 1)


## @pytest.mark.django_db
class ParentChildModelTests(TestCase):
    def test_parent_child_order(self):
        foobar = Foobar.objects.create(name="foobar")
        child1 = ChildModel.objects.create(name="child1", foobar=foobar, age=1)
        child2 = ChildModel.objects.create(name="child2", foobar=foobar, age=2)
        child3 = ChildModel.objects.create(name="child3", foobar=foobar, age=3)
        child4 = ChildModel.objects.create(name="child4", foobar=foobar, age=4)

        # This is the order of the children at the start
        assert child1.order == 0
        assert child2.order == 1
        assert child3.order == 2
        assert child4.order == 3

        # Delete the first child
        # This causes the parent to be deleted as well
        child1.delete()

        # Refresh the db
        child2.refresh_from_db()
        child3.refresh_from_db()
        child4.refresh_from_db()

        # The order of the children should be updated
        # The expected order
        assert child2.order == 0
        assert child3.order == 1
        assert child4.order == 2
