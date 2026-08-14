Change log
==========

4.0.0
----------

Backwards incompatible changes:

- Drop support for Django 2.2 to 5.1 and Python 3.5 to 3.9. Django 5.2 and Python 3.10 are now the minimum; stay on 3.7.x/3.8.x for older releases
- The admin move controls are now submit buttons and the move views accept `POST` only. They previously changed data over `GET` without a CSRF token, so any page a logged in admin visited could reorder their data. Overridden copies of `order_controls.html`, and hand-built move URLs, need updating
- The admin move views now require the change permission on the model. `admin_site.admin_view()` only checks that the user is active staff, so any staff account could reorder any ordered model
- A `Meta.ordering` that does not include the order field is now the error `ordered_model.E007` instead of passing unnoticed. Field names are read out of `F()` and `OrderBy` expressions as well as strings
- `OrderedModelSerializer` no longer marks the order field as required, so a create without an order appends as the model does by itself

Fixes:

- `save(update_fields=...)` no longer drops the order recomputed when an object moves to another `order_with_respect_to` group, which left duplicate order values behind
- `OrderedModelSerializer` rejects a negative order and clamps a position past the end, which used to raise an `IntegrityError` or leave a permanent gap
- `top()` and `bottom()` on an empty ordering group no longer raise `TypeError`
- An `order_with_respect_to` path through a nullable relation no longer raises `AttributeError`
- `order_with_respect_to` paths are no longer resolved on every model instantiation, which cost a query per row for paths through a relation
- `save()`, `delete()`, `to()` and `swap()` re-number inside a transaction
- `OrderedManyToManyField` supports a descending `Meta.ordering` on the through model, which used to build an invalid `through__-order` lookup
- `reorder_model` accepts `--batch_size` on the command line, re-orders groups whose `order_with_respect_to` value is NULL, and skips an unknown model name instead of abandoning the models after it
- The changelist query string is kept in a `ContextVar` rather than on the `ModelAdmin`, which is shared between concurrent requests

Packaging:

- Replace `setup.py` and `requirements.txt` with `pyproject.toml`. `setup.py` declared its dependencies with `requires=`, which setuptools ignores, so the Django dependency was never installed, and without `python_requires` pip would install the package on any Python version. DRF is now the `rest` extra


