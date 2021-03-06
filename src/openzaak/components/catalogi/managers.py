from django.db import models, transaction

from openzaak.components.autorisaties.models import AutorisatieSpec


class SyncAutorisatieManager(models.Manager):
    @transaction.atomic
    def bulk_create(self, *args, **kwargs):
        transaction.on_commit(AutorisatieSpec.sync)
        return super().bulk_create(*args, **kwargs)
