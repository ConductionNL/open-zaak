import datetime
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import fields, manager
from django.utils import timezone

from django_loose_fk.virtual_models import ProxyMixin
from drc_cmis.backend import CMISDRCStorageBackend
from drc_cmis.client import CMISDRCClient, exceptions
from vng_api_common.tests import reverse

from ..besluiten.models import Besluit
from ..catalogi.models.informatieobjecttype import InformatieObjectType
from ..zaken.models.zaken import Zaak
from .query import (
    InformatieobjectQuerySet,
    InformatieobjectRelatedQuerySet,
    ObjectInformatieObjectQuerySet,
)
from .utils import CMISStorageFile

logger = logging.getLogger(__name__)


def convert_timestamp_to_django_datetime(json_date):
    """
    Takes an int such as 1467717221000 as input and returns 2016-07-05 as output.
    """
    if json_date is not None:
        timestamp = int(str(json_date)[:10])
        django_datetime = timezone.make_aware(
            datetime.datetime.fromtimestamp(timestamp)
        )
        return django_datetime


def format_fields(obj, obj_fields):
    """
    Ensuring the charfields are not null and dates are in the correct format
    """
    for field in obj_fields:
        if isinstance(field, fields.CharField) or isinstance(field, fields.TextField):
            if getattr(obj, field.name) is None:
                setattr(obj, field.name, "")
        elif isinstance(field, fields.DateTimeField):
            date_value = getattr(obj, field.name)
            if isinstance(date_value, int):
                setattr(
                    obj, field.name, convert_timestamp_to_django_datetime(date_value)
                )
        elif isinstance(field, fields.DateField):
            date_value = getattr(obj, field.name)
            if isinstance(date_value, int):
                converted_datetime = convert_timestamp_to_django_datetime(date_value)
                setattr(obj, field.name, converted_datetime.date())

    return obj


def cmis_doc_to_django_model(cmis_doc):
    from .models import (
        EnkelvoudigInformatieObject,
        EnkelvoudigInformatieObjectCanonical,
    )

    # The if the document is locked, the lock_id is stored in versionSeriesCheckedOutId
    canonical = EnkelvoudigInformatieObjectCanonical()
    canonical.lock = cmis_doc.versionSeriesCheckedOutId or ""

    versie = cmis_doc.versie
    try:
        int_versie = int(Decimal(versie) * 100)
    except ValueError as e:
        int_versie = 0
    except InvalidOperation:
        int_versie = 0

    # Ensuring the charfields are not null and dates are in the correct format
    cmis_doc = format_fields(cmis_doc, EnkelvoudigInformatieObject._meta.get_fields())

    # Setting up a local file with the content of the cmis document
    uuid_with_version = cmis_doc.versionSeriesId + ";" + cmis_doc.versie
    content_file = CMISStorageFile(uuid_version=uuid_with_version,)

    document = EnkelvoudigInformatieObject(
        auteur=cmis_doc.auteur,
        begin_registratie=cmis_doc.begin_registratie,
        beschrijving=cmis_doc.beschrijving,
        bestandsnaam=cmis_doc.bestandsnaam,
        bronorganisatie=cmis_doc.bronorganisatie,
        creatiedatum=cmis_doc.creatiedatum,
        formaat=cmis_doc.formaat,
        # id=cmis_doc.versionSeriesId,
        canonical=canonical,
        identificatie=cmis_doc.identificatie,
        indicatie_gebruiksrecht=cmis_doc.indicatie_gebruiksrecht,
        informatieobjecttype=cmis_doc.informatieobjecttype,
        inhoud=content_file,
        integriteit_algoritme=cmis_doc.integriteit_algoritme,
        integriteit_datum=cmis_doc.integriteit_datum,
        integriteit_waarde=cmis_doc.integriteit_waarde,
        link=cmis_doc.link,
        ontvangstdatum=cmis_doc.ontvangstdatum,
        status=cmis_doc.status,
        taal=cmis_doc.taal,
        titel=cmis_doc.titel,
        uuid=cmis_doc.versionSeriesId,
        versie=int_versie,
        vertrouwelijkheidaanduiding=cmis_doc.vertrouwelijkheidaanduiding,
        verzenddatum=cmis_doc.verzenddatum,
    )

    return document