3.8.0
----------
- Fix `post_delete` signal triggered upshuffles to do a potentially expensive full reordering of the owrt group (#307)
- Support passing custom `--batch_size` to `reorder_model` management command (#303)
- Add tox builder for python 3.11, Django 4.1 and above
- Add `ordered_model.fields.OrderedManyToManyField` which respects `Meta.ordering` when following ManyToMany related fields. (#277)
- Relax check that `order_with_respect_to` entries final element must be a `ForeignKey` - it can be any `Field` instance (#298)


3.7.4 - 2023-03-17
----------
- Relax Check for `OrderedModelManager` to a `Warning`, if the manager returns the correct queryset (#290)


3.7.3 - 2023-03-15
----------
- Restrict signal handler 'senders' to subclasses of `OrderedModelBase` to avoid query count regression due to `Collector.can_fast_delete` logic in `models/deletion.py` (#288)
- Fix `reorder_model` management command re-ordering with multiple `order_with_respect_to` values


3.7.2 - 2023-03-14
----------
- Fix a performance regression (unnecessary queries) in the WRT change detection (#286)
- Add a Check that `order_with_respect_to` specifies only ForeignKey fields
- Add a Check that our subclasses of ModelManager and QuerySet are used (#286) 


3.7.1 - 2023-03-06
----------

- Fix for `model.save()` falsely detecting WRT change from admin create since 3.7
- Cascaded deletes of `OrderedModel` instances now handled using signals (#182)

3.7 - 2023-03-03
----------

- Use bulk update method in `reorder_model` management command for performance (#273)
- Add tox builder for python 3.10, use upstream DRF with upstream django
- Emit a system Check failure if a subclass of `OrderedModelBase` fails to specify `Meta.ordering`
- Updating the value of fields within `order_with_respect_to` now adjusts ordering accordingly (#198)

3.6 - 2022-05-30
----------

- Add `serializers.OrderedModelSerializer` to allow Django Rest Framework to re-order models (#251 #264)
- Add tox builder for Django 4.0, drop building against 2.0 and 2.1 due to DRF compatibility.

3.5 - 2022-01-12
----------------

- Django 4.0 compatibility: Fix ChangeList constructor for Admin (#256)
- Remove usage of `assertEquals` in tests (#255)
- Add admin screenshots to README (#245)
- Fix reorder command for custom order field models (#257)


3.4.3 - 2021-04-20
------------------

- Fix packaging, setup.py was missing management command package path


3.4.2 - 2021-04-20
------------------

- Fix `OrderedTabularInline` for models with custom primary key field (#233)
- Add management command `reorder_model` that can re-order most models with a broken ordering (#240)
- Fix handling of keyword arguments passed to  `bulk_create` by Django 3 (#235)
- Fix inline admin support for Proxy Models by adding parent model to url name (#242)
- Migrated to GitHub Actions workflow (#241)

3.4.1 - 2020-05-11
------------------

- Fix regression in admin OrderedInlineMixin after refactor in 3.4.0

3.4.0 - 2020-05-11
------------------

- Fix `bulk_create` not returning
- Fix `OrderedModelQuerySet` returning parent class instances for polymorphic cases
- Support django 3.0
- Drop support python 3.4

3.3.0 - 2019-07-10
------------------

- `bulk_create` now works with `order_with_respect_to`
- more internal refactoring moved most methods to `OrderedModelQuerySet`

3.2.0 - 2019-07-10
------------------

- Internal refactoring now using `Manager` - probably will break some code
- provide `bulk_create`

3.1.1 - 2018-11-13
------------------

- Fix arrow-top and arrow-bottom not found

3.1.0 - 2018-11-10
------------------

- Remove depricated `allow_tags`
- Add `previous` and `next` methods
- Add `top` and `bottom` buttons in admin
- Delete duplicated code from InlineModelAdminMixin
- Add Simplified Chinese translations
- Use `import_string` instead of `__import__`
- Make order field's `verbose_name` translatable(NOTE: this will cause creation of new migration file, which will not affect db state)

3.0.0 - 2018-09-21
------------------

- Drop support for python 2.x
- Drop support for django 1.x
- Fix AdminInline for django > 2.1
- Do not install tests
- delete deprecated methods `move`, `move_up`, `move_down` and `_move`

2.1.0 - 2018-08-16
------------------

- Add support for Django 2.1
- Support `order_with_respect_to` on related fields
- Add Tabular and Stacked inline

2.0.0 - 2018-06-07
------------------

- Drop support for Django < 1.11

1.5.0 - 2018-06-07
------------------

- Add support for Django 2.0
- Fix problem where swap took a queryset instead of a model instance

1.4.3 - 2017-08-29
------------------

- Fix a problem with links in the admin when using multiple threads.

1.4.2 - 2017-08-18
------------------

- Use Django's version of `six`
- Fix various deprecations
- Fix missing up/down links with custom primary key

1.4.1 - 2017-04-16
------------------

### Fixed

- `pip install` not working due to missing `requirements.txt`

1.4.0 - 2017-04-14
------------------

### Added

- Support for ordering using a specified base class when using Multi-table inheritance
- Suport for Python 3.6, Django 1.10 and 1.11.

### Fixed

- The move up/down links in OrderedTabularInline
- Passing args to `filter()` which broke django-polymorphic.


1.3.0 – 2016-10-08
------------------

 - Add `extra_update` argument to various methods.
 - Fix bug in `order_with_respect_to` when using string in Python 3.

1.2.1 – 2016-07-12
------------------

 - Various bug fixes in admin
 - Add support for URL namespaces other than "admin"

1.2.0 – 2016-07-08
------------------

 - Remove support for Django <1.8 and Python 2.6
 - Support for multiple order_with_respect_to fields
 - Remove usage of deprecated django.conf.urls.patterns

1.1.0 – 2016-01-15
------------------

 - Add support for many-to-many models.
 - Add Italian translations.

1.0.0 – 2015-11-24
------------------

1.0, because why not. Seems to be working alright for everyone. Some little things in this release:

 - Add support for custom order field by inheriting from `OrderedModelBase` and setting `order_field_name`.
 - Add support for Python 3.
 - Drop support for Django 1.4.

0.4.2 – 2015-06-02
------------------

 - Fix admin buttons not working with custom primary keys.
 - Fix admin using deprecated `get_query_set` method.

0.4.1 – 2015-04-06
------------------

 - Add support for Django 1.7 and 1.8.
 - Fix deprecation warning about module\_name.
 - Add French translations.

0.4.0 – 2014-07-31
------------------

 - Models can now be moved to any position, not just up and down. `move_up()` and `move_down()` are replaced by `up()` and `down()`. See the readme for the full set of new methods.
 - Add `order_with_respect_to` option so models can be ordered based on another field.
 - The admin ordering controls are now rendered using templates.
 - Ordering now always starts from 0 and has no gaps. Previously, gaps in the ordering numbers could appear when models were deleted, etc.
 - Fix bug where objects always get the order of "0".
 - Models with custom primary keys can now be used as ordered models.


0.3.0 – 2013-10-25
------------------

 - Support for Django 1.4, 1.5 and 1.6.
 - Fix list_filter being deselected when moving in admin
 - Improve performance of ordering by adding index and using Max aggregate

0.2.0 – 2012-11-14
------------------

 - First release
