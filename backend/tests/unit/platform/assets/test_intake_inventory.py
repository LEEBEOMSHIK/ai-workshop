from uuid import uuid4

from ai_workshop.platform.assets.intake_inventory import UploadIntakeInventory
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding


class Store:
    binding = TemporaryBinding("temporary", uuid4())
    exists = False

    def observe(self, claim):
        return self.exists


def row(store):
    return UploadIntakeRecord(
        id=uuid4(),
        workspace_id=uuid4(),
        document_id=uuid4(),
        asset_version_id=uuid4(),
        user_id=uuid4(),
        new_document=True,
        generation=None,
        existing_document_id=None,
        original_attempt_id=None,
        actual_document_id=None,
        actual_version_id=None,
        attached_original_id=None,
        attached=False,
        store_id=store.binding.store_id,
        binding_id=store.binding.binding_id,
        state="cleaned",
        revision=4,
        error_code=None,
    )


def test_presence_and_binding_are_not_hidden_by_cleaned_state():
    store = Store()
    inventory = UploadIntakeInventory(None, store)
    item = row(store)
    assert inventory._inspect(item) == set()
    store.exists = True
    assert "temporary_present" in inventory._inspect(item)
    item.binding_id = uuid4()
    assert "binding_mismatch" in inventory._inspect(item)


def test_errors_have_fixed_codes_and_no_provider_message():
    class Broken(Store):
        def observe(self, claim):
            raise RuntimeError("private/path/secret")

    store = Broken()
    assert UploadIntakeInventory(None, store)._inspect(row(store)) == {"observation_failed"}