def cmis_gebruiksrechten_to_django(cmis_gebruiksrechten):

    from .models import EnkelvoudigInformatieObjectCanonical, Gebruiksrechten

    canonical = EnkelvoudigInformatieObjectCanonical()

    cmis_gebruiksrechten = format_fields(
        cmis_gebruiksrechten, Gebruiksrechten._meta.get_fields()
    )

    django_gebruiksrechten = Gebruiksrechten(
        uuid=cmis_gebruiksrechten.versionSeriesId,
        informatieobject=canonical,
        omschrijving_voorwaarden=cmis_gebruiksrechten.omschrijving_voorwaarden,
        startdatum=cmis_gebruiksrechten.startdatum,
        einddatum=cmis_gebruiksrechten.einddatum,
    )

    return django_gebruiksrechten


def cmis_oio_to_django(cmis_oio):

    from .models import EnkelvoudigInformatieObjectCanonical, ObjectInformatieObject

    canonical = EnkelvoudigInformatieObjectCanonical()

    django_oio = ObjectInformatieObject(
        uuid=cmis_oio.versionSeriesId,
        informatieobject=canonical,
        zaak=cmis_oio.zaak_url,
        besluit=cmis_oio.besluit_url,
        object_type=cmis_oio.related_object_type,
    )

    return django_oio


def get_object_url(the_object, object_type=None):
    """
    Retrieves the url for a local or an external object.
    """
    # Case in which the informatie_object_type is already a url
    if isinstance(the_object, str):
        return the_object
    elif isinstance(the_object, ProxyMixin):
        return the_object._initial_data["url"]
    elif object_type is not None and isinstance(the_object, object_type):
        path = reverse(the_object)
        return f"{settings.HOST_URL}{path}"


class AdapterManager(manager.Manager):
    def get_queryset(self):
        if settings.CMIS_ENABLED:
            return CMISQuerySet(model=self.model, using=self._db, hints=self._hints)
        else:
            return DjangoQuerySet(model=self.model, using=self._db, hints=self._hints)


class GebruiksrechtenAdapterManager(manager.Manager):
    def get_queryset(self):
        if settings.CMIS_ENABLED:
            return GebruiksrechtenQuerySet(
                model=self.model, using=self._db, hints=self._hints
            )
        else:
            return DjangoQuerySet(model=self.model, using=self._db, hints=self._hints)


class ObjectInformatieObjectAdapterManager(manager.Manager):
    def get_queryset(self):
        if settings.CMIS_ENABLED:
            return ObjectInformatieObjectCMISQuerySet(
                model=self.model, using=self._db, hints=self._hints
            )
        else:
            return ObjectInformatieObjectQuerySet(
                model=self.model, using=self._db, hints=self._hints
            )

    def create_from(self, relation):
        return self.get_queryset().create_from(relation)

    def delete_for(self, relation):
        return self.get_queryset().delete_for(relation)


class DjangoQuerySet(InformatieobjectQuerySet):
    pass


class CMISQuerySet(InformatieobjectQuerySet):
    """
    Find more information about the drc-cmis adapter on github here.
    https://github.com/GemeenteUtrecht/gemma-drc-cmis
    """

    _client = None
    documents = []
    has_been_filtered = False

    @property
    def get_cmis_client(self):
        if not self._client:
            self._client = CMISDRCClient()

        return self._client

    def _chain(self, **kwargs):
        obj = super()._chain(**kwargs)
        # In the super, when _clone() is performed on the queryset,
        # an SQL query is run to retrieve the objects, but with
        # alfresco it doesn't work, so the cache is re-added manually
        obj._result_cache = self._result_cache
        return obj

    def all(self):
        """
        Fetch all the needed results. from the cmis backend.
        """
        logger.debug(f"MANAGER ALL: get_documents start")
        cmis_documents = self.get_cmis_client.get_cmis_documents()
        self.documents = []
        for cmis_doc in cmis_documents["results"]:
            self.documents.append(cmis_doc_to_django_model(cmis_doc))

        self._result_cache = self.documents
        logger.debug(f"CMIS_BACKEND: get_documents successful")
        return self

    def iterator(self):
        # loop though the results to return them when requested.
        # Not tested with a filter attached to the all call.
        for document in self.documents:
            yield document

    def create(self, **kwargs):
        # The url needs to be added manually because the drc_cmis uses the 'omshrijving' as the value
        # of the informatie object type
        kwargs["informatieobjecttype"] = get_object_url(
            kwargs.get("informatieobjecttype"), InformatieObjectType
        )

        # The begin_registratie field needs to be populated (could maybe be moved in cmis library?)
        kwargs["begin_registratie"] = timezone.now()

        try:
            # Needed because the API calls the create function for an update request
            new_cmis_document = self.get_cmis_client.update_cmis_document(
                uuid=kwargs.get("uuid"),
                lock=kwargs.get("lock"),
                data=kwargs,
                content=kwargs.get("inhoud"),
            )
        except exceptions.DocumentDoesNotExistError:
            new_cmis_document = self.get_cmis_client.create_document(
                identification=kwargs.get("identificatie"),
                data=kwargs,
                content=kwargs.get("inhoud"),
            )

        django_document = cmis_doc_to_django_model(new_cmis_document)

        # TODO needed to fix test src/openzaak/components/documenten/tests/models/test_human_readable_identification.py
        # but first filters on regex need to be implemented in alfresco
        # if not django_document.identificatie:
        #     django_document.identificatie = generate_unique_identification(django_document, "creatiedatum")
        #     model_data = model_to_dict(django_document)
        #     self.filter(uuid=django_document.uuid).update(**model_data)
        return django_document

    def filter(self, *args, **kwargs):
        filters = {}
        # TODO
        # Limit filter to just exact lookup for now (until implemented in drc_cmis)
        for key, value in kwargs.items():
            new_key = key.split("__")
            if len(new_key) > 1 and new_key[1] != "exact":
                raise NotImplementedError(
                    "Fields lookups other than exact and lte are not implemented yet."
                )
            filters[new_key[0]] = value

        self._result_cache = []

        try:
            if filters.get("identificatie") is not None:
                cmis_doc = self.get_cmis_client.get_cmis_document(
                    identification=filters.get("identificatie"),
                    via_identification=True,
                    filters=None,
                )
                self._result_cache.append(cmis_doc_to_django_model(cmis_doc))
            elif filters.get("versie") is not None and filters.get("uuid") is not None:
                cmis_doc = self.get_cmis_client.get_cmis_document(
                    identification=filters.get("uuid"),
                    via_identification=False,
                    filters=None,
                )
                all_versions = cmis_doc.get_all_versions()
                for version_number, cmis_document in all_versions.items():
                    if version_number == str(filters["versie"]):
                        self._result_cache.append(
                            cmis_doc_to_django_model(cmis_document)
                        )
            elif (
                filters.get("registratie_op") is not None
                and filters.get("uuid") is not None
            ):
                cmis_doc = self.get_cmis_client.get_cmis_document(
                    identification=filters.get("uuid"),
                    via_identification=False,
                    filters=None,
                )
                all_versions = cmis_doc.get_all_versions()
                for versie, cmis_document in all_versions.items():
                    if (
                        convert_timestamp_to_django_datetime(
                            cmis_document.begin_registratie
                        )
                        <= filters["registratie_op"]
                    ):
                        self._result_cache.append(
                            cmis_doc_to_django_model(cmis_document)
                        )
                        break
            elif filters.get("uuid") is not None:
                cmis_doc = self.get_cmis_client.get_cmis_document(
                    identification=filters.get("uuid"),
                    via_identification=False,
                    filters=None,
                )
                self._result_cache.append(cmis_doc_to_django_model(cmis_doc))
            else:
                # Filter the alfresco database
                cmis_documents = self.get_cmis_client.get_cmis_documents(
                    filters=filters
                )
                for cmis_doc in cmis_documents["results"]:
                    self._result_cache.append(cmis_doc_to_django_model(cmis_doc))
        except exceptions.DocumentDoesNotExistError:
            pass

        self.documents = self._result_cache.copy()
        self.has_been_filtered = True

        return self

    def get(self, *args, **kwargs):

        if self.has_been_filtered:
            num = len(self._result_cache)
            if num == 1:
                return self._result_cache[0]
            if not num:
                raise self.model.DoesNotExist(
                    "%s matching query does not exist." % self.model._meta.object_name
                )
            raise self.model.MultipleObjectsReturned(
                "get() returned more than one %s -- it returned %s!"
                % (self.model._meta.object_name, num)
            )
        else:
            return super().get(*args, **kwargs)

    def delete(self):

        number_alfresco_updates = 0
        for django_doc in self._result_cache:
            try:
                if settings.CMIS_DELETE_IS_OBLITERATE:
                    # Actually removing the files from Alfresco
                    self.get_cmis_client.obliterate_document(django_doc.uuid)
                else:
                    # Updating all the documents from Alfresco to have 'verwijderd=True'
                    self.get_cmis_client.delete_cmis_document(django_doc.uuid)
                number_alfresco_updates += 1
            except exceptions.DocumentConflictException:
                logger.log(
                    f"Document met identificatie {django_doc.identificatie} kan niet worden gemarkeerd als verwijderd"
                )

        return number_alfresco_updates, {"cmis_document": number_alfresco_updates}

    def update(self, **kwargs):
        cmis_storage = CMISDRCStorageBackend()

        number_docs_to_update = len(self._result_cache)

        if kwargs.get("inhoud") == "":
            kwargs["inhoud"] = None

        for django_doc in self._result_cache:
            canonical_obj = django_doc.canonical
            canonical_obj.lock_document(doc_uuid=django_doc.uuid)
            cmis_storage.update_document(
                uuid=django_doc.uuid,
                lock=canonical_obj.lock,
                data=kwargs,
                content=kwargs.get("inhoud"),
            )
            canonical_obj.unlock_document(
                doc_uuid=django_doc.uuid, lock=canonical_obj.lock
            )

            self._result_cache = None

            # Should return the number of rows that have been modified
            return number_docs_to_update


class GebruiksrechtenQuerySet(InformatieobjectRelatedQuerySet):

    _client = None
    has_been_filtered = False

    def __len__(self):
        # Overwritten to prevent prefetching of related objects
        return len(self._result_cache)

    @property
    def get_cmis_client(self):
        if not self._client:
            self._client = CMISDRCClient()

        return self._client

    def _chain(self, **kwargs):
        obj = super()._chain(**kwargs)
        # In the super, when _clone() is performed on the queryset,
        # an SQL query is run to retrieve the objects, but with
        # alfresco it doesn't work, so the cache is re-added manually
        obj._result_cache = self._result_cache
        return obj

    def create(self, **kwargs):
        from .models import EnkelvoudigInformatieObject

        cmis_gebruiksrechten = self.get_cmis_client.create_cmis_gebruiksrechten(
            data=kwargs
        )

        # Get EnkelvoudigInformatieObject uuid from URL
        uuid = kwargs.get("informatieobject").split("/")[-1]
        modified_data = {"indicatie_gebruiksrecht": True}
        EnkelvoudigInformatieObject.objects.filter(uuid=uuid).update(**modified_data)

        django_gebruiksrechten = cmis_gebruiksrechten_to_django(cmis_gebruiksrechten)

        return django_gebruiksrechten

    def filter(self, *args, **kwargs):

        self._result_cache = []

        cmis_gebruiksrechten = self.get_cmis_client.get_cmis_gebruiksrechten(kwargs)

        for a_cmis_gebruiksrechten in cmis_gebruiksrechten["results"]:
            self._result_cache.append(
                cmis_gebruiksrechten_to_django(a_cmis_gebruiksrechten)
            )

        self.has_been_filtered = True

        return self


class ObjectInformatieObjectCMISQuerySet(ObjectInformatieObjectQuerySet):

    _client = None
    has_been_filtered = False

    @property
    def get_cmis_client(self):
        if not self._client:
            self._client = CMISDRCClient()

        return self._client

    def __len__(self):
        # Overwritten to prevent prefetching of related objects
        return len(self._result_cache)

    def _fetch_all(self):
        # Overwritten to prevent prefetching of related objects
        self._result_cache = []
        cmis_oio = self.get_cmis_client.get_all_cmis_oio()
        for a_cmis_oio in cmis_oio["results"]:
            self._result_cache.append(cmis_oio_to_django(a_cmis_oio))

    def _chain(self, **kwargs):
        obj = super()._chain(**kwargs)
        # In the super, when _clone() is performed on the queryset,
        # an SQL query is run to retrieve the objects, but with
        # alfresco it doesn't work, so the cache is re-added manually
        obj._result_cache = self._result_cache
        return obj

    def convert_django_names_to_alfresco(self, data):

        converted_data = {}
        object_types = {"besluit": Besluit, "zaak": Zaak}

        if data.get('object_type'):
            object_type = data.pop('object_type')
            if data.get(object_type):
                relation_object = data.pop(object_type)
            else:
                relation_object = data.pop("object")
            relation_url = get_object_url(relation_object, object_types[object_type])
            converted_data["related_object_type"] = object_type
            converted_data[f"{object_type}_url"] = relation_url

        for key, value in data.items():
            split_key = key.split("__")
            split_key[0] = split_key[0].strip("_")
            if len(split_key) > 1 and split_key[1] != "exact":
                raise NotImplementedError(
                    "Fields lookups other than exact are not implemented yet."
                )
            if split_key[0] == 'informatieobject':
                converted_data["enkelvoudiginformatieobject"] = data.get('informatieobject')
            elif object_types.get(split_key[0]):
                converted_data[f"{split_key[0]}_url"] = get_object_url(value, object_types[split_key[0]])
            else:
                converted_data[split_key[0]] = value

        return converted_data

    def all(self):
        self._fetch_all()
        return self

    def create(self, **kwargs):
        converted_data = self.convert_django_names_to_alfresco(kwargs)

        cmis_oio = self.get_cmis_client.create_cmis_oio(data=converted_data)

        django_oio = cmis_oio_to_django(cmis_oio)
        return django_oio

    def create_from(self, relation):
        object_type = self.RELATIONS[type(relation)]
        relation_object = getattr(relation, object_type)
        data = {
            "informatieobject": relation._informatieobject_url,
            "object_type": f"{object_type}",
            f"{object_type}": f"{settings.HOST_URL}{reverse(relation_object)}",
        }
        return self.create(**data)

    def delete_for(self, relation):
        object_type = self.RELATIONS[type(relation)]
        relation_object = getattr(relation, object_type)
        filters = {
            "informatieobject": relation._informatieobject_url,
            "object_type": f"{object_type}",
            f"object": relation_object,
        }
        obj = self.get(**filters)
        return obj.delete()

    def filter(self, *args, **kwargs):

        self._result_cache = []

        filters = self.convert_django_names_to_alfresco(kwargs)
        # Not needed for retrieving ObjectInformatieobjects from alfresco
        if filters.get('related_object_type'):
            filters.pop('related_object_type')

        cmis_oio = self.get_cmis_client.get_cmis_oio(filters)

        for a_cmis_oio in cmis_oio["results"]:
            self._result_cache.append(cmis_oio_to_django(a_cmis_oio))

        self.has_been_filtered = True

        return self
